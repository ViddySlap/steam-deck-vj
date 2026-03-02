from __future__ import annotations

import unittest

from windows.config import NoteMapping
from windows.receiver import ActionReceiver
from windows.midi import MidiError


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
