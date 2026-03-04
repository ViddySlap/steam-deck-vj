# Windows Receiver

This first implementation slice provides:

- UDP listener for JSON action events
- protocol validation for `action`, `state`, and `seq`
- per-sender sequence filtering for out-of-order packets
- action-to-MIDI mapping from `config/windows_midi_map.json`
- timeout and shutdown failsafes that release active notes/controls
- optional MIDI feedback input on a separate port such as `DECK_OUT`
- receiver-side cache for tracked `macro_cc` parameters
- manual Resolume override for active fades when inbound feedback diverges

## Message Format

Incoming UDP datagrams are UTF-8 JSON objects:

```json
{
  "action": "BTN_A",
  "state": "down",
  "seq": 1,
  "profile_name": "default",
  "profile_hash": "abc123"
}
```

Required fields:

- `action`
- `state` with value `down` or `up`
- `seq` as a non-negative integer

## MIDI Map Format

Example `config/windows_midi_map.json`:

```json
{
  "macro_settings": {
    "fade_duration_seconds": 2.0,
    "update_hz": 30,
    "min_value": 0,
    "max_value": 127
  },
  "mappings": {
    "BTN_A": { "type": "note", "channel": 0, "note": 60, "velocity": 127 },
    "DPAD_UP": { "type": "macro_cc", "channel": 0, "cc": 22, "gesture": "click" },
    "DPAD_UP_LONG_PRESS": {
      "type": "macro_cc",
      "channel": 0,
      "cc": 22,
      "gesture": "long_press"
    }
  }
}
```

Supported mapping types:

- `note`
- `cc`
- `macro_cc`
- `relative_cc`
- `staged_note_macro`

`macro_cc` uses the same CC for click and long-press actions. A click toggles immediately between
the configured min/max values, while a long press starts a receiver-side linear fade to the opposite
value and continues to completion even after button release.

`relative_cc` emits repeated CC ticks while the action is held. It is intended for Resolume
relative encoder mappings such as clip browser scrolling. The receiver does not cache state for
these mappings; each sent CC value is a standalone increment/decrement step.

`staged_note_macro` sends a modifier `note_on` first, waits for a configured delay, then sends a
second trigger `note_on` on a different channel using the same note number. The modifier note is
held for a fixed receiver-side duration and then released automatically.

The receiver also maintains authoritative layer-state publishers for the Steam Input toggle layers:
- ABXY layer state uses the `START` note number on Channels 1 and 2 as explicit Layer 1 / Layer 2 lamps
- bumper/trigger layer state uses the `SELECT` note number on Channels 1 and 2 as explicit Layer 1 / Layer 2 lamps
- raw `START` and `SELECT` button presses remain available on Channel 3 for MIDI Learn
- layer state self-heals from ground-truth action IDs such as `BTN_A_LAYER_2` or `L1_LAYER_2`

Tracked `macro_cc` parameters are also the current feedback/cache subset. When `--feedback-port` is
configured, inbound CC feedback on the same channel/CC updates the cache. During an active fade, the
receiver ignores matching feedback values but cancels the fade if Resolume reports a different value,
so manual movement in Resolume wins over automation.

## Running

Dry-run mode works in WSL and logs the MIDI events that would be sent:

```bash
python -m windows.win_recv --map config/windows_midi_map.json --dry-run --verbose
```

Send a test packet from the same machine:

```bash
python3 -m protocol.send_test --action BTN_A --state tap --target 127.0.0.1:45123
```

For real Windows MIDI output, install a `mido`-compatible backend on Windows and run:

```bash
py -m pip install -r requirements.txt
py -m windows.list_midi_ports
py -m windows.win_recv --map config/windows_midi_map.json --midi-port "DECK_IN" --feedback-port "DECK_OUT" --verbose
```

Use separate loopMIDI ports for each direction:

- `DECK_IN`: receiver output into Resolume MIDI input
- `DECK_OUT`: Resolume MIDI output back into the receiver for selected feedback-enabled mappings

Do not point Resolume MIDI output back at `DECK_IN`.

## Limitations

- WSL cannot fully validate Windows MIDI port behavior.
- Sequence handling currently assumes monotonically increasing integer counters.
- A receiver-side loop guard drops ultra-fast duplicate events and temporarily mutes output if the incoming event rate spikes abnormally.
- Startup cache initialization from inbound feedback is not implemented.
- Real MIDI output must be validated on Windows proper with loopMIDI or another visible output port.
