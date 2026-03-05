from __future__ import annotations

import json
import unittest

from protocol.messages import encode_action_event


class EncodeEventTests(unittest.TestCase):
    def test_encodes_required_fields(self) -> None:
        payload = encode_action_event(
            action="BTN_A",
            state="down",
            seq=4,
            profile_name=None,
            profile_hash=None,
        )
        self.assertEqual(
            json.loads(payload.decode("utf-8")),
            {"kind": "action", "action": "BTN_A", "state": "down", "seq": 4},
        )

    def test_encodes_optional_fields(self) -> None:
        payload = encode_action_event(
            action="BTN_A",
            state="up",
            seq=5,
            profile_name="default",
            profile_hash="abc123",
        )
        self.assertEqual(
            json.loads(payload.decode("utf-8")),
            {
                "kind": "action",
                "action": "BTN_A",
                "state": "up",
                "seq": 5,
                "profile_name": "default",
                "profile_hash": "abc123",
            },
        )
