# Windows Install

This repo now includes a Windows installer flow for the receiver.

## Goal

From a fresh repo checkout on Windows:

- create a local Python virtual environment
- install the required MIDI dependencies
- create a desktop shortcut that starts the Windows receiver
- keep machine-specific receiver settings in a local JSON file

## Prerequisites

- Git installed on Windows
- Python 3.12 installed and available as `py -3.12`
- `loopMIDI` installed

## Install

If you already cloned the repo, from File Explorer or PowerShell in the repo root, run:

```powershell
.\install-windows.cmd
```

If you want a single bootstrap entrypoint that clones or updates the repo into `%USERPROFILE%\steam-deck-vj` and then installs it, run:

```powershell
.\bootstrap-windows.cmd
```

You can also pass a target install directory:

```powershell
.\bootstrap-windows.cmd C:\VJ\steam-deck-vj
```

This installer will:

- create `.venv`
- install `requirements.txt`
- create `config/windows_receiver_settings.local.json` if it does not already exist
- create a desktop shortcut named `Steam Deck VJ Receiver`

## Configure

Edit `config/windows_receiver_settings.local.json` if needed.

Default settings:

```json
{
  "listen": "0.0.0.0:45123",
  "midi_port": "DECK_IN",
  "map_path": "config/windows_midi_map.json",
  "timeout": 2.0,
  "verbose": true
}
```

The receiver now accepts an exact MIDI port name or a unique prefix. That means a configured `DECK_IN` will successfully resolve `DECK_IN 1` if it is the only matching port.

## Run

Double-click the desktop shortcut:

- `Steam Deck VJ Receiver`

It opens PowerShell and runs the receiver with your local settings.

## Notes

- Resolume MIDI input should point at `DECK_IN`
- Resolume MIDI output should be disabled or sent only to `DECK_OUT`
- Do not use the same loopMIDI port for both input and output
