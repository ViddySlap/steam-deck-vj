# agents.md — Steam Deck MIDI

## Project

- App name: **Steam Deck MIDI**
- Repository: `steam-deck-vj`
- Purpose: Provide a show-ready control bridge where Steam Deck inputs (mapped via Steam Input) become stable Action events that are sent over the network to a Windows machine, where they are converted into MIDI messages for Resolume.
- Primary users: VJs and live visual performers using a Steam Deck (SteamOS Desktop Mode) to control Resolume on a Windows machine over a dedicated 10.10.10.x network.

---

## Core Philosophy

1. Steam Input is the only mapping UI.
2. Action IDs are the stable contract.
3. Windows is the MIDI device.
4. Tokens are disposable.
5. The show must never break.

---

## Memory System

### memory.txt (Persistent Project Context)

This repository includes a `memory.txt` file that acts as long-term project memory across agent sessions.

On startup, agents **must read `memory.txt`** to understand prior decisions, constraints, architectural reasoning, and current progress.

### When to Update memory.txt

Agents are encouraged and authorized to update `memory.txt` when appropriate, but must:

- Preserve important historical decisions.
- Avoid deleting critical architectural context.
- Avoid unnecessary verbosity.
- Keep entries structured and concise.

Updates should occur at natural stopping points, such as:

- After a major milestone is completed.
- When the user says “everything is working.”
- When the user says “I’m not sure what to do next.”
- When an architectural decision is finalized.
- When packaging, protocol, or reliability changes occur.

### Update Philosophy

- Do not interrupt active work just to update memory.
- Prefer updating at logical boundaries.
- Favor summary over raw logs.
- Maintain clarity over completeness.

The goal of `memory.txt` is:
To allow future agents to resume work safely without losing context — while never blocking forward progress.

---

## Definition of Done

### Steam Deck Side (SteamOS Desktop Mode / X11)

- CLI Learn Wizard:
  - Captures Steam Input–generated X11 key events.
  - Writes token → Action ID profile bindings.
- Sender:
  - Captures key press/release events.
  - Translates to Action IDs using profile.
  - Sends Action events over UDP.
- Preset system:
  - Supports multiple target IP presets.
  - Presets saved locally.
- Installer:
  - Downloadable Deck installer entrypoint.
  - Installs dependencies.
  - Installs/updates repo into `~/steam-deck-vj`.
  - Creates two branded desktop launchers.

Desktop Launchers:
- **Learn Steam Input Map**
- **STEAMDECK-MIDI-SENDER**

Each launcher:
- Has independent branding.
- Uses a clean entrypoint.
- Does not expose internal script names.

---

### Windows Side

- UDP receiver:
  - Listens on configurable host:port.
  - Converts Action events → MIDI.
- Uses `windows_midi_map.json` for Action → MIDI mapping.
- Supports:
  - Note + CC output.
  - Sequence filtering.
  - Duplicate suppression.
  - Timeout-based stuck-note release.
  - Panic/reset behavior.
  - Rate limiting / loop guard.
- MIDI port discovery and smart resolution.
- Clear errors if required MIDI port missing.
- Verified with loopMIDI + Resolume.

Packaging:
- PyInstaller EXE build.
- Branded EXE icon.
- Version stamping from root `VERSION`.
- Inno Setup installer.
- Desktop shortcut.
- Local config survives upgrades.
- GitHub Releases workflow established.

---

## Current Phase: Distribution & Productization

The project has moved beyond proof-of-concept into packaging and release.

Primary focus:

1. Professional packaging (Deck + Windows).
2. Branding and UX polish.
3. Installer-driven deployment.
4. Preset-driven sender UX.
5. Versioned GitHub releases.

Goal:
A third party should be able to install Steam Deck MIDI without touching the repository manually.

---

## Steam Deck Sender Preset Workflow

When launching **STEAMDECK-MIDI-SENDER**:

1. Display preset list:
   - Preset 1
   - Additional presets
   - "Create new preset"

2. Create new preset:
   - Prompt: "What is your target IP address?"
   - Prompt: "What is the name of the target?"
   - Save preset atomically.
   - Return to preset selection list.

3. Selecting a preset:
   - Enters sending mode.
   - Sends Action events to chosen target IP.

Local Deck runtime config:
- `deck_runtime_settings.local.json`
- Stores:
  - XInput device ID.
  - Sender target presets.
- Uses atomic writes.
- Survives updates.

---

## Architecture

### Stable Contract

- **Action IDs** = stable semantic API.
- **Tokens** = disposable key identifiers captured from X11.
- Windows never sees raw tokens.

### Message Format (v1)

UDP JSON messages:

## Windows Operations via SSH (Guardrails)

The WSL-side agent may run Windows-specific operations ONLY through the repo wrapper script:

- `scripts/windows/ssh_task.sh <task>`

The agent MUST NOT execute raw SSH one-liners like:
`ssh ... "powershell ..."`

### Allowed tasks

`scripts/windows/ssh_task.sh` exposes ONLY:

- `status` — git status + VERSION (read-only)
- `pull` — git pull --ff-only (repo-only change)
- `build_exe` — runs `scripts/windows/build_exe.ps1`
- `build_installer` — runs `scripts/windows/build_installer.ps1`
- `list_output` — lists `installer-output` directory

### Safety constraints

- Hardcode the Windows repo root path and restrict all operations to it.
- Refuse any task not on the allowlist.
- No arbitrary command strings.
- No deletion outside the build output directory (and only if a dedicated clean task is added later).

### Codex execution policy

- SSH commands may require explicit approval depending on sandbox rules.
- Prefer approving ONLY the wrapper script execution, not raw SSH commands.
- If Codex requests elevated execution for SSH, the user must verify the wrapper task being run.
---