# Windows MIDI Setup

This project uses:

- `mido` for Python MIDI message handling
- `python-rtmidi` as the local MIDI backend
- `loopMIDI` as the Windows virtual MIDI port for Resolume

## 1. Install Python Dependencies

In Windows PowerShell, from the repo root:

```powershell
py -m pip install -r requirements.txt
```

Or use the repo installer:

```powershell
.\install-windows.cmd
```

## 2. Create a Virtual MIDI Port

Install and open `loopMIDI`, then create two ports named:

```text
DECK_IN
DECK_OUT
```

`DECK_IN` is the control path from the bridge into Resolume.
`DECK_OUT` is reserved for Resolume MIDI output or future feedback work.
Do not use the same virtual port for both directions.

## 3. Confirm the Port Is Visible to Python

Run:

```powershell
py -m windows.list_midi_ports
```

Expected result:

```text
Available MIDI output ports:
- [0] DECK_IN
- [1] DECK_OUT
```

## 4. Start the Receiver With Real MIDI Output

Run:

```powershell
py -m windows.win_recv --map config/windows_midi_map.json --midi-port "DECK_IN" --verbose
```

If you use the default port name, `--midi-port` can be omitted:

```powershell
py -m windows.win_recv --map config/windows_midi_map.json --verbose
```

## 5. Point Resolume at the Same Port

In Resolume MIDI preferences:

- Enable MIDI input on `DECK_IN`
- Disable MIDI output, or send MIDI output only to `DECK_OUT`

Never enable input and output on the same loopMIDI port.

## Notes

- Keep `loopMIDI` running before starting the receiver.
- The receiver opens only a MIDI output to `DECK_IN`; it does not subscribe to MIDI input.
- If the port name is wrong, the receiver will print the available indexed port list.
- The receiver accepts a unique port prefix, so `DECK_IN` can resolve `DECK_IN 1`.
- For initial testing, keep the example mappings in `config/windows_midi_map.json`.
