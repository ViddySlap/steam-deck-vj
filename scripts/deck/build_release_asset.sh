#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/release-output"
SOURCE_PATH="${REPO_ROOT}/STEAMDECK-MIDI-SENDER-SETUP.sh"
TARGET_PATH="${OUTPUT_DIR}/STEAMDECK-MIDI-SENDER-SETUP.sh"

mkdir -p "${OUTPUT_DIR}"
cp "${SOURCE_PATH}" "${TARGET_PATH}"
chmod +x "${TARGET_PATH}"

echo ""
echo "Deck release asset prepared."
echo "Output: ${TARGET_PATH}"
