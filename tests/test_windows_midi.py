from __future__ import annotations

import unittest

from windows.midi import MidiError, resolve_output_port_name


class ResolveOutputPortNameTests(unittest.TestCase):
    def test_returns_exact_match(self) -> None:
        resolved = resolve_output_port_name("DECK_IN 1", ["DECK_IN 1", "DECK_OUT 2"])
        self.assertEqual(resolved, "DECK_IN 1")

    def test_returns_case_insensitive_exact_match(self) -> None:
        resolved = resolve_output_port_name("deck_in 1", ["DECK_IN 1", "DECK_OUT 2"])
        self.assertEqual(resolved, "DECK_IN 1")

    def test_returns_unique_prefix_match(self) -> None:
        resolved = resolve_output_port_name("DECK_IN", ["DECK_IN 1", "DECK_OUT 2"])
        self.assertEqual(resolved, "DECK_IN 1")

    def test_rejects_ambiguous_prefix_match(self) -> None:
        with self.assertRaisesRegex(MidiError, "matched multiple ports"):
            resolve_output_port_name("DECK_IN", ["DECK_IN 1", "DECK_IN 2"])

    def test_rejects_missing_port(self) -> None:
        with self.assertRaisesRegex(MidiError, "not found"):
            resolve_output_port_name("DECK_IN", ["OTHER 1", "OTHER 2"])
