from __future__ import annotations

import ctypes
import json
import tempfile
import unittest
from pathlib import Path

from deck.xinput_send import (
    Xi2KeyEvent,
    flush_block,
    load_bindings,
    next_select_timeout,
    set_mask,
    should_emit_event,
)
from protocol.messages import encode_action_event, parse_action_event


class LoadBindingsTests(unittest.TestCase):
    def test_loads_profile_and_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bindings.json"
            path.write_text(
                json.dumps({"profile_name": "default", "bindings": {"14": "BTN_A"}}),
                encoding="utf-8",
            )
            profile_name, bindings = load_bindings(str(path))

        self.assertEqual(profile_name, "default")
        self.assertEqual(bindings, {"14": "BTN_A"})


class ShouldEmitEventTests(unittest.TestCase):
    def test_emits_first_press_and_release(self) -> None:
        held_keys: set[str] = set()

        self.assertTrue(
            should_emit_event(
                Xi2KeyEvent(keycode="67", state="down"), held_keys
            )
        )
        self.assertEqual(held_keys, {"67"})
        self.assertTrue(
            should_emit_event(
                Xi2KeyEvent(keycode="67", state="up"), held_keys
            )
        )
        self.assertEqual(held_keys, set())

    def test_suppresses_duplicate_press_while_held(self) -> None:
        held_keys = {"67"}

        self.assertFalse(
            should_emit_event(
                Xi2KeyEvent(keycode="67", state="down"), held_keys
            )
        )
        self.assertEqual(held_keys, {"67"})

    def test_suppresses_release_without_matching_hold(self) -> None:
        held_keys: set[str] = set()

        self.assertFalse(
            should_emit_event(
                Xi2KeyEvent(keycode="67", state="up"), held_keys
            )
        )
        self.assertEqual(held_keys, set())

    def test_tracks_multiple_held_keys_independently(self) -> None:
        held_keys: set[str] = set()

        self.assertTrue(
            should_emit_event(
                Xi2KeyEvent(keycode="67", state="down"), held_keys
            )
        )
        self.assertTrue(
            should_emit_event(
                Xi2KeyEvent(keycode="68", state="down"), held_keys
            )
        )
        self.assertEqual(held_keys, {"67", "68"})
        self.assertTrue(
            should_emit_event(
                Xi2KeyEvent(keycode="67", state="up"), held_keys
            )
        )
        self.assertEqual(held_keys, {"68"})


class FlushBlockTests(unittest.TestCase):
    def test_flushes_bound_press(self) -> None:
        parsed, action = flush_block(
            Xi2KeyEvent(keycode="67", state="down"),
            {"67": "BTN_A"},
            set(),
        )

        self.assertEqual(
            parsed, Xi2KeyEvent(keycode="67", state="down")
        )
        self.assertEqual(action, "BTN_A")

    def test_flushes_release_without_needing_trailing_blank_separator(self) -> None:
        held_keys = {"67"}
        parsed, action = flush_block(
            Xi2KeyEvent(keycode="67", state="up"),
            {"67": "BTN_A"},
            held_keys,
        )

        self.assertEqual(
            parsed, Xi2KeyEvent(keycode="67", state="up")
        )
        self.assertEqual(action, "BTN_A")
        self.assertEqual(held_keys, set())


class SetMaskTests(unittest.TestCase):
    def test_sets_bit_for_event_type(self) -> None:
        mask = (ctypes.c_ubyte * 2)()
        set_mask(mask, 13)
        self.assertEqual(mask[1], 0b00100000)


class NextSelectTimeoutTests(unittest.TestCase):
    def test_checks_immediately_when_internal_work_is_pending(self) -> None:
        self.assertEqual(
            next_select_timeout(
                held_keys={"67"},
                block=["pending"],
                next_heartbeat_at=10.0,
                now=9.9,
            ),
            0.0,
        )

    def test_uses_heartbeat_deadline_when_idle_and_holding(self) -> None:
        self.assertEqual(
            next_select_timeout(
                held_keys={"67"},
                block=[],
                next_heartbeat_at=10.0,
                now=9.25,
            ),
            0.75,
        )

    def test_blocks_indefinitely_when_no_keys_are_held(self) -> None:
        self.assertIsNone(
            next_select_timeout(
                held_keys=set(),
                block=[],
                next_heartbeat_at=10.0,
                now=9.25,
            )
        )


class SharedProtocolEncodingTests(unittest.TestCase):
    def test_encoded_event_round_trips(self) -> None:
        payload = encode_action_event(action="BTN_A", state="down", seq=1)
        event = parse_action_event(payload)
        self.assertEqual(event.action, "BTN_A")
        self.assertEqual(event.state, "down")
        self.assertEqual(event.seq, 1)
