# GitHub Release

Use this flow after building a Windows release on a Windows machine.

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
- `installer-output\STEAMDECK-MIDI-RECEIVER-Setup.exe`

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
- title it `STEAMDECK MIDI Receiver v<version>`
- attach `installer-output\STEAMDECK-MIDI-RECEIVER-Setup.exe`

## 6. Release Notes

Keep release notes short and practical:

- what changed
- whether the installer format changed
- whether users need to recreate `DECK_IN`
- any manual upgrade notes
