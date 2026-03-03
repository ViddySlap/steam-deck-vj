from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deck.learn_wizard import (
    find_duplicate_action,
    is_skip_input,
    load_actions,
    parse_key_press,
    write_bindings,
)


class LoadActionsTests(unittest.TestCase):
    def test_loads_simple_action_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "actions.yaml"
            path.write_text("actions:\n  - BTN_A\n  - BTN_B\n", encoding="utf-8")
            actions = load_actions(str(path))
        self.assertEqual(actions, ["BTN_A", "BTN_B"])

    def test_preserves_action_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "actions.yaml"
            path.write_text(
                "actions:\n  - L3\n  - L4\n  - R3\n  - R4\n", encoding="utf-8"
            )
            actions = load_actions(str(path))
        self.assertEqual(actions, ["L3", "L4", "R3", "R4"])


class ParseKeyPressTests(unittest.TestCase):
    def test_parses_press(self) -> None:
        parsed = parse_key_press("key press   14")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.token, "14")

    def test_ignores_release(self) -> None:
        self.assertIsNone(parse_key_press("key release 14"))


class DuplicateDetectionTests(unittest.TestCase):
    def test_finds_existing_assignment(self) -> None:
        action = find_duplicate_action({"BTN_A": "14"}, "14")
        self.assertEqual(action, "BTN_A")


class SkipInputTests(unittest.TestCase):
    def test_detects_lowercase_s(self) -> None:
        self.assertTrue(is_skip_input(b"s"))

    def test_detects_uppercase_s(self) -> None:
        self.assertTrue(is_skip_input(b"S"))

    def test_ignores_enter(self) -> None:
        self.assertFalse(is_skip_input(b"\n"))


class WriteBindingsTests(unittest.TestCase):
    def test_writes_token_to_action_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "deck_bindings.json"
            write_bindings(str(path), "default", {"BTN_A": "14", "BTN_B": "15"})
            written = path.read_text(encoding="utf-8")

        self.assertIn('"14": "BTN_A"', written)
        self.assertIn('"15": "BTN_B"', written)

    def test_omits_skipped_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "deck_bindings.json"
            write_bindings(str(path), "default", {"BTN_A": "14"})
            written = path.read_text(encoding="utf-8")

        self.assertIn('"14": "BTN_A"', written)
        self.assertNotIn("BTN_B", written)
