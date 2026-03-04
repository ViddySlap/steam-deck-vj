"""Core Windows receiver logic."""

from __future__ import annotations

import logging
import socket
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from protocol.messages import ActionEvent, HeartbeatEvent, ProtocolError, parse_action_event
from windows.config import (
    ControlChangeMapping,
    MacroCCMapping,
    MacroSettings,
    MidiMapping,
    NoteMapping,
    RelativeCCMapping,
    StagedNoteMacroMapping,
)
from windows.midi import MidiControlChange, MidiError, MidiIn, MidiOut


LOGGER = logging.getLogger(__name__)

LAYER_UNKNOWN = "unknown"
LAYER_1 = "layer_1"
LAYER_2 = "layer_2"

ABXY_LAYER_1_ACTIONS = {"BTN_A", "BTN_B", "BTN_X", "BTN_Y"}
ABXY_LAYER_2_ACTIONS = {
    "BTN_A_LAYER_2",
    "BTN_B_LAYER_2",
    "BTN_X_LAYER_2",
    "BTN_Y_LAYER_2",
}
BUMPER_LAYER_1_ACTIONS = {"L1", "R1", "L2_SOFT", "L2_FULL", "R2_SOFT", "R2_FULL"}
BUMPER_LAYER_2_ACTIONS = {
    "L1_LAYER_2",
    "R1_LAYER_2",
    "L2_SOFT_LAYER_2",
    "L2_FULL_LAYER_2",
    "R2_SOFT_LAYER_2",
    "R2_FULL_LAYER_2",
}


@dataclass
class SenderState:
    last_seq: int = -1
    last_seen: float = 0.0


@dataclass
class ActiveMacroFade:
    channel: int
    cc: int
    start_value: int
    target_value: int
    start_time: float
    duration_seconds: float


@dataclass
class ActiveRelativeCC:
    action: str
    channel: int
    cc: int
    step_value: int
    repeat_interval_seconds: float
    next_send_time: float


@dataclass
class ActiveStagedNoteMacro:
    action: str
    modifier_channel: int
    trigger_channel: int
    note: int
    velocity: int
    trigger_time: float
    off_time: float
    refresh_actions: frozenset[str]
    trigger_sent: bool = False


@dataclass
class LayerStatePublisher:
    note: int
    raw_channel: int
    layer_1_channel: int
    layer_2_channel: int
    state: str = LAYER_UNKNOWN
    last_published_state: str | None = None
    last_publish_time: float = 0.0


