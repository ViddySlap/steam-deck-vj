# Deck Release Checklist

Use this checklist when preparing a downloadable Steam Deck installer release.

## Build Machine

- use a Linux machine or Steam Deck
- ensure the repo is up to date

## Prepare The Release Asset

From the repo root:

```bash
bash ./scripts/deck/build_release_asset.sh
```

Verify:

- `release-output/STEAMDECK-MIDI-SENDER-SETUP.sh`

## What The Installer Does

The Deck release asset:

- clones or updates the repo into `~/steam-deck-vj`
- creates `config/deck_runtime_settings.local.json` if missing
- creates desktop launchers for:
  - `Learn Steam Input Map`
  - `STEAMDECK-MIDI-SENDER`

## Target Deck Setup

On the target Steam Deck in Desktop Mode:

1. Download `STEAMDECK-MIDI-SENDER-SETUP.sh`.
2. Open a terminal in the download location.
3. Run:

```bash
bash ./STEAMDECK-MIDI-SENDER-SETUP.sh
```

4. Use `Learn Steam Input Map` if bindings need to be rebuilt.
5. Use `STEAMDECK-MIDI-SENDER` to create/select a target preset and start sending.

## Upgrade Behavior

- rerunning the installer updates the repo checkout in `~/steam-deck-vj`
- rerunning the installer keeps `config/deck_runtime_settings.local.json`
- sender target presets remain stored in that local settings file
