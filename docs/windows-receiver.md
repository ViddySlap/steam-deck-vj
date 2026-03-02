# Windows Receiver

This first implementation slice provides:

- UDP listener for JSON action events
- protocol validation for `action`, `state`, and `seq`
- per-sender sequence filtering for out-of-order packets
- action-to-MIDI mapping from `config/windows_midi_map.json`
- timeout and shutdown failsafes that release active notes/controls

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
  "mappings": {
    "BTN_A": { "type": "note", "channel": 0, "note": 60, "velocity": 127 },
    "DPAD_UP": { "type": "cc", "channel": 0, "cc": 1, "on_value": 127, "off_value": 0 }
  }
}
```

Supported mapping types:

- `note`
- `cc`

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
py -m windows.win_recv --map config/windows_midi_map.json --midi-port "DECK_IN" --verbose
```

The Windows receiver opens only a MIDI output port. It does not subscribe to MIDI input.
Use `DECK_IN` for bridge output into Resolume, and leave Resolume MIDI output on that port disabled.

## Limitations

- WSL cannot fully validate Windows MIDI port behavior.
- Sequence handling currently assumes monotonically increasing integer counters.
- A receiver-side loop guard drops ultra-fast duplicate events and temporarily mutes output if the incoming event rate spikes abnormally.
- Real MIDI output must be validated on Windows proper with loopMIDI or another visible output port.
