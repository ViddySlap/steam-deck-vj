from __future__ import annotations

import unittest

from unittest import mock

from windows.midi import (
    MidiError,
    get_input_port_names,
    get_output_port_names,
    open_midi_input,
    get_port_snapshot,
    resolve_available_input_port_name,
    resolve_available_output_port_name,
    resolve_input_port_name,
    resolve_output_port_name,
)


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

    def test_get_output_port_names_returns_mido_output_names(self) -> None:
        fake_mido = mock.Mock()
        fake_mido.get_output_names.return_value = ["DECK_IN 1", "DECK_OUT 2"]
        with mock.patch.dict("sys.modules", {"mido": fake_mido}):
            self.assertEqual(get_output_port_names(), ["DECK_IN 1", "DECK_OUT 2"])

    def test_get_input_port_names_returns_mido_input_names(self) -> None:
        fake_mido = mock.Mock()
        fake_mido.get_input_names.return_value = ["DECK_IN 1", "DECK_OUT 2"]
        with mock.patch.dict("sys.modules", {"mido": fake_mido}):
            self.assertEqual(get_input_port_names(), ["DECK_IN 1", "DECK_OUT 2"])

    def test_get_port_snapshot_returns_both_lists(self) -> None:
        with mock.patch(
            "windows.midi.get_input_port_names", return_value=["DECK_FEEDBACK 1"]
        ), mock.patch(
            "windows.midi.get_output_port_names", return_value=["DECK_IN 1"]
        ):
            snapshot = get_port_snapshot()

        self.assertEqual(snapshot.input_names, ["DECK_FEEDBACK 1"])
        self.assertEqual(snapshot.output_names, ["DECK_IN 1"])

    def test_resolve_available_output_port_name_uses_live_port_list(self) -> None:
        with mock.patch(
            "windows.midi.get_output_port_names", return_value=["DECK_IN 1", "OTHER"]
        ):
            self.assertEqual(resolve_available_output_port_name("DECK_IN"), "DECK_IN 1")

    def test_resolve_input_port_name_returns_unique_prefix_match(self) -> None:
        resolved = resolve_input_port_name("DECK_OUT", ["DECK_IN 1", "DECK_OUT 2"])
        self.assertEqual(resolved, "DECK_OUT 2")

    def test_resolve_available_input_port_name_uses_live_port_list(self) -> None:
        with mock.patch(
            "windows.midi.get_input_port_names", return_value=["DECK_OUT 2", "OTHER"]
        ):
            self.assertEqual(resolve_available_input_port_name("DECK_OUT"), "DECK_OUT 2")

    def test_open_midi_input_returns_none_without_port_name(self) -> None:
        self.assertIsNone(open_midi_input(None, dry_run=False))

    def test_open_midi_input_returns_dry_run_backend(self) -> None:
        midi_in = open_midi_input("DECK_OUT", dry_run=True)

        assert midi_in is not None
        self.assertEqual(midi_in.port_name, "DECK_OUT")
        self.assertEqual(midi_in.poll_control_changes(), [])
