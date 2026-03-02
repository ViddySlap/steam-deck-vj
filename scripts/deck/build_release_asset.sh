#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/release-output"
BUNDLE_DIR="${OUTPUT_DIR}/steamdeck-midi-installer"
SOURCE_PATH="${REPO_ROOT}/STEAMDECK-MIDI-SENDER-SETUP.sh"
TARGET_PATH="${BUNDLE_DIR}/STEAMDECK-MIDI-SENDER-SETUP.sh"
LAUNCHER_PATH="${BUNDLE_DIR}/STEAMDECK-MIDI-INSTALL.desktop"
ARCHIVE_PATH="${OUTPUT_DIR}/STEAMDECK-MIDI-SENDER-SETUP.tar.gz"

mkdir -p "${OUTPUT_DIR}"
rm -rf "${BUNDLE_DIR}"
mkdir -p "${BUNDLE_DIR}"
cp "${SOURCE_PATH}" "${TARGET_PATH}"
chmod +x "${TARGET_PATH}"

cat >"${LAUNCHER_PATH}" <<'EOF'
[Desktop Entry]
Type=Application
Version=1.0
Name=STEAMDECK MIDI Installer
Comment=Install or update Steam Deck MIDI
Exec=sh -c 'SCRIPT_DIR="$(dirname "$1")"; chmod +x "$SCRIPT_DIR/STEAMDECK-MIDI-SENDER-SETUP.sh"; exec "$SCRIPT_DIR/STEAMDECK-MIDI-SENDER-SETUP.sh"' sh %k
Terminal=true
Categories=Utility;
Icon=system-software-install
StartupNotify=true
EOF

chmod +x "${LAUNCHER_PATH}"
tar -C "${OUTPUT_DIR}" -czf "${ARCHIVE_PATH}" "$(basename "${BUNDLE_DIR}")"

echo ""
echo "Deck release asset prepared."
echo "Bundle directory: ${BUNDLE_DIR}"
echo "Launcher:         ${LAUNCHER_PATH}"
echo "Archive:          ${ARCHIVE_PATH}"
