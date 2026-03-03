from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deck.xinput_send import (
    Xi2KeyEvent,
    flush_block,
    load_bindings,
    parse_xi2_event_block,
    should_emit_event,
)
from protocol.messages import encode_action_event, parse_action_event


class ParseXi2EventBlockTests(unittest.TestCase):
    def test_parses_initial_key_press(self) -> None:
        self.assertEqual(
            parse_xi2_event_block(
                [
                    "EVENT type 2 (KeyPress)",
                    "    device: 5 (5)",
                    "    time: 3096762",
                    "    detail: 67",
                    "    flags: ",
                ]
            ),
            Xi2KeyEvent(keycode="67", state="down", is_repeat=False),
        )

    def test_parses_repeat_key_press(self) -> None:
        self.assertEqual(
            parse_xi2_event_block(
                [
                    "EVENT type 2 (KeyPress)",
                    "    device: 5 (5)",
                    "    time: 3101007",
                    "    detail: 67",
                    "    flags: repeat",
                ]
            ),
            Xi2KeyEvent(keycode="67", state="down", is_repeat=True),
        )

    def test_parses_key_release(self) -> None:
        self.assertEqual(
            parse_xi2_event_block(
                [
                    "EVENT type 3 (KeyRelease)",
                    "    device: 5 (5)",
                    "    time: 3101444",
                    "    detail: 67",
                    "    flags: ",
                ]
            ),
            Xi2KeyEvent(keycode="67", state="up", is_repeat=False),
        )

    def test_ignores_other_event_blocks(self) -> None:
        self.assertIsNone(
            parse_xi2_event_block(
                [
                    "EVENT type 14 (RawKeyRelease)",
                    "    device: 3 (5)",
                    "    time: 3101444",
                    "    detail: 67",
                ]
            )
        )


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
                Xi2KeyEvent(keycode="67", state="down", is_repeat=False), held_keys
            )
        )
        self.assertEqual(held_keys, {"67"})
        self.assertTrue(
            should_emit_event(
                Xi2KeyEvent(keycode="67", state="up", is_repeat=False), held_keys
            )
        )
        self.assertEqual(held_keys, set())

    def test_suppresses_repeat_while_held(self) -> None:
        held_keys = {"67"}

        self.assertFalse(
            should_emit_event(
                Xi2KeyEvent(keycode="67", state="down", is_repeat=True), held_keys
            )
        )
        self.assertEqual(held_keys, {"67"})

    def test_suppresses_release_without_matching_hold(self) -> None:
        held_keys: set[str] = set()

        self.assertFalse(
            should_emit_event(
                Xi2KeyEvent(keycode="67", state="up", is_repeat=False), held_keys
            )
        )
        self.assertEqual(held_keys, set())

    def test_tracks_multiple_held_keys_independently(self) -> None:
        held_keys: set[str] = set()

        self.assertTrue(
            should_emit_event(
                Xi2KeyEvent(keycode="67", state="down", is_repeat=False), held_keys
            )
        )
        self.assertTrue(
            should_emit_event(
                Xi2KeyEvent(keycode="68", state="down", is_repeat=False), held_keys
            )
        )
        self.assertEqual(held_keys, {"67", "68"})
        self.assertTrue(
            should_emit_event(
                Xi2KeyEvent(keycode="67", state="up", is_repeat=False), held_keys
            )
        )
        self.assertEqual(held_keys, {"68"})


class FlushBlockTests(unittest.TestCase):
    def test_flushes_bound_press(self) -> None:
        parsed, action = flush_block(
            [
                "EVENT type 2 (KeyPress)",
                "    device: 5 (5)",
                "    time: 3096762",
                "    detail: 67",
                "    flags: ",
            ],
            {"67": "BTN_A"},
            set(),
        )

        self.assertEqual(
            parsed, Xi2KeyEvent(keycode="67", state="down", is_repeat=False)
        )
        self.assertEqual(action, "BTN_A")

    def test_flushes_release_without_needing_trailing_blank_separator(self) -> None:
        held_keys = {"67"}
        parsed, action = flush_block(
            [
                "EVENT type 3 (KeyRelease)",
                "    device: 5 (5)",
                "    time: 3096878",
                "    detail: 67",
                "    flags: ",
            ],
            {"67": "BTN_A"},
            held_keys,
        )

        self.assertEqual(
            parsed, Xi2KeyEvent(keycode="67", state="up", is_repeat=False)
        )
        self.assertEqual(action, "BTN_A")
        self.assertEqual(held_keys, set())


class SharedProtocolEncodingTests(unittest.TestCase):
    def test_encoded_event_round_trips(self) -> None:
        payload = encode_action_event(action="BTN_A", state="down", seq=1)
        event = parse_action_event(payload)
        self.assertEqual(event.action, "BTN_A")
        self.assertEqual(event.state, "down")
        self.assertEqual(event.seq, 1)
