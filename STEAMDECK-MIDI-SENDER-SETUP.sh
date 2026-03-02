#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/ViddySlap/steam-deck-vj.git"
INSTALL_DIR="${HOME}/steam-deck-vj"
APPLICATIONS_DIR="${HOME}/.local/share/applications"
DESKTOP_DIR="${HOME}/Desktop"
LEARN_DESKTOP="${APPLICATIONS_DIR}/learn-steam-input-map.desktop"
SEND_DESKTOP="${APPLICATIONS_DIR}/steamdeck-midi-sender.desktop"
LEARN_ICON_PATH="${INSTALL_DIR}/assets/deck/learn-map-icon.png"
SEND_ICON_PATH="${INSTALL_DIR}/assets/deck/sender-icon.png"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

write_desktop_file() {
  local path="$1"
  local name="$2"
  local exec_path="$3"
  local icon_path="$4"
  local fallback_icon="$5"
  local icon_value="${fallback_icon}"

  if [[ -f "${icon_path}" ]]; then
    icon_value="${icon_path}"
  fi

  cat >"${path}" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=${name}
Exec=${exec_path}
Terminal=true
Categories=Utility;
Icon=${icon_value}
EOF

  chmod +x "${path}"
}

require_command git
require_command python3
require_command xinput

mkdir -p "${APPLICATIONS_DIR}"
mkdir -p "${DESKTOP_DIR}"

if [[ -d "${INSTALL_DIR}/.git" ]]; then
  git -C "${INSTALL_DIR}" pull --ff-only
else
  rm -rf "${INSTALL_DIR}"
  git clone "${REPO_URL}" "${INSTALL_DIR}"
fi

chmod +x "${INSTALL_DIR}/scripts/deck/run_sender.sh"
chmod +x "${INSTALL_DIR}/scripts/deck/run_learn_map.sh"

if [[ ! -f "${INSTALL_DIR}/config/deck_runtime_settings.local.json" ]]; then
  cp \
    "${INSTALL_DIR}/config/deck_runtime_settings.example.json" \
    "${INSTALL_DIR}/config/deck_runtime_settings.local.json"
fi

write_desktop_file \
  "${LEARN_DESKTOP}" \
  "Learn Steam Input Map" \
  "${INSTALL_DIR}/scripts/deck/run_learn_map.sh" \
  "${LEARN_ICON_PATH}" \
  "utilities-terminal"

write_desktop_file \
  "${SEND_DESKTOP}" \
  "STEAMDECK-MIDI-SENDER" \
  "${INSTALL_DIR}/scripts/deck/run_sender.sh" \
  "${SEND_ICON_PATH}" \
  "applications-games"

cp "${LEARN_DESKTOP}" "${DESKTOP_DIR}/Learn Steam Input Map.desktop"
cp "${SEND_DESKTOP}" "${DESKTOP_DIR}/STEAMDECK-MIDI-SENDER.desktop"
chmod +x "${DESKTOP_DIR}/Learn Steam Input Map.desktop"
chmod +x "${DESKTOP_DIR}/STEAMDECK-MIDI-SENDER.desktop"

echo ""
echo "Steam Deck install complete."
echo "Repo: ${INSTALL_DIR}"
echo "Desktop launchers:"
echo "- Learn Steam Input Map"
echo "- STEAMDECK-MIDI-SENDER"
echo ""
echo "Open Learn Steam Input Map first if you need to rebuild deck_bindings.json."
