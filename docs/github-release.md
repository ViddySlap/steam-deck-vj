# GitHub Release

Use this flow after preparing release artifacts for Windows and Steam Deck.

## 1. Confirm Version

Check the repo root `VERSION` file and update it before building if needed.

## 2. Build Release Artifacts

From the repo root on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\build_exe.ps1 -RepoRoot (Get-Location).Path
powershell -ExecutionPolicy Bypass -File .\scripts\windows\build_installer.ps1 -RepoRoot (Get-Location).Path
```

Verify:

- `dist\STEAMDECK-MIDI-RECEIVER.exe`
- `installer-output\STEAMDECK-MIDI-RECEIVER-Setup-<version>.exe`

From the repo root on Linux or Steam Deck:

```bash
bash ./scripts/deck/build_release_asset.sh
```

Verify:

- `release-output/STEAMDECK-MIDI-SENDER-SETUP.tar.gz`

## 3. Commit The Version Bump

If you changed `VERSION`, commit and push it to `main`.

## 4. Tag The Release

From the repo root:

```bash
git tag v<version>
git push origin v<version>
```

Example:

```bash
git tag v0.1.0
git push origin v0.1.0
```

## 5. Create The GitHub Release

On GitHub:

- open the repo Releases page
- create a new release from tag `v<version>`
- title it `STEAMDECK MIDI TX/RX v<version>`
- attach `installer-output\STEAMDECK-MIDI-RECEIVER-Setup-<version>.exe`
- attach `release-output\STEAMDECK-MIDI-SENDER-SETUP.tar.gz`

## 6. Release Notes

Keep release notes short and practical:

- what changed
- whether the installer format changed
- whether users need to recreate `DECK_IN`
- any Steam Deck installer/update notes
- any manual upgrade notes
