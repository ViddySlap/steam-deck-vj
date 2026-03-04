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
)
from windows.midi import MidiControlChange, MidiError, MidiIn, MidiOut


LOGGER = logging.getLogger(__name__)


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
        self._tracked_macro_keys = {
            (mapping.channel, mapping.cc)
            for mapping in mappings.values()
            if isinstance(mapping, MacroCCMapping)
        }

    @property
    def fade_poll_interval_seconds(self) -> float | None:
        if not self._active_macro_fades:
            return None
        return self._macro_settings.step_interval_seconds

    def handle_datagram(
        self, payload: bytes, addr: tuple[str, int], now: float | None = None
    ) -> bool:
        timestamp = self._clock() if now is None else now
        self.advance_fades(now=timestamp)

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
        try:
            return self._dispatch_event(event, timestamp)
        except MidiError as exc:
            LOGGER.error("MIDI output error while handling %s: %s", event.action, exc)
            self._active_actions.pop(event.action, None)
            return False

    def check_timeouts(self, now: float | None = None) -> bool:
        timestamp = self._clock() if now is None else now
        self.advance_fades(now=timestamp)
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
            if value == expected_value or value == current_value:
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