class ActionReceiver:
    """Receive action messages and emit mapped MIDI output."""

    def __init__(
        self,
        midi_out: MidiOut,
        mappings: dict[str, MidiMapping],
        *,
        timeout_seconds: float = 2.0,
        macro_settings: MacroSettings | None = None,
        dedupe_window_seconds: float = 0.015,
        rate_limit_window_seconds: float = 1.0,
        rate_limit_max_events: int = 200,
        rate_limit_cooldown_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._midi_out = midi_out
        self._mappings = mappings
        self._timeout_seconds = timeout_seconds
        self._macro_settings = macro_settings or MacroSettings()
        self._dedupe_window_seconds = dedupe_window_seconds
        self._rate_limit_window_seconds = rate_limit_window_seconds
        self._rate_limit_max_events = rate_limit_max_events
        self._rate_limit_cooldown_seconds = rate_limit_cooldown_seconds
        self._clock = clock
        self._sender_states: dict[tuple[str, int], SenderState] = {}
        self._active_actions: dict[str, MidiMapping] = {}
        self._recent_events: dict[tuple[str, str], float] = {}
        self._event_times: deque[float] = deque()
        self._loop_guard_until = 0.0
        self._macro_values: dict[tuple[int, int], int] = {}
        self._active_macro_fades: dict[tuple[int, int], ActiveMacroFade] = {}
        self._active_relative_ccs: dict[str, ActiveRelativeCC] = {}
        self._active_staged_note_macros: dict[str, ActiveStagedNoteMacro] = {}
        self._abxy_layer_publisher = self._build_layer_publisher("START")
        self._bumper_layer_publisher = self._build_layer_publisher("SELECT")
        self._tracked_macro_keys = {
            (mapping.channel, mapping.cc)
            for mapping in mappings.values()
            if isinstance(mapping, MacroCCMapping)
        }

    @property
    def fade_poll_interval_seconds(self) -> float | None:
        intervals: list[float] = []
        if self._active_macro_fades:
            intervals.append(self._macro_settings.step_interval_seconds)
        if self._active_relative_ccs:
            intervals.extend(
                active.repeat_interval_seconds for active in self._active_relative_ccs.values()
            )
        if self._active_staged_note_macros:
            intervals.append(0.01)
        if self._has_known_layer_state():
            intervals.append(self._macro_settings.layer_refresh_ms / 1000.0)
        if not intervals:
            return None
        return min(intervals)

    def handle_datagram(
        self, payload: bytes, addr: tuple[str, int], now: float | None = None
    ) -> bool:
        timestamp = self._clock() if now is None else now
        self.advance_fades(now=timestamp)
        self.advance_relative_ccs(now=timestamp)
        self.advance_staged_note_macros(now=timestamp)
        self.advance_layer_state_publish(now=timestamp)

        try:
            event = parse_action_event(payload)
        except ProtocolError as exc:
            LOGGER.warning("ignored invalid packet from %s:%s: %s", addr[0], addr[1], exc)
            return False

        sender = self._sender_states.setdefault(addr, SenderState())
        if event.seq <= sender.last_seq:
            LOGGER.warning(
                "ignored out-of-order packet from %s:%s seq=%s last_seq=%s",
                addr[0],
                addr[1],
                event.seq,
                sender.last_seq,
            )
            return False

        sender.last_seq = event.seq
        sender.last_seen = timestamp
        if isinstance(event, HeartbeatEvent):
            LOGGER.debug("heartbeat seq=%s from %s:%s", event.seq, addr[0], addr[1])
            return True
        if not self._allow_event(event, timestamp):
            return False
        self._update_layer_state_from_action(event, timestamp)
        self._refresh_staged_note_macros(event.action, timestamp)
        try:
            return self._dispatch_event(event, timestamp)
        except MidiError as exc:
            LOGGER.error("MIDI output error while handling %s: %s", event.action, exc)
            self._active_actions.pop(event.action, None)
            return False

    def check_timeouts(self, now: float | None = None) -> bool:
        timestamp = self._clock() if now is None else now
        self.advance_fades(now=timestamp)
        self.advance_relative_ccs(now=timestamp)
        self.advance_staged_note_macros(now=timestamp)
        self.advance_layer_state_publish(now=timestamp)
        if not self._sender_states:
            return False

        timed_out = all(
            (timestamp - sender.last_seen) >= self._timeout_seconds
            for sender in self._sender_states.values()
        )
        if not timed_out:
            return False

        if self._active_actions:
            LOGGER.warning("input timeout reached; releasing active MIDI state")
            self.release_all()
        return True

    def release_all(self) -> None:
        for action, mapping in list(self._active_actions.items()):
            try:
                self._release_mapping(action, mapping)
            except MidiError as exc:
                LOGGER.error("MIDI output error while releasing %s: %s", action, exc)
        self._active_actions.clear()
        self._active_macro_fades.clear()
        self._active_relative_ccs.clear()
        for active in list(self._active_staged_note_macros.values()):
            try:
                self._midi_out.note_off(active.modifier_channel, active.note, 0)
            except MidiError as exc:
                LOGGER.error(
                    "MIDI output error while releasing staged note macro %s: %s",
                    active.action,
                    exc,
                )
        self._active_staged_note_macros.clear()
        try:
            self._midi_out.panic()
        except MidiError as exc:
            LOGGER.error("MIDI output error during panic reset: %s", exc)

    def advance_fades(self, now: float | None = None) -> None:
        timestamp = self._clock() if now is None else now
        if not self._active_macro_fades or timestamp < self._loop_guard_until:
            return

        for key, fade in list(self._active_macro_fades.items()):
            elapsed = max(0.0, timestamp - fade.start_time)
            progress = min(1.0, elapsed / fade.duration_seconds)
            next_value = round(
                fade.start_value + (fade.target_value - fade.start_value) * progress
            )

            if self._macro_values.get(key) != next_value:
                self._send_macro_value(fade.channel, fade.cc, next_value)

            if progress >= 1.0:
                self._active_macro_fades.pop(key, None)

    def handle_midi_feedback(
        self,
        channel: int,
        cc: int,
        value: int,
        *,
        now: float | None = None,
    ) -> bool:
        key = (channel, cc)
        if key not in self._tracked_macro_keys:
            return False

        timestamp = self._clock() if now is None else now
        fade = self._active_macro_fades.get(key)
        if fade is not None:
            expected_value = self._fade_value_at(fade, timestamp)
            current_value = self._macro_values.get(key)
            if self._feedback_matches_active_fade(
                value,
                expected_value=expected_value,
                current_value=current_value,
            ):
                LOGGER.debug(
                    "ignored feedback for active fade channel=%s cc=%s value=%s",
                    channel,
                    cc,
                    value,
                )
                return False

            LOGGER.info(
                "manual override detected; canceling fade channel=%s cc=%s value=%s",
                channel,
                cc,
                value,
            )
            self._active_macro_fades.pop(key, None)

        self._macro_values[key] = value
        LOGGER.debug(
            "updated macro cache from feedback channel=%s cc=%s value=%s",
            channel,
            cc,
            value,
        )
        return True

    def advance_relative_ccs(self, now: float | None = None) -> None:
        timestamp = self._clock() if now is None else now
        if not self._active_relative_ccs or timestamp < self._loop_guard_until:
            return

        for active in list(self._active_relative_ccs.values()):
            while timestamp >= active.next_send_time:
                self._midi_out.control_change(active.channel, active.cc, active.step_value)
                active.next_send_time += active.repeat_interval_seconds

    def advance_staged_note_macros(self, now: float | None = None) -> None:
        timestamp = self._clock() if now is None else now
        if not self._active_staged_note_macros or timestamp < self._loop_guard_until:
            return

        for action, active in list(self._active_staged_note_macros.items()):
            if not active.trigger_sent and timestamp >= active.trigger_time:
                self._midi_out.note_on(active.trigger_channel, active.note, active.velocity)
                active.trigger_sent = True
            if timestamp < active.off_time:
                continue
            self._midi_out.note_off(active.modifier_channel, active.note, 0)
            self._active_staged_note_macros.pop(action, None)

    def advance_layer_state_publish(self, now: float | None = None) -> None:
        timestamp = self._clock() if now is None else now
        refresh_interval = self._macro_settings.layer_refresh_ms / 1000.0
        for publisher in (self._abxy_layer_publisher, self._bumper_layer_publisher):
            if publisher is None or publisher.state == LAYER_UNKNOWN:
                continue
            if (
                publisher.last_published_state == publisher.state
                and (timestamp - publisher.last_publish_time) < refresh_interval
            ):
                continue
            self._publish_layer_state(publisher, timestamp)

    def _allow_event(self, event: ActionEvent, timestamp: float) -> bool:
        if timestamp < self._loop_guard_until:
            LOGGER.warning(
                "dropping event during loop-guard cooldown: action=%s state=%s seq=%s",
                event.action,
                event.state,
                event.seq,
            )
            return False

        event_key = (event.action, event.state)
        previous = self._recent_events.get(event_key)
        if previous is not None and (timestamp - previous) < self._dedupe_window_seconds:
            LOGGER.debug(
                "dropped duplicate event inside %.1fms window: action=%s state=%s seq=%s",
                self._dedupe_window_seconds * 1000,
                event.action,
                event.state,
                event.seq,
            )
            self._recent_events[event_key] = timestamp
            return False
        self._recent_events[event_key] = timestamp

        self._event_times.append(timestamp)
        cutoff = timestamp - self._rate_limit_window_seconds
        while self._event_times and self._event_times[0] < cutoff:
            self._event_times.popleft()

        if len(self._event_times) <= self._rate_limit_max_events:
            return True

        self._loop_guard_until = timestamp + self._rate_limit_cooldown_seconds
        self._event_times.clear()
        LOGGER.error(
            "loop guard tripped: received %s events in %.2fs; muting MIDI for %.2fs",
            self._rate_limit_max_events + 1,
            self._rate_limit_window_seconds,
            self._rate_limit_cooldown_seconds,
        )
        self.release_all()
        return False

    def _dispatch_event(self, event: ActionEvent, timestamp: float) -> bool:
        mapping = self._mappings.get(event.action)
        if mapping is None:
            LOGGER.warning("no MIDI mapping for action %s", event.action)
            return False

        if isinstance(mapping, MacroCCMapping):
            handled = self._handle_macro_event(event, mapping, timestamp)
            if handled:
                LOGGER.info("action=%s state=%s seq=%s", event.action, event.state, event.seq)
            return handled
        if isinstance(mapping, RelativeCCMapping):
            handled = self._handle_relative_cc_event(event, mapping, timestamp)
            if handled:
                LOGGER.info("action=%s state=%s seq=%s", event.action, event.state, event.seq)
            return handled
        if isinstance(mapping, StagedNoteMacroMapping):
            handled = self._handle_staged_note_macro_event(event, mapping, timestamp)
            if handled:
                LOGGER.info("action=%s state=%s seq=%s", event.action, event.state, event.seq)
            return handled

        if event.state == "down":
            self._apply_down(mapping)
            self._active_actions[event.action] = mapping
            LOGGER.info("action=%s state=down seq=%s", event.action, event.seq)
            return True

        self._release_mapping(event.action, mapping)
        self._active_actions.pop(event.action, None)
        LOGGER.info("action=%s state=up seq=%s", event.action, event.seq)
        return True

    def _apply_down(self, mapping: MidiMapping) -> None:
        if isinstance(mapping, NoteMapping):
            self._midi_out.note_on(mapping.channel, mapping.note, mapping.velocity)
            return
        if isinstance(mapping, ControlChangeMapping):
            self._midi_out.control_change(mapping.channel, mapping.cc, mapping.on_value)
            return
        if isinstance(mapping, MacroCCMapping):
            raise TypeError("macro mappings must be handled via _handle_macro_event")
        if isinstance(mapping, RelativeCCMapping):
            raise TypeError("relative CC mappings must be handled via _handle_relative_cc_event")
        if isinstance(mapping, StagedNoteMacroMapping):
            raise TypeError(
                "staged note macro mappings must be handled via _handle_staged_note_macro_event"
            )
        raise TypeError(f"unsupported mapping type: {type(mapping)!r}")

    def _release_mapping(self, action: str, mapping: MidiMapping) -> None:
        if isinstance(mapping, NoteMapping):
            self._midi_out.note_off(mapping.channel, mapping.note, 0)
            LOGGER.info("released note mapping for %s", action)
            return
        if isinstance(mapping, ControlChangeMapping):
            self._midi_out.control_change(mapping.channel, mapping.cc, mapping.off_value)
            LOGGER.info("released CC mapping for %s", action)
            return
        if isinstance(mapping, MacroCCMapping):
            return
        if isinstance(mapping, RelativeCCMapping):
            return
        if isinstance(mapping, StagedNoteMacroMapping):
            return
        raise TypeError(f"unsupported mapping type: {type(mapping)!r}")

    def _handle_macro_event(
        self, event: ActionEvent, mapping: MacroCCMapping, timestamp: float
    ) -> bool:
        if event.state != "down":
            return True

        key = (mapping.channel, mapping.cc)
        self._active_macro_fades.pop(key, None)

        current_value = self._macro_values.get(key, self._macro_settings.min_value)
        target_value = self._toggle_target(current_value)

        if mapping.gesture == "click":
            self._send_macro_value(mapping.channel, mapping.cc, target_value)
            return True

        if key not in self._macro_values:
            self._send_macro_value(mapping.channel, mapping.cc, current_value)

        self._active_macro_fades[key] = ActiveMacroFade(
            channel=mapping.channel,
            cc=mapping.cc,
            start_value=current_value,
            target_value=target_value,
            start_time=timestamp,
            duration_seconds=self._macro_settings.fade_duration_seconds,
        )
        self.advance_fades(now=timestamp)
        return True

    def _handle_relative_cc_event(
        self,
        event: ActionEvent,
        mapping: RelativeCCMapping,
        timestamp: float,
    ) -> bool:
        if event.state == "up":
            self._active_relative_ccs.pop(event.action, None)
            return True

        self._cancel_relative_ccs_for_target(mapping.channel, mapping.cc)
        repeat_interval_seconds = mapping.repeat_interval_ms / 1000.0
        self._midi_out.control_change(mapping.channel, mapping.cc, mapping.step_value)
        self._active_relative_ccs[event.action] = ActiveRelativeCC(
            action=event.action,
            channel=mapping.channel,
            cc=mapping.cc,
            step_value=mapping.step_value,
            repeat_interval_seconds=repeat_interval_seconds,
            next_send_time=timestamp + repeat_interval_seconds,
        )
        return True

    def _cancel_relative_ccs_for_target(self, channel: int, cc: int) -> None:
        for action, active in list(self._active_relative_ccs.items()):
            if active.channel == channel and active.cc == cc:
                self._active_relative_ccs.pop(action, None)

    def _handle_staged_note_macro_event(
        self,
        event: ActionEvent,
        mapping: StagedNoteMacroMapping,
        timestamp: float,
    ) -> bool:
        if event.state != "down":
            return True

        existing = self._active_staged_note_macros.pop(event.action, None)
        if existing is not None:
            self._midi_out.note_off(existing.modifier_channel, existing.note, 0)

        self._midi_out.note_on(mapping.modifier_channel, mapping.note, mapping.velocity)
        self._active_staged_note_macros[event.action] = ActiveStagedNoteMacro(
            action=event.action,
            modifier_channel=mapping.modifier_channel,
            trigger_channel=mapping.trigger_channel,
            note=mapping.note,
            velocity=mapping.velocity,
            trigger_time=timestamp + (self._macro_settings.macro_delay_ms / 1000.0),
            off_time=timestamp + (self._macro_settings.modifier_hold_ms / 1000.0),
            refresh_actions=frozenset(mapping.refresh_actions),
        )
        return True

    def _refresh_staged_note_macros(self, action: str, timestamp: float) -> None:
        if not self._active_staged_note_macros:
            return

        refreshed = False
        extension = self._macro_settings.modifier_hold_ms / 1000.0
        for active in self._active_staged_note_macros.values():
            if action not in active.refresh_actions:
                continue
            active.off_time = timestamp + extension
            refreshed = True

        if refreshed:
            LOGGER.debug(
                "refreshed staged modifier hold from action=%s until=%.3f",
                action,
                timestamp + extension,
            )

    def _update_layer_state_from_action(self, event: ActionEvent, timestamp: float) -> None:
        if event.state != "down":
            return
        self._handle_layer_toggle_hint(event.action, timestamp)
        self._handle_layer_ground_truth(event.action, timestamp)

    def _handle_layer_toggle_hint(self, action: str, timestamp: float) -> None:
        if action == "START":
            self._toggle_known_layer_state(self._abxy_layer_publisher, timestamp)
        elif action == "SELECT":
            self._toggle_known_layer_state(self._bumper_layer_publisher, timestamp)

    def _handle_layer_ground_truth(self, action: str, timestamp: float) -> None:
        if action in ABXY_LAYER_1_ACTIONS:
            self._set_layer_state(self._abxy_layer_publisher, LAYER_1, timestamp, action)
        elif action in ABXY_LAYER_2_ACTIONS:
            self._set_layer_state(self._abxy_layer_publisher, LAYER_2, timestamp, action)

        if action in BUMPER_LAYER_1_ACTIONS:
            self._set_layer_state(self._bumper_layer_publisher, LAYER_1, timestamp, action)
        elif action in BUMPER_LAYER_2_ACTIONS:
            self._set_layer_state(self._bumper_layer_publisher, LAYER_2, timestamp, action)

    def _toggle_known_layer_state(
        self,
        publisher: LayerStatePublisher | None,
        timestamp: float,
    ) -> None:
        if publisher is None or publisher.state == LAYER_UNKNOWN:
            return
        next_state = LAYER_2 if publisher.state == LAYER_1 else LAYER_1
        self._set_layer_state(publisher, next_state, timestamp, "toggle")

    def _set_layer_state(
        self,
        publisher: LayerStatePublisher | None,
        state: str,
        timestamp: float,
        source: str,
    ) -> None:
        if publisher is None:
            return
        if publisher.state not in {LAYER_UNKNOWN, state}:
            LOGGER.info(
                "layer state resync for note=%s from=%s to=%s via=%s",
                publisher.note,
                publisher.state,
                state,
                source,
            )
        publisher.state = state
        if publisher.last_published_state == state:
            return
        self._publish_layer_state(publisher, timestamp)

    def _publish_layer_state(self, publisher: LayerStatePublisher, timestamp: float) -> None:
        if publisher.state == LAYER_2:
            self._midi_out.note_off(publisher.layer_1_channel, publisher.note, 0)
            self._midi_out.note_on(publisher.layer_2_channel, publisher.note, 127)
        else:
            self._midi_out.note_on(publisher.layer_1_channel, publisher.note, 127)
            self._midi_out.note_off(publisher.layer_2_channel, publisher.note, 0)
        publisher.last_published_state = publisher.state
        publisher.last_publish_time = timestamp

    def _has_known_layer_state(self) -> bool:
        return any(
            publisher is not None and publisher.state != LAYER_UNKNOWN
            for publisher in (self._abxy_layer_publisher, self._bumper_layer_publisher)
        )

    def _build_layer_publisher(self, action: str) -> LayerStatePublisher | None:
        mapping = self._mappings.get(action)
        if not isinstance(mapping, NoteMapping):
            return None
        return LayerStatePublisher(
            note=mapping.note,
            raw_channel=mapping.channel,
            layer_1_channel=0,
            layer_2_channel=1,
        )

    def _toggle_target(self, current_value: int) -> int:
        midpoint = (self._macro_settings.min_value + self._macro_settings.max_value) / 2
        if current_value > midpoint:
            return self._macro_settings.min_value
        return self._macro_settings.max_value

    def _fade_value_at(self, fade: ActiveMacroFade, timestamp: float) -> int:
        elapsed = max(0.0, timestamp - fade.start_time)
        progress = min(1.0, elapsed / fade.duration_seconds)
        return round(
            fade.start_value + (fade.target_value - fade.start_value) * progress
        )

    def _feedback_matches_active_fade(
        self,
        value: int,
        *,
        expected_value: int,
        current_value: int | None,
    ) -> bool:
        tolerance = self._macro_settings.feedback_match_tolerance
        if abs(value - expected_value) <= tolerance:
            return True
        if current_value is not None and abs(value - current_value) <= tolerance:
            return True
        return False

    def _send_macro_value(self, channel: int, cc: int, value: int) -> None:
        self._midi_out.control_change(channel, cc, value)
        self._macro_values[(channel, cc)] = value


def serve_forever(
    listen_host: str,
    listen_port: int,
    receiver: ActionReceiver,
    *,
    midi_in: MidiIn | None = None,
    poll_interval: float = 0.25,
) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((listen_host, listen_port))

    LOGGER.info("listening on udp://%s:%s", listen_host, listen_port)
    if midi_in is not None:
        LOGGER.info(
            "listening for MIDI feedback: name=%s index=%s",
            midi_in.port_name,
            midi_in.port_index if midi_in.port_index is not None else "n/a",
        )
    try:
        while True:
            _drain_midi_feedback(receiver, midi_in)
            try:
                fade_poll = receiver.fade_poll_interval_seconds
                timeout = poll_interval if fade_poll is None else min(poll_interval, fade_poll)
                sock.settimeout(timeout)
                payload, addr = sock.recvfrom(4096)
            except socket.timeout:
                _drain_midi_feedback(receiver, midi_in)
                receiver.advance_fades()
                receiver.check_timeouts()
                continue
            receiver.handle_datagram(payload, addr)
            _drain_midi_feedback(receiver, midi_in)
            receiver.advance_fades()
            receiver.check_timeouts()
    except KeyboardInterrupt:
        LOGGER.info("shutdown requested")
    finally:
        receiver.release_all()
        sock.close()
        if midi_in is not None:
            midi_in.close()


def _drain_midi_feedback(receiver: ActionReceiver, midi_in: MidiIn | None) -> None:
    if midi_in is None:
        return
    for message in midi_in.poll_control_changes():
        _handle_feedback_message(receiver, message)


def _handle_feedback_message(receiver: ActionReceiver, message: MidiControlChange) -> None:
    try:
        receiver.handle_midi_feedback(
            message.channel,
            message.control,
            message.value,
        )
    except Exception:
        LOGGER.exception(
            "failed to process MIDI feedback channel=%s cc=%s value=%s",
            message.channel,
            message.control,
            message.value,
        )
