#!/usr/bin/env bash
# Within app bootstrap: verify built Cactus under third_party/cactus (fixed path),
# then create the app .venv and pip install -r requirements.txt.
#
# Cactus clone / setup / build / downloads are upstream-only — not scripted here.

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${APP_ROOT}/third_party/cactus"

TOTAL_PHASES=2

_log_line() {
  printf '%s\n' "$*"
}

_log_banner() {
  _log_line ""
  _log_line "══════════════════════════════════════════════════════════════════════════════"
  _log_line "  $*"
  _log_line "══════════════════════════════════════════════════════════════════════════════"
}

_phase() {
  local n="$1" name="$2"
  _log_banner "PHASE ${n}/${TOTAL_PHASES} — ${name}"
}

_sub() {
  _log_line "  ▸ $*"
}

_ok() {
  _log_line "  ✓ $*"
}

usage() {
  echo "Within — verify third_party/cactus + libcactus, then app .venv + pip."
  echo ""
  echo "  source sys_setup.sh   Recommended: setup + activate .venv in current shell"
  echo "  ./sys_setup.sh        Setup only (activation does not persist in this shell)"
  echo "  -h, --help            This message."
  exit 0
}

if [[ $# -gt 0 ]]; then
  case "$1" in
    -h|--help) usage ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
fi

lib_basename() {
  [[ "$(uname -s)" == "Darwin" ]] && echo "libcactus.dylib" || echo "libcactus.so"
}

BUILT_LIB="${ENGINE}/cactus/build/$(lib_basename)"

_log_banner "Within — sys_setup.sh"
_log_line "  App root:    ${APP_ROOT}"
_log_line "  Engine root: ${ENGINE} (fixed)"

_phase 1 "Verify Cactus engine (third_party/cactus)"
if [[ ! -d "${ENGINE}" ]]; then
  echo "ERROR: missing directory ${ENGINE}"
  exit 1
fi
[[ -f "${ENGINE}/python/src/cactus.py" ]] || {
  echo "ERROR: missing ${ENGINE}/python/src/cactus.py"
  exit 1
}
_ok "Cactus Python package present"
[[ -f "$BUILT_LIB" ]] || {
  echo "ERROR: shared library not found: $BUILT_LIB"
  exit 1
}
_ok "${BUILT_LIB}"

APP_PY="${APP_ROOT}/.venv/bin/python"

_phase 2 "Application virtualenv + requirements"
_venv_stale=0
if [[ ! -d "${APP_ROOT}/.venv" ]]; then
  _sub "No .venv yet → creating with $(command -v python3)"
  _venv_stale=1
elif ! grep -q "VIRTUAL_ENV.*${APP_ROOT}/.venv" "${APP_ROOT}/.venv/bin/activate" 2>/dev/null; then
  _sub "Stale .venv (path mismatch) → removing and recreating"
  rm -rf "${APP_ROOT}/.venv"
  _venv_stale=1
fi
if [[ "$_venv_stale" -eq 1 ]]; then
  python3 -m venv "${APP_ROOT}/.venv"
  _ok "App venv created at ${APP_ROOT}/.venv"
else
  _ok "App venv already present → reusing ${APP_ROOT}/.venv"
fi

[[ -f "${APP_ROOT}/requirements.txt" ]] || {
  echo "ERROR: missing ${APP_ROOT}/requirements.txt"
  exit 1
}
_sub "[app pip 1/2] Bootstrapping pip..."
"${APP_PY}" -m ensurepip --upgrade -q 2>/dev/null || true
"${APP_PY}" -m pip install --upgrade pip -q
_ok "pip upgraded ($(basename "${APP_PY}"))"
_sub "[app pip 2/2] Installing ${APP_ROOT}/requirements.txt"
"${APP_PY}" -m pip install -r "${APP_ROOT}/requirements.txt" -q
_ok "App requirements installed"

_log_banner "DONE — all phases complete"

# Subshell 里 source 不会影响当前终端；用 source sys_setup.sh 才会在本 shell 激活。
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  # shellcheck source=/dev/null
  source "${APP_ROOT}/.venv/bin/activate"
  _ok "Activated .venv in this shell ($(command -v python))"
  _log_line "  cd ${APP_ROOT} && uvicorn app.main:app --reload --host 0.0.0.0 --port 8765"
else
  _log_line "  To activate in this shell, run:"
  _log_line "    source ${APP_ROOT}/sys_setup.sh"
  _log_line "  Or manually:"
  _log_line "    source ${APP_ROOT}/.venv/bin/activate"
  _log_line "    cd ${APP_ROOT} && uvicorn app.main:app --reload --host 0.0.0.0 --port 8765"
fi
