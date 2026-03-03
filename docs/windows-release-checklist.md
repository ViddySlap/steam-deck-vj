# Windows Release Checklist

Use this checklist when preparing a USB-friendly Windows release.

## Build Machine

- use a Windows machine
- ensure Python 3.12 is installed
- ensure Inno Setup 6 is installed
- ensure the repo is up to date

## Build

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\build_exe.ps1 -RepoRoot (Get-Location).Path
```

Verify:

- `dist\STEAMDECK-MIDI-RECEIVER.exe`

Then build the installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\build_installer.ps1 -RepoRoot (Get-Location).Path
```

Verify:

- `installer-output\STEAMDECK-MIDI-RECEIVER-Setup-<version>.exe`

## USB Contents

Copy to the USB drive:

- `installer-output\STEAMDECK-MIDI-RECEIVER-Setup-<version>.exe`
- a short text note with setup steps if desired

## Target Machine Setup

On the target Windows machine:

1. Install `loopMIDI`.
2. Create a `DECK_IN` loopMIDI port.
3. Run `STEAMDECK-MIDI-RECEIVER-Setup-<version>.exe`.
4. Launch `STEAMDECK MIDI Receiver` from the desktop or Start Menu shortcut.
5. In Resolume, enable MIDI input on `DECK_IN`.
6. Keep Resolume MIDI output on that port disabled.

## Upgrade Behavior

- installer updates the packaged EXE and example config files
- installer preserves `config\windows_receiver_settings.local.json`

Edit `windows_receiver_settings.local.json` on installed machines for machine-specific settings.
