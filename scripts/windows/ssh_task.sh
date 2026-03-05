#!/usr/bin/env bash
set -euo pipefail

# Guardrailed Windows SSH task runner.
# Only allow known release tasks inside the Windows repo root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_CONFIG="$SCRIPT_DIR/.ssh_task.local"

# Local, untracked override for environment-specific host/user details.
if [[ -f "$LOCAL_CONFIG" ]]; then
  # shellcheck source=/dev/null
  source "$LOCAL_CONFIG"
fi

: "${WIN_SSH_HOST:?Set WIN_SSH_HOST (for example: export WIN_SSH_HOST='user@host').}"
WIN_USER_HOST="$WIN_SSH_HOST"
WIN_REPO_ROOT='C:\Users\Ben\steam-deck-vj'

usage() {
  cat <<'EOF'
Usage: scripts/windows/ssh_task.sh <task>

Required local config:
  WIN_SSH_HOST=user@host  (export env var or put it in scripts/windows/.ssh_task.local)

Allowed tasks:
  status          Show git status and VERSION
  pull            git pull --ff-only
  build_exe       Build Windows receiver EXE
  build_installer Build Windows installer EXE
  list_output     List installer-output artifacts
EOF
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

task="$1"

run_remote() {
  local cmd="$1"
  ssh "$WIN_USER_HOST" "$cmd"
}

case "$task" in
  status)
    run_remote "powershell -NoProfile -ExecutionPolicy Bypass -Command \"cd '$WIN_REPO_ROOT'; git status --short --branch; Get-Content VERSION\""
    ;;
  pull)
    run_remote "powershell -NoProfile -ExecutionPolicy Bypass -Command \"cd '$WIN_REPO_ROOT'; git pull --ff-only\""
    ;;
  build_exe)
    run_remote "powershell -NoProfile -ExecutionPolicy Bypass -File $WIN_REPO_ROOT\\scripts\\windows\\build_exe.ps1 -RepoRoot $WIN_REPO_ROOT"
    ;;
  build_installer)
    run_remote "powershell -NoProfile -ExecutionPolicy Bypass -File $WIN_REPO_ROOT\\scripts\\windows\\build_installer.ps1 -RepoRoot $WIN_REPO_ROOT"
    ;;
  list_output)
    run_remote "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Get-ChildItem '$WIN_REPO_ROOT\\installer-output' | Select Name,Length,LastWriteTime\""
    ;;
  *)
    echo "Error: task '$task' is not allowed." >&2
    usage
    exit 2
    ;;
esac
