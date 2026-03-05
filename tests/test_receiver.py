from __future__ import annotations

import unittest

from windows.config import (
    ControlChangeMapping,
    MacroCCMapping,
    MacroSettings,
    NoteMapping,
    RelativeCCMapping,
    StagedNoteMacroMapping,
)
from windows.receiver import ActionReceiver
from windows.midi import MidiControlChange, MidiError
from protocol.messages import encode_heartbeat_event


class FakeMidiOut:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int, int]] = []

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        self.calls.append(("note_on", channel, note, velocity))

    def note_off(self, channel: int, note: int, velocity: int = 0) -> None:
        self.calls.append(("note_off", channel, note, velocity))

    def control_change(self, channel: int, control: int, value: int) -> None:
        self.calls.append(("cc", channel, control, value))

    def panic(self) -> None:
        self.calls.append(("panic", -1, -1, -1))

    def close(self) -> None:
        return None


class FailingMidiOut(FakeMidiOut):
    def __init__(
        self,
        *,
        fail_note_on: bool = False,
        fail_note_off: bool = False,
        fail_panic: bool = False,
    ) -> None:
        super().__init__()
        self.fail_note_on = fail_note_on
        self.fail_note_off = fail_note_off
        self.fail_panic = fail_panic

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        if self.fail_note_on:
            raise MidiError("note_on failed")
        super().note_on(channel, note, velocity)

    def note_off(self, channel: int, note: int, velocity: int = 0) -> None:
        if self.fail_note_off:
            raise MidiError("note_off failed")
        super().note_off(channel, note, velocity)

    def panic(self) -> None:
        if self.fail_panic:
            raise MidiError("panic failed")
        super().panic()


class ActionReceiverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.midi = FakeMidiOut()
        self.receiver = ActionReceiver(
            self.midi,
            {"BTN_A": NoteMapping(action="BTN_A", kind="note", channel=0, note=60)},
            timeout_seconds=1.0,
        )
        self.addr = ("10.10.10.2", 45123)

    def test_emits_note_on_and_off(self) -> None:
        self.receiver.handle_datagram(
            b'{"action":"BTN_A","state":"down","seq":1}', self.addr, now=0.0
        )
        self.receiver.handle_datagram(
            b'{"action":"BTN_A","state":"up","seq":2}', self.addr, now=0.1
        )
        self.assertEqual(
            self.midi.calls,
            [("note_on", 0, 60, 127), ("note_off", 0, 60, 0)],
        )

    def test_ignores_out_of_order_packets(self) -> None:
        self.receiver.handle_datagram(
            b'{"action":"BTN_A","state":"down","seq":5}', self.addr, now=0.0
        )
        self.receiver.handle_datagram(
            b'{"action":"BTN_A","state":"up","seq":4}', self.addr, now=0.1
        )
        self.assertEqual(self.midi.calls, [("note_on", 0, 60, 127)])

    def test_releases_active_state_on_timeout(self) -> None:
        self.receiver.handle_datagram(
            b'{"action":"BTN_A","state":"down","seq":1}', self.addr, now=0.0
        )
        timed_out = self.receiver.check_timeouts(now=1.5)
        self.assertTrue(timed_out)
        self.assertEqual(
            self.midi.calls,
            [("note_on", 0, 60, 127), ("note_off", 0, 60, 0), ("panic", -1, -1, -1)],
        )

    def test_heartbeat_prevents_timeout_during_hold(self) -> None:
        self.receiver.handle_datagram(
            b'{"action":"BTN_A","state":"down","seq":1}', self.addr, now=0.0
        )
        self.receiver.handle_datagram(
            encode_heartbeat_event(seq=2), self.addr, now=0.6
        )
        self.receiver.handle_datagram(
            encode_heartbeat_event(seq=3), self.addr, now=1.2
        )

        timed_out = self.receiver.check_timeouts(now=1.8)

        self.assertFalse(timed_out)
        self.assertEqual(self.midi.calls, [("note_on", 0, 60, 127)])

    def test_survives_midi_send_failure_during_down_event(self) -> None:
        midi = FailingMidiOut(fail_note_on=True)
        receiver = ActionReceiver(
            midi,
            {"BTN_A": NoteMapping(action="BTN_A", kind="note", channel=0, note=60)},
            timeout_seconds=1.0,
        )

        handled = receiver.handle_datagram(
            b'{"action":"BTN_A","state":"down","seq":1}', self.addr, now=0.0
        )

        self.assertFalse(handled)
        self.assertEqual(midi.calls, [])
        self.assertEqual(receiver._active_actions, {})

    def test_survives_midi_failure_during_timeout_release(self) -> None:
        midi = FailingMidiOut(fail_note_off=True, fail_panic=True)
        receiver = ActionReceiver(
            midi,
            {"BTN_A": NoteMapping(action="BTN_A", kind="note", channel=0, note=60)},
            timeout_seconds=1.0,
        )

        receiver.handle_datagram(
            b'{"action":"BTN_A","state":"down","seq":1}', self.addr, now=0.0
        )
        timed_out = receiver.check_timeouts(now=1.5)

        self.assertTrue(timed_out)
        self.assertEqual(midi.calls, [("note_on", 0, 60, 127)])
        self.assertEqual(receiver._active_actions, {})

    def test_drops_duplicate_event_inside_dedupe_window(self) -> None:
        self.receiver.handle_datagram(
            b'{"action":"BTN_A","state":"down","seq":1}', self.addr, now=0.0
        )

        handled = self.receiver.handle_datagram(
            b'{"action":"BTN_A","state":"down","seq":2}', self.addr, now=0.01
        )

        self.assertFalse(handled)
        self.assertEqual(self.midi.calls, [("note_on", 0, 60, 127)])

    def test_loop_guard_releases_active_state_when_rate_limit_trips(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {"BTN_A": NoteMapping(action="BTN_A", kind="note", channel=0, note=60)},
            timeout_seconds=1.0,
            dedupe_window_seconds=0.0,
            rate_limit_window_seconds=1.0,
            rate_limit_max_events=3,
            rate_limit_cooldown_seconds=0.5,
        )

        receiver.handle_datagram(
            b'{"action":"BTN_A","state":"down","seq":1}', self.addr, now=0.0
        )
        receiver.handle_datagram(
            b'{"action":"BTN_A","state":"up","seq":2}', self.addr, now=0.1
        )
        receiver.handle_datagram(
            b'{"action":"BTN_A","state":"down","seq":3}', self.addr, now=0.2
        )

        handled = receiver.handle_datagram(
            b'{"action":"BTN_A","state":"up","seq":4}', self.addr, now=0.3
        )

        self.assertFalse(handled)
        self.assertEqual(
            self.midi.calls,
            [
                ("note_on", 0, 60, 127),
                ("note_off", 0, 60, 0),
                ("note_on", 0, 60, 127),
                ("note_off", 0, 60, 0),
                ("panic", -1, -1, -1),
            ],
        )

        handled_during_cooldown = receiver.handle_datagram(
            b'{"action":"BTN_A","state":"down","seq":5}', self.addr, now=0.4
        )

        self.assertFalse(handled_during_cooldown)
        self.assertEqual(len(self.midi.calls), 5)

    def test_dpad_down_click_emits_independent_note_trigger(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "DPAD_DOWN": NoteMapping(
                    action="DPAD_DOWN",
                    kind="note",
                    channel=0,
                    note=98,
                )
            },
            timeout_seconds=1.0,
        )

        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN","state":"down","seq":1}', self.addr, now=0.0
        )
        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN","state":"up","seq":2}', self.addr, now=0.1
        )
        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN","state":"down","seq":3}', self.addr, now=0.2
        )

        self.assertEqual(
            self.midi.calls,
            [("note_on", 0, 98, 127), ("note_off", 0, 98, 0), ("note_on", 0, 98, 127)],
        )

    def test_layer_switch_retriggers_held_control_for_base_and_layer_2_actions(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "SELECT": ControlChangeMapping(
                    action="SELECT",
                    kind="cc",
                    channel=2,
                    cc=79,
                    on_value=127,
                    off_value=0,
                ),
                "R2_FULL": NoteMapping(
                    action="R2_FULL",
                    kind="note",
                    channel=0,
                    note=70,
                ),
                "R2_FULL_LAYER_2": NoteMapping(
                    action="R2_FULL_LAYER_2",
                    kind="note",
                    channel=0,
                    note=71,
                ),
            },
            timeout_seconds=1.0,
        )

        receiver.handle_datagram(
            b'{"action":"R2_FULL","state":"down","seq":1}', self.addr, now=0.0
        )
        receiver.handle_datagram(
            b'{"action":"SELECT","state":"down","seq":2}', self.addr, now=0.1
        )
        receiver.handle_datagram(
            b'{"action":"R2_FULL_LAYER_2","state":"down","seq":3}', self.addr, now=0.2
        )
        receiver.handle_datagram(
            b'{"action":"R2_FULL_LAYER_2","state":"up","seq":4}', self.addr, now=0.3
        )

        self.assertEqual(
            self.midi.calls,
            [
                ("cc", 0, 79, 127),
                ("cc", 1, 79, 0),
                ("note_on", 0, 70, 127),
                ("note_off", 0, 70, 0),
                ("cc", 0, 79, 0),
                ("cc", 1, 79, 127),
                ("cc", 2, 79, 127),
                ("note_on", 0, 71, 127),
                ("note_off", 0, 71, 0),
            ],
        )

    def test_layer_2_variant_without_base_down_does_not_force_base_release(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "R2_FULL": NoteMapping(
                    action="R2_FULL",
                    kind="note",
                    channel=0,
                    note=70,
                ),
                "R2_FULL_LAYER_2": NoteMapping(
                    action="R2_FULL_LAYER_2",
                    kind="note",
                    channel=0,
                    note=71,
                ),
            },
            timeout_seconds=1.0,
        )

        receiver.handle_datagram(
            b'{"action":"R2_FULL_LAYER_2","state":"down","seq":1}', self.addr, now=0.0
        )
        receiver.handle_datagram(
            b'{"action":"R2_FULL_LAYER_2","state":"up","seq":2}', self.addr, now=0.1
        )

        self.assertEqual(
            self.midi.calls,
            [("note_on", 0, 71, 127), ("note_off", 0, 71, 0)],
        )

    def test_first_layer_toggle_releases_held_actions_even_when_layer_state_is_unknown(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "SELECT": ControlChangeMapping(
                    action="SELECT",
                    kind="cc",
                    channel=2,
                    cc=79,
                    on_value=127,
                    off_value=0,
                ),
                "R4": NoteMapping(
                    action="R4",
                    kind="note",
                    channel=0,
                    note=76,
                ),
                "L4": NoteMapping(
                    action="L4",
                    kind="note",
                    channel=0,
                    note=74,
                ),
                "R2_FULL_LAYER_2": NoteMapping(
                    action="R2_FULL_LAYER_2",
                    kind="note",
                    channel=0,
                    note=71,
                ),
                "R2_SOFT_LAYER_2": NoteMapping(
                    action="R2_SOFT_LAYER_2",
                    kind="note",
                    channel=0,
                    note=69,
                ),
            },
            timeout_seconds=1.0,
        )

        receiver.handle_datagram(
            b'{"action":"R4","state":"down","seq":1}', self.addr, now=0.0
        )
        receiver.handle_datagram(
            b'{"action":"L4","state":"down","seq":2}', self.addr, now=0.1
        )
        receiver.handle_datagram(
            b'{"action":"SELECT","state":"down","seq":3}', self.addr, now=0.2
        )
        receiver.handle_datagram(
            b'{"action":"R2_FULL_LAYER_2","state":"down","seq":4}', self.addr, now=0.3
        )
        receiver.handle_datagram(
            b'{"action":"R2_SOFT_LAYER_2","state":"down","seq":5}', self.addr, now=0.4
        )

        self.assertEqual(
            self.midi.calls,
            [
                ("note_on", 0, 76, 127),
                ("note_on", 0, 74, 127),
                ("note_off", 0, 76, 0),
                ("note_off", 0, 74, 0),
                ("cc", 2, 79, 127),
                ("cc", 0, 79, 0),
                ("cc", 1, 79, 127),
                ("note_on", 0, 71, 127),
                ("note_on", 0, 69, 127),
            ],
        )

    def test_soft_and_full_trigger_actions_both_emit_midi(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "R2_SOFT": NoteMapping(
                    action="R2_SOFT",
                    kind="note",
                    channel=0,
                    note=68,
                ),
                "R2_FULL": NoteMapping(
                    action="R2_FULL",
                    kind="note",
                    channel=0,
                    note=70,
                ),
                "R2_SOFT_LAYER_2": NoteMapping(
                    action="R2_SOFT_LAYER_2",
                    kind="note",
                    channel=0,
                    note=69,
                ),
                "R2_FULL_LAYER_2": NoteMapping(
                    action="R2_FULL_LAYER_2",
                    kind="note",
                    channel=0,
                    note=71,
                ),
            },
            timeout_seconds=1.0,
        )

        receiver.handle_datagram(
            b'{"action":"R2_SOFT","state":"down","seq":1}', self.addr, now=0.0
        )
        receiver.handle_datagram(
            b'{"action":"R2_SOFT","state":"up","seq":2}', self.addr, now=0.1
        )
        receiver.handle_datagram(
            b'{"action":"R2_FULL","state":"down","seq":3}', self.addr, now=0.2
        )
        receiver.handle_datagram(
            b'{"action":"R2_FULL","state":"up","seq":4}', self.addr, now=0.3
        )
        receiver.handle_datagram(
            b'{"action":"R2_SOFT_LAYER_2","state":"down","seq":5}', self.addr, now=0.4
        )
        receiver.handle_datagram(
            b'{"action":"R2_SOFT_LAYER_2","state":"up","seq":6}', self.addr, now=0.5
        )
        receiver.handle_datagram(
            b'{"action":"R2_FULL_LAYER_2","state":"down","seq":7}', self.addr, now=0.6
        )
        receiver.handle_datagram(
            b'{"action":"R2_FULL_LAYER_2","state":"up","seq":8}', self.addr, now=0.7
        )

        self.assertEqual(
            self.midi.calls,
            [
                ("note_on", 0, 68, 127),
                ("note_off", 0, 68, 0),
                ("note_on", 0, 70, 127),
                ("note_off", 0, 70, 0),
                ("note_on", 0, 69, 127),
                ("note_off", 0, 69, 0),
                ("note_on", 0, 71, 127),
                ("note_off", 0, 71, 0),
            ],
        )

    def test_macro_long_press_fades_to_target_and_ignores_release(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "DPAD_DOWN_LONG_PRESS": MacroCCMapping(
                    action="DPAD_DOWN_LONG_PRESS",
                    kind="macro_cc",
                    channel=0,
                    cc=20,
                    gesture="long_press",
                )
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(fade_duration_seconds=2.0, update_hz=10),
        )

        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN_LONG_PRESS","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.advance_fades(now=1.0)
        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN_LONG_PRESS","state":"up","seq":2}',
            self.addr,
            now=1.1,
        )
        receiver.advance_fades(now=2.0)

        self.assertEqual(
            self.midi.calls,
            [("cc", 0, 20, 0), ("cc", 0, 20, 64), ("cc", 0, 20, 70), ("cc", 0, 20, 127)],
        )

    def test_dpad_down_click_does_not_interrupt_long_press_macro_fade(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "DPAD_DOWN": NoteMapping(
                    action="DPAD_DOWN",
                    kind="note",
                    channel=0,
                    note=98,
                ),
                "DPAD_DOWN_LONG_PRESS": MacroCCMapping(
                    action="DPAD_DOWN_LONG_PRESS",
                    kind="macro_cc",
                    channel=0,
                    cc=20,
                    gesture="long_press",
                ),
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(fade_duration_seconds=2.0, update_hz=10),
        )

        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN_LONG_PRESS","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.advance_fades(now=1.0)
        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN","state":"down","seq":2}', self.addr, now=1.1
        )
        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN","state":"up","seq":3}', self.addr, now=1.2
        )
        receiver.advance_fades(now=2.0)

        self.assertEqual(
            self.midi.calls,
            [
                ("cc", 0, 20, 0),
                ("cc", 0, 20, 64),
                ("cc", 0, 20, 70),
                ("note_on", 0, 98, 127),
                ("cc", 0, 20, 76),
                ("note_off", 0, 98, 0),
                ("cc", 0, 20, 127),
            ],
        )

    def test_macro_fades_continue_after_sender_timeout(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "DPAD_RIGHT_LONG_PRESS": MacroCCMapping(
                    action="DPAD_RIGHT_LONG_PRESS",
                    kind="macro_cc",
                    channel=0,
                    cc=21,
                    gesture="long_press",
                )
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(fade_duration_seconds=2.0, update_hz=10),
        )

        receiver.handle_datagram(
            b'{"action":"DPAD_RIGHT_LONG_PRESS","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        timed_out = receiver.check_timeouts(now=1.5)
        receiver.advance_fades(now=2.0)

        self.assertTrue(timed_out)
        self.assertEqual(
            self.midi.calls,
            [("cc", 0, 21, 0), ("cc", 0, 21, 95), ("cc", 0, 21, 127)],
        )

    def test_macro_fades_run_independently_per_layer(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "DPAD_DOWN_LONG_PRESS": MacroCCMapping(
                    action="DPAD_DOWN_LONG_PRESS",
                    kind="macro_cc",
                    channel=0,
                    cc=20,
                    gesture="long_press",
                ),
                "DPAD_RIGHT_LONG_PRESS": MacroCCMapping(
                    action="DPAD_RIGHT_LONG_PRESS",
                    kind="macro_cc",
                    channel=0,
                    cc=21,
                    gesture="long_press",
                ),
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(fade_duration_seconds=2.0, update_hz=10),
        )

        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN_LONG_PRESS","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.handle_datagram(
            b'{"action":"DPAD_RIGHT_LONG_PRESS","state":"down","seq":2}',
            self.addr,
            now=0.5,
        )
        receiver.advance_fades(now=1.5)
        receiver.advance_fades(now=2.5)

        self.assertEqual(
            self.midi.calls,
            [
                ("cc", 0, 20, 0),
                ("cc", 0, 20, 32),
                ("cc", 0, 21, 0),
                ("cc", 0, 20, 95),
                ("cc", 0, 21, 64),
                ("cc", 0, 20, 127),
                ("cc", 0, 21, 127),
            ],
        )

    def test_feedback_updates_cached_macro_value(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "DPAD_DOWN": MacroCCMapping(
                    action="DPAD_DOWN",
                    kind="macro_cc",
                    channel=0,
                    cc=20,
                    gesture="click",
                )
            },
            timeout_seconds=1.0,
        )

        handled = receiver.handle_midi_feedback(0, 20, 64, now=0.0)

        self.assertTrue(handled)
        self.assertEqual(receiver._macro_values[(0, 20)], 64)
        self.assertEqual(self.midi.calls, [])

    def test_feedback_ignores_untracked_cc(self) -> None:
        handled = self.receiver.handle_midi_feedback(0, 20, 64, now=0.0)

        self.assertFalse(handled)
        self.assertEqual(self.receiver._macro_values, {})

    def test_matching_feedback_is_ignored_while_fade_is_active(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "DPAD_DOWN_LONG_PRESS": MacroCCMapping(
                    action="DPAD_DOWN_LONG_PRESS",
                    kind="macro_cc",
                    channel=0,
                    cc=20,
                    gesture="long_press",
                )
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(fade_duration_seconds=2.0, update_hz=10),
        )

        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN_LONG_PRESS","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.advance_fades(now=1.0)

        handled = receiver.handle_midi_feedback(0, 20, 64, now=1.0)

        self.assertFalse(handled)
        self.assertIn((0, 20), receiver._active_macro_fades)
        self.assertEqual(receiver._macro_values[(0, 20)], 64)

    def test_nearby_feedback_is_ignored_while_fade_is_active(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "DPAD_DOWN_LONG_PRESS": MacroCCMapping(
                    action="DPAD_DOWN_LONG_PRESS",
                    kind="macro_cc",
                    channel=0,
                    cc=20,
                    gesture="long_press",
                )
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(fade_duration_seconds=2.0, update_hz=10),
        )

        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN_LONG_PRESS","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.advance_fades(now=0.42)

        handled = receiver.handle_midi_feedback(0, 20, 28, now=0.44)

        self.assertFalse(handled)
        self.assertIn((0, 20), receiver._active_macro_fades)
        self.assertEqual(receiver._macro_values[(0, 20)], 27)

    def test_non_matching_feedback_cancels_active_fade_as_manual_override(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "DPAD_DOWN_LONG_PRESS": MacroCCMapping(
                    action="DPAD_DOWN_LONG_PRESS",
                    kind="macro_cc",
                    channel=0,
                    cc=20,
                    gesture="long_press",
                )
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(fade_duration_seconds=2.0, update_hz=10),
        )

        receiver.handle_datagram(
            b'{"action":"DPAD_DOWN_LONG_PRESS","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.advance_fades(now=1.0)

        handled = receiver.handle_midi_feedback(0, 20, 90, now=1.0)
        receiver.advance_fades(now=2.0)

        self.assertTrue(handled)
        self.assertNotIn((0, 20), receiver._active_macro_fades)
        self.assertEqual(receiver._macro_values[(0, 20)], 90)
        self.assertEqual(self.midi.calls, [("cc", 0, 20, 0), ("cc", 0, 20, 64)])

    def test_relative_cc_repeats_while_held_and_stops_on_release(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "R_PAD_RIGHT": RelativeCCMapping(
                    action="R_PAD_RIGHT",
                    kind="relative_cc",
                    channel=0,
                    cc=47,
                    step_value=1,
                    repeat_interval_ms=40,
                )
            },
            timeout_seconds=1.0,
        )

        receiver.handle_datagram(
            b'{"action":"R_PAD_RIGHT","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.advance_relative_ccs(now=0.04)
        receiver.advance_relative_ccs(now=0.08)
        receiver.handle_datagram(
            b'{"action":"R_PAD_RIGHT","state":"up","seq":2}',
            self.addr,
            now=0.09,
        )
        receiver.advance_relative_ccs(now=0.12)

        self.assertEqual(
            self.midi.calls,
            [("cc", 0, 47, 1), ("cc", 0, 47, 1), ("cc", 0, 47, 1)],
        )

    def test_relative_cc_left_uses_reverse_step_value(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "R_PAD_LEFT": RelativeCCMapping(
                    action="R_PAD_LEFT",
                    kind="relative_cc",
                    channel=0,
                    cc=47,
                    step_value=127,
                    repeat_interval_ms=40,
                )
            },
            timeout_seconds=1.0,
        )

        receiver.handle_datagram(
            b'{"action":"R_PAD_LEFT","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.advance_relative_ccs(now=0.04)

        self.assertEqual(self.midi.calls, [("cc", 0, 47, 127), ("cc", 0, 47, 127)])

    def test_relative_cc_opposite_direction_cancels_existing_repeat(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "R_PAD_RIGHT": RelativeCCMapping(
                    action="R_PAD_RIGHT",
                    kind="relative_cc",
                    channel=0,
                    cc=47,
                    step_value=1,
                    repeat_interval_ms=40,
                ),
                "R_PAD_LEFT": RelativeCCMapping(
                    action="R_PAD_LEFT",
                    kind="relative_cc",
                    channel=0,
                    cc=47,
                    step_value=127,
                    repeat_interval_ms=40,
                ),
            },
            timeout_seconds=1.0,
        )

        receiver.handle_datagram(
            b'{"action":"R_PAD_RIGHT","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.advance_relative_ccs(now=0.04)
        receiver.handle_datagram(
            b'{"action":"R_PAD_LEFT","state":"down","seq":2}',
            self.addr,
            now=0.05,
        )
        receiver.advance_relative_ccs(now=0.09)

        self.assertEqual(
            self.midi.calls,
            [("cc", 0, 47, 1), ("cc", 0, 47, 1), ("cc", 0, 47, 127), ("cc", 0, 47, 127)],
        )

    def test_staged_note_macro_sends_modifier_then_delayed_trigger_then_release(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "L_PAD_LEFT_LONG_PRESS": StagedNoteMacroMapping(
                    action="L_PAD_LEFT_LONG_PRESS",
                    kind="staged_note_macro",
                    note=86,
                    modifier_channel=0,
                    trigger_channel=1,
                    velocity=127,
                    refresh_actions=("L_PAD_LEFT", "L_PAD_RIGHT"),
                )
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(macro_delay_ms=80, modifier_hold_ms=2000),
        )

        receiver.handle_datagram(
            b'{"action":"L_PAD_LEFT_LONG_PRESS","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.handle_datagram(
            b'{"action":"L_PAD_LEFT_LONG_PRESS","state":"up","seq":2}',
            self.addr,
            now=0.1,
        )
        receiver.advance_staged_note_macros(now=0.07)
        receiver.advance_staged_note_macros(now=0.08)
        receiver.advance_staged_note_macros(now=1.9)
        receiver.advance_staged_note_macros(now=2.0)

        self.assertEqual(
            self.midi.calls,
            [("note_on", 0, 86, 127), ("note_on", 1, 86, 127), ("note_off", 0, 86, 0)],
        )

    def test_staged_note_macro_retrigger_restarts_sequence_and_timer(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "L_PAD_RIGHT_LONG_PRESS": StagedNoteMacroMapping(
                    action="L_PAD_RIGHT_LONG_PRESS",
                    kind="staged_note_macro",
                    note=87,
                    modifier_channel=0,
                    trigger_channel=1,
                    velocity=127,
                    refresh_actions=("L_PAD_LEFT", "L_PAD_RIGHT"),
                )
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(macro_delay_ms=80, modifier_hold_ms=2000),
        )

        receiver.handle_datagram(
            b'{"action":"L_PAD_RIGHT_LONG_PRESS","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.advance_staged_note_macros(now=0.08)
        receiver.handle_datagram(
            b'{"action":"L_PAD_RIGHT_LONG_PRESS","state":"down","seq":2}',
            self.addr,
            now=1.0,
        )
        receiver.advance_staged_note_macros(now=1.08)
        receiver.advance_staged_note_macros(now=2.5)
        receiver.advance_staged_note_macros(now=3.0)

        self.assertEqual(
            self.midi.calls,
            [
                ("note_on", 0, 87, 127),
                ("note_on", 1, 87, 127),
                ("note_off", 0, 87, 0),
                ("note_on", 0, 87, 127),
                ("note_on", 1, 87, 127),
                ("note_off", 0, 87, 0),
            ],
        )

    def test_staged_note_macro_refreshes_hold_on_left_or_right_click(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "L_PAD_LEFT": NoteMapping(
                    action="L_PAD_LEFT",
                    kind="note",
                    channel=0,
                    note=82,
                ),
                "L_PAD_RIGHT": NoteMapping(
                    action="L_PAD_RIGHT",
                    kind="note",
                    channel=0,
                    note=83,
                ),
                "L_PAD_LEFT_LONG_PRESS": StagedNoteMacroMapping(
                    action="L_PAD_LEFT_LONG_PRESS",
                    kind="staged_note_macro",
                    note=86,
                    modifier_channel=0,
                    trigger_channel=1,
                    velocity=127,
                    refresh_actions=("L_PAD_LEFT", "L_PAD_RIGHT"),
                ),
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(macro_delay_ms=80, modifier_hold_ms=2000),
        )

        receiver.handle_datagram(
            b'{"action":"L_PAD_LEFT_LONG_PRESS","state":"down","seq":1}',
            self.addr,
            now=0.0,
        )
        receiver.advance_staged_note_macros(now=0.08)
        receiver.handle_datagram(
            b'{"action":"L_PAD_RIGHT","state":"down","seq":2}',
            self.addr,
            now=1.0,
        )
        receiver.handle_datagram(
            b'{"action":"L_PAD_RIGHT","state":"up","seq":3}',
            self.addr,
            now=1.1,
        )
        receiver.handle_datagram(
            b'{"action":"L_PAD_LEFT","state":"down","seq":4}',
            self.addr,
            now=2.0,
        )
        receiver.handle_datagram(
            b'{"action":"L_PAD_LEFT","state":"up","seq":5}',
            self.addr,
            now=2.1,
        )
        receiver.advance_staged_note_macros(now=3.9)
        receiver.advance_staged_note_macros(now=4.1)

        self.assertEqual(
            self.midi.calls,
            [
                ("note_on", 0, 86, 127),
                ("note_on", 1, 86, 127),
                ("note_on", 0, 83, 127),
                ("note_off", 0, 83, 0),
                ("note_on", 0, 82, 127),
                ("note_off", 0, 82, 0),
                ("note_off", 0, 86, 0),
            ],
        )

    def test_layer_state_starts_unknown_and_uses_ground_truth_then_toggle(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "START": ControlChangeMapping(
                    action="START",
                    kind="cc",
                    channel=2,
                    cc=78,
                    on_value=127,
                    off_value=0,
                ),
                "BTN_A": NoteMapping(action="BTN_A", kind="note", channel=0, note=36),
                "BTN_A_LAYER_2": NoteMapping(
                    action="BTN_A_LAYER_2",
                    kind="note",
                    channel=0,
                    note=37,
                ),
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(),
        )

        receiver.handle_datagram(
            b'{"action":"START","state":"down","seq":1}', self.addr, now=0.0
        )
        receiver.handle_datagram(
            b'{"action":"BTN_A_LAYER_2","state":"down","seq":2}', self.addr, now=0.1
        )
        receiver.handle_datagram(
            b'{"action":"START","state":"down","seq":3}', self.addr, now=0.2
        )
        receiver.handle_datagram(
            b'{"action":"BTN_A_LAYER_2","state":"down","seq":4}', self.addr, now=0.3
        )

        self.assertEqual(
            self.midi.calls,
            [
                ("cc", 2, 78, 127),
                ("cc", 0, 78, 0),
                ("cc", 1, 78, 127),
                ("note_on", 0, 37, 127),
                ("note_off", 0, 37, 0),
                ("cc", 0, 78, 127),
                ("cc", 1, 78, 0),
                ("cc", 2, 78, 127),
                ("cc", 0, 78, 0),
                ("cc", 1, 78, 127),
                ("note_on", 0, 37, 127),
            ],
        )

    def test_bumper_layer_state_publishes_on_ground_truth(self) -> None:
        receiver = ActionReceiver(
            self.midi,
            {
                "SELECT": ControlChangeMapping(
                    action="SELECT",
                    kind="cc",
                    channel=2,
                    cc=79,
                    on_value=127,
                    off_value=0,
                ),
                "L1_LAYER_2": NoteMapping(
                    action="L1_LAYER_2",
                    kind="note",
                    channel=0,
                    note=61,
                ),
            },
            timeout_seconds=1.0,
            macro_settings=MacroSettings(),
        )

        receiver.handle_datagram(
            b'{"action":"L1_LAYER_2","state":"down","seq":1}', self.addr, now=0.0
        )

        self.assertEqual(
            self.midi.calls,
            [
                ("cc", 0, 79, 0),
                ("cc", 1, 79, 127),
                ("note_on", 0, 61, 127),
            ],
        )


class ServeForeverFeedbackTests(unittest.TestCase):
    def test_drains_feedback_messages(self) -> None:
        midi = FakeMidiOut()
        receiver = ActionReceiver(
            midi,
            {
                "DPAD_DOWN": MacroCCMapping(
                    action="DPAD_DOWN",
                    kind="macro_cc",
                    channel=0,
                    cc=20,
                    gesture="click",
                )
            },
        )

        class FakeMidiIn:
            def poll_control_changes(self) -> list[MidiControlChange]:
                if hasattr(self, "_used"):
                    return []
                self._used = True
                return [MidiControlChange(channel=0, control=20, value=99)]

            def close(self) -> None:
                return None

            @property
            def port_name(self) -> str:
                return "DECK_OUT"

            @property
            def port_index(self) -> int | None:
                return 0

        from windows.receiver import _drain_midi_feedback

        _drain_midi_feedback(receiver, FakeMidiIn())

        self.assertEqual(receiver._macro_values[(0, 20)], 99)
