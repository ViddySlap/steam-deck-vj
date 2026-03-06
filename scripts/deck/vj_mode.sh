#!/usr/bin/env bash
set -euo pipefail

VJ_HOME="${HOME}/vj-mode"
LOG_DIR="${VJ_HOME}/logs"
ENV_FILE="${VJ_HOME}/vj_mode.env"
RUN_TS="$(date +%Y%m%d-%H%M%S)"
MAIN_LOG="${LOG_DIR}/vj_mode-${RUN_TS}.log"
INPUTLEAP_LOG="${LOG_DIR}/inputleap-${RUN_TS}.log"
TOUCHOSC_LOG="${LOG_DIR}/touchosc-${RUN_TS}.log"
SENDER_LOG="${LOG_DIR}/sender-${RUN_TS}.log"

mkdir -p "${LOG_DIR}"
touch "${MAIN_LOG}"

log() {
  printf '[%s] %s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)" "$*" | tee -a "${MAIN_LOG}"
}

# shellcheck disable=SC1090
if [[ -f "${ENV_FILE}" ]]; then
  source "${ENV_FILE}"
fi

TOUCHOSC_BIN="${TOUCHOSC_BIN:-${HOME}/Applications/TouchOSC/TouchOSC}"
TOUCHOSC_FILE="${TOUCHOSC_FILE:-${HOME}/Documents/TouchOSC/STEAMDECK V1.tosc}"
INPUTLEAP_ENABLE="${INPUTLEAP_ENABLE:-1}"
INPUTLEAP_FLATPAK_APP="${INPUTLEAP_FLATPAK_APP:-io.github.input_leap.input-leap}"
INPUTLEAP_CONFIG="${INPUTLEAP_CONFIG:-${HOME}/.var/app/io.github.input_leap.input-leap/config/InputLeap/InputLeap.conf}"
INPUTLEAP_EXTRA_ARGS="${INPUTLEAP_EXTRA_ARGS:-}"
INPUTLEAP_MODE="${INPUTLEAP_MODE:-server}"
SENDER_ENABLE="${SENDER_ENABLE:-0}"
SENDER_CMD="${SENDER_CMD:-${HOME}/steam-deck-midi/scripts/deck/run_sender.sh}"

INPUTLEAP_PID=""
SENDER_PID=""

cleanup() {
  local exit_code="$1"
  if [[ -n "${SENDER_PID}" ]] && kill -0 "${SENDER_PID}" 2>/dev/null; then
    log "Stopping sender pid=${SENDER_PID}"
    kill "${SENDER_PID}" 2>/dev/null || true
  fi
  if [[ -n "${INPUTLEAP_PID}" ]] && kill -0 "${INPUTLEAP_PID}" 2>/dev/null; then
    log "Stopping InputLeap pid=${INPUTLEAP_PID}"
    kill "${INPUTLEAP_PID}" 2>/dev/null || true
  fi
  log "VJ Mode finished with exit code ${exit_code}"
}

trap 'cleanup $?' EXIT

log "VJ Mode starting"
log "Main log: ${MAIN_LOG}"
log "Session: DESKTOP_SESSION=${DESKTOP_SESSION:-} DISPLAY=${DISPLAY:-} XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-}"

# Steam injects overlay libraries; this can break some native binaries.
unset LD_PRELOAD
log "LD_PRELOAD cleared"

if [[ "${INPUTLEAP_ENABLE}" == "1" ]]; then
  if command -v flatpak >/dev/null 2>&1; then
    if [[ -f "${INPUTLEAP_CONFIG}" ]]; then
      if [[ "${INPUTLEAP_MODE}" == "client" ]]; then
        log "Starting InputLeap client (flatpak) with config ${INPUTLEAP_CONFIG}"
        # shellcheck disable=SC2086
        flatpak run --command=input-leapc "${INPUTLEAP_FLATPAK_APP}" \
          --no-daemon --no-restart --use-x11 --display "${DISPLAY:-:0}" \
          --config "${INPUTLEAP_CONFIG}" ${INPUTLEAP_EXTRA_ARGS} \
          >"${INPUTLEAP_LOG}" 2>&1 &
      else
        log "Starting InputLeap server (flatpak) with config ${INPUTLEAP_CONFIG}"
        # shellcheck disable=SC2086
        flatpak run --command=input-leaps "${INPUTLEAP_FLATPAK_APP}" \
          --no-daemon --no-restart --use-x11 --display "${DISPLAY:-:0}" \
          --config "${INPUTLEAP_CONFIG}" ${INPUTLEAP_EXTRA_ARGS} \
          >"${INPUTLEAP_LOG}" 2>&1 &
      fi
      INPUTLEAP_PID="$!"
      log "InputLeap pid=${INPUTLEAP_PID}, log=${INPUTLEAP_LOG}"
    else
      log "InputLeap config not found at ${INPUTLEAP_CONFIG}; skipping InputLeap startup"
    fi
  else
    log "flatpak command missing; skipping InputLeap startup"
  fi
fi

if [[ "${SENDER_ENABLE}" == "1" ]]; then
  if [[ -x "${SENDER_CMD}" ]]; then
    log "Starting sender: ${SENDER_CMD}"
    "${SENDER_CMD}" >"${SENDER_LOG}" 2>&1 &
    SENDER_PID="$!"
    log "Sender pid=${SENDER_PID}, log=${SENDER_LOG}"
  else
    log "Sender command missing or not executable: ${SENDER_CMD}"
  fi
fi

if [[ ! -x "${TOUCHOSC_BIN}" ]]; then
  log "TouchOSC binary not executable: ${TOUCHOSC_BIN}"
  exit 1
fi

if [[ ! -f "${TOUCHOSC_FILE}" ]]; then
  log "TouchOSC layout file not found: ${TOUCHOSC_FILE}"
  exit 1
fi

log "Launching TouchOSC with layout: ${TOUCHOSC_FILE}"
set +e
"${TOUCHOSC_BIN}" "${TOUCHOSC_FILE}" >"${TOUCHOSC_LOG}" 2>&1
touchosc_exit="$?"
set -e
log "TouchOSC exited with code ${touchosc_exit}"
exit "${touchosc_exit}"
