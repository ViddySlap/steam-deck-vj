from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from windows.config import (
    ConfigError,
    ControlChangeMapping,
    MacroCCMapping,
    NoteMapping,
    load_midi_map,
)


class LoadMidiMapTests(unittest.TestCase):
    def test_loads_note_and_cc_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "map.json"
            path.write_text(
                json.dumps(
                    {
                        "macro_settings": {"fade_duration_seconds": 1.5, "update_hz": 20},
                        "mappings": {
                            "BTN_A": {"type": "note", "channel": 0, "note": 60},
                            "DPAD_UP": {"type": "cc", "channel": 1, "cc": 10},
                            "DPAD_UP_LONG_PRESS": {
                                "type": "macro_cc",
                                "channel": 1,
                                "cc": 11,
                                "gesture": "long_press",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_midi_map(path)

        self.assertEqual(config.macro_settings.fade_duration_seconds, 1.5)
        self.assertEqual(config.macro_settings.update_hz, 20)
        self.assertIsInstance(config.mappings["BTN_A"], NoteMapping)
        self.assertIsInstance(config.mappings["DPAD_UP"], ControlChangeMapping)
        self.assertIsInstance(config.mappings["DPAD_UP_LONG_PRESS"], MacroCCMapping)

    def test_rejects_missing_mappings_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "map.json"
            path.write_text(json.dumps({"bad": {}}), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_midi_map(path)

    def test_rejects_invalid_macro_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "map.json"
            path.write_text(
                json.dumps(
                    {
                        "macro_settings": {"min_value": 127, "max_value": 0},
                        "mappings": {"BTN_A": {"type": "note", "channel": 0, "note": 60}},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_midi_map(path)
