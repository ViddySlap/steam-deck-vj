from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deck.xinput_send import (
    consume_warmup_event,
    Xi2KeyEvent,
    flush_block,
    is_complete_xi2_event_block,
    load_bindings,
    next_select_timeout,
    parse_xi2_event_block,
    should_emit_event,
)
from protocol.messages import encode_action_event, parse_action_event


class ParseXi2EventBlockTests(unittest.TestCase):
    def test_parses_initial_key_press(self) -> None:
        self.assertEqual(
            parse_xi2_event_block(
                [
                    "EVENT type 13 (RawKeyPress)",
                    "    device: 5 (5)",
                    "    time: 3096762",
                    "    detail: 67",
                ]
            ),
            Xi2KeyEvent(keycode="67", state="down"),
        )

    def test_parses_key_release(self) -> None:
        self.assertEqual(
            parse_xi2_event_block(
                [
                    "EVENT type 14 (RawKeyRelease)",
                    "    device: 5 (5)",
                    "    time: 3101444",
                    "    detail: 67",
                ]
            ),
            Xi2KeyEvent(keycode="67", state="up"),
        )

    def test_ignores_other_event_blocks(self) -> None:
        self.assertIsNone(
            parse_xi2_event_block(
                [
                    "EVENT type 2 (KeyPress)",
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
            [
                "EVENT type 13 (RawKeyPress)",
                "    device: 5 (5)",
                "    time: 3096762",
                "    detail: 67",
            ],
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
            [
                "EVENT type 14 (RawKeyRelease)",
                "    device: 5 (5)",
                "    time: 3096878",
                "    detail: 67",
            ],
            {"67": "BTN_A"},
            held_keys,
        )

        self.assertEqual(
            parsed, Xi2KeyEvent(keycode="67", state="up")
        )
        self.assertEqual(action, "BTN_A")
        self.assertEqual(held_keys, set())


class Xi2EventCompletionTests(unittest.TestCase):
    def test_detects_complete_raw_keypress_block_at_detail_line(self) -> None:
        self.assertTrue(
            is_complete_xi2_event_block(
                [
                    "EVENT type 13 (RawKeyPress)",
                    "    device: 5 (5)",
                    "    time: 3096762",
                    "    detail: 67",
                ]
            )
        )

    def test_incomplete_raw_keyrelease_block_is_not_complete_before_detail_line(self) -> None:
        self.assertFalse(
            is_complete_xi2_event_block(
                [
                    "EVENT type 14 (RawKeyRelease)",
                    "    device: 5 (5)",
                    "    time: 3096878",
                ]
            )
        )


class NextSelectTimeoutTests(unittest.TestCase):
    def test_waits_for_current_block_before_heartbeat(self) -> None:
        self.assertIsNone(
            next_select_timeout(
                held_keys={"67"},
                block=["EVENT type 3 (KeyRelease)"],
                next_heartbeat_at=10.0,
                now=9.9,
            )
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


class ConsumeWarmupEventTests(unittest.TestCase):
    def test_consumes_first_complete_press_release_cycle(self) -> None:
        held_keys: set[str] = set()
        ready, warmup_keycode = consume_warmup_event(
            Xi2KeyEvent(keycode="67", state="down"), held_keys, None
        )
        self.assertFalse(ready)
        self.assertEqual(warmup_keycode, "67")
        self.assertEqual(held_keys, {"67"})

        ready, warmup_keycode = consume_warmup_event(
            Xi2KeyEvent(keycode="67", state="up"), held_keys, warmup_keycode
        )
        self.assertTrue(ready)
        self.assertIsNone(warmup_keycode)
        self.assertEqual(held_keys, set())

    def test_ignores_duplicate_down_during_warmup(self) -> None:
        held_keys = {"67"}
        ready, warmup_keycode = consume_warmup_event(
            Xi2KeyEvent(keycode="67", state="down"), held_keys, "67"
        )
        self.assertFalse(ready)
        self.assertEqual(warmup_keycode, "67")
        self.assertEqual(held_keys, {"67"})


class SharedProtocolEncodingTests(unittest.TestCase):
    def test_encoded_event_round_trips(self) -> None:
        payload = encode_action_event(action="BTN_A", state="down", seq=1)
        event = parse_action_event(payload)
        self.assertEqual(event.action, "BTN_A")
        self.assertEqual(event.state, "down")
        self.assertEqual(event.seq, 1)
