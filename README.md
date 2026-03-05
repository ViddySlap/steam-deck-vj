# steam-deck-midi

Steam Deck MIDI is a show-focused Steam Deck to Windows MIDI bridge for Resolume.

The control contract is stable Action IDs:

- Steam Deck captures Steam Input-generated buttons.
- Deck sender maps button tokens to Action IDs and sends UDP JSON events.
- Windows receiver maps Action IDs to MIDI note/CC output for Resolume.

## Current status (v0.1.6)

- Deck sender runtime uses direct X11/XI2 raw key listening (no `xinput test` subprocess parsing).
- Sender emits one `down`/`up` pair per press/release and heartbeat messages while held.
- Windows receiver supports:
  - action-to-note/CC mapping from `config/windows_midi_map.json`
  - `macro_cc` fades with feedback-aware manual override handling
  - `relative_cc` repeat output for encoder-style controls
  - duplicate suppression, timeout-based safety release, and panic/reset handling
  - separate MIDI output and feedback input port configuration
- Steam Deck install flow provides branded desktop launchers:
  - `Learn Steam Input Map`
  - `STEAMDECK-MIDI-SENDER`
- Windows release flow includes PyInstaller + Inno Setup packaging.

## Docs

- Receiver: `docs/windows-receiver.md`
- Windows install: `docs/windows-install.md`
- Windows packaging: `docs/windows-packaging.md`
- Windows release checklist: `docs/windows-release-checklist.md`
- GitHub release process: `docs/github-release.md`
- Steam Deck install: `docs/steamdeck-install.md`
- Deck sender behavior: `docs/deck-sender.md`
- Deck Learn Wizard: `docs/deck-learn-wizard.md`
- Deck release checklist: `docs/deck-release-checklist.md`
