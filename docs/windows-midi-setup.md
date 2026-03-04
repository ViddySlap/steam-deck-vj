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

Install and open `loopMIDI`, then create a port named:

```text
DECK_IN
```

`DECK_IN` is the control path from the bridge into Resolume.

If you want receiver-side cache feedback from Resolume, create a second port:

```text
DECK_OUT
```

`DECK_OUT` is the feedback path from Resolume back into the receiver.

## 3. Confirm the Port Is Visible to Python

Run:

```powershell
py -m windows.list_midi_ports
```

Expected result:

```text
Available MIDI input ports:
- [0] DECK_OUT
Available MIDI output ports:
- [0] DECK_IN
```

## 4. Start the Receiver With Real MIDI Output

Run:

```powershell
py -m windows.win_recv --map config/windows_midi_map.json --midi-port "DECK_IN" --feedback-port "DECK_OUT" --verbose
```

If you use the default port name, `--midi-port` can be omitted:

```powershell
py -m windows.win_recv --map config/windows_midi_map.json --feedback-port "DECK_OUT" --verbose
```

## 5. Point Resolume at the Same Port

In Resolume MIDI preferences:

- Enable MIDI input on `DECK_IN`
- Leave MIDI output disabled on `DECK_IN`
- For only the mappings that need cache/state feedback, set MIDI output to `DECK_OUT`

Do not enable Resolume MIDI output on `DECK_IN`.

## Notes

- Keep `loopMIDI` running before starting the receiver.
- `--feedback-port` is optional. Without it, the receiver behaves as output-only.
- Current feedback/cache handling applies to tracked `macro_cc` parameters.
- If the port name is wrong, the receiver will print the available indexed port list.
- The receiver accepts a unique port prefix, so `DECK_IN` can resolve `DECK_IN 1`.
- For initial testing, keep the example mappings in `config/windows_midi_map.json`.
- The shipped example map assigns the four D-pad opacity macros to CCs `20` through `23`; use
  Resolume MIDI Learn to bind those CCs to the target layer opacity controls manually.
