#!/usr/bin/env bash
# Bootstrap: clone Cactus into third_party/, create engine venv, pip install, cactus build --python,
# download default chat + ASR weights, emit ./setup.env.
# Uses only "${ENGINE}/venv/bin/python" for pip (avoids PEP 668 / Homebrew); does not patch upstream setup.
#
# Prerequisites: cmake, make, C++ compiler; python3.12; macOS arm64 may need vendored libcurl (see Cactus README).
#
# Usage (Within app root):
#   chmod +x sys_setup.sh && ./sys_setup.sh
#
# Also: sources setup.env, creates .venv, pip install -r requirements.txt (same as former manual steps).
# Then run: source ./setup.env && source .venv/bin/activate && uvicorn ...

set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
THIRD_PARTY="${APP_ROOT}/third_party"
DEFAULT_ENGINE="${THIRD_PARTY}/cactus"
ENGINE="${CACTUS_ENGINE_PATH:-$DEFAULT_ENGINE}"
GIT_URL="${CACTUS_GIT_URL:-https://github.com/cactus-compute/cactus.git}"

SKIP_CLONE=0
SKIP_BUILD=0
SKIP_MODELS=0
SHALLOW=(--depth 1)

CHAT_MODEL="${CACTUS_MODEL_ID:-google/gemma-4-E2B-it}"
ASR_MODEL="${CACTUS_ASR_MODEL_ID:-nvidia/parakeet-tdt-0.6b-v3}"
PRECISION="${CACTUS_WEIGHTS_PRECISION:-INT4}"

usage() {
  echo "Within — clone/build Cactus engine + download weights."
  echo "  --skip-clone  --skip-build  --skip-models  --full-clone  --engine PATH"
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --skip-clone) SKIP_CLONE=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-models) SKIP_MODELS=1; shift ;;
    --full-clone) SHALLOW=(); shift ;;
    --engine)
      [[ $# -lt 2 ]] && { echo "ERROR: --engine needs a path"; exit 1; }
      ENGINE="$(cd "$2" && pwd)"
      shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

lib_basename() {
  [[ "$(uname -s)" == "Darwin" ]] && echo "libcactus.dylib" || echo "libcactus.so"
}

BUILT_LIB="${ENGINE}/cactus/build/$(lib_basename)"
VENV="${ENGINE}/venv"
PY="${VENV}/bin/python"

# Create venv + install cactus CLI using only venv python (no source ./setup, no PEP 668 issues).
_engine_install_python_tools() {
  if ! command -v python3.12 &>/dev/null; then
    echo "ERROR: python3.12 not found (brew install python@3.12)"
    exit 1
  fi
  echo "Engine venv + pip (this can take a while)..."
  [[ -d "$VENV" ]] || python3.12 -m venv "$VENV"
  [[ -x "$PY" ]] || { echo "ERROR: no $PY"; exit 1; }

  "$PY" -m pip install --upgrade pip -q
  REQ="${ENGINE}/python/requirements.txt"
  [[ -f "$REQ" ]] || { echo "ERROR: missing $REQ"; exit 1; }
  "$PY" -m pip install -r "$REQ" -q

  PARENT_REQ="${ENGINE}/../requirements.txt"
  if [[ -f "$PARENT_REQ" ]] && [[ "$PARENT_REQ" != "$REQ" ]]; then
    "$PY" -m pip install -r "$PARENT_REQ" -q || true
  fi

  "$PY" -m pip install -e "${ENGINE}/python" -q
  echo "cactus CLI at ${VENV}/bin/cactus"
}

echo "== Within — sys_setup.sh =="
echo "App root:    ${APP_ROOT}"
echo "Engine root: ${ENGINE}"
echo ""

if [[ "$SKIP_CLONE" -eq 0 ]]; then
  if [[ -d "${ENGINE}/.git" ]] || [[ -f "${ENGINE}/python/src/cactus.py" ]]; then
    echo "Engine already present; skip clone."
  else
    mkdir -p "${THIRD_PARTY}"
    echo "Cloning ${GIT_URL} → ${ENGINE}"
    git clone "${SHALLOW[@]}" "${GIT_URL}" "${ENGINE}"
  fi
else
  [[ -f "${ENGINE}/python/src/cactus.py" ]] || { echo "ERROR: missing ${ENGINE}/python/src/cactus.py"; exit 1; }
fi

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  _engine_install_python_tools
  echo "Building libcactus (Python FFI shared lib)..."
  (
    cd "${ENGINE}"
    export PATH="${VENV}/bin:${PATH}"
    cactus build --python
  )
else
  echo "Skipping build (--skip-build)."
fi

[[ -f "$BUILT_LIB" ]] || {
  echo "ERROR: not found: $BUILT_LIB"
  exit 1
}
echo "Shared library: $BUILT_LIB"

CACTUS_CLI="${VENV}/bin/cactus"

if [[ "$SKIP_MODELS" -eq 0 ]]; then
  [[ -x "$CACTUS_CLI" ]] || {
    echo "ERROR: $CACTUS_CLI missing. Run without --skip-build once."
    exit 1
  }
  echo "Downloading models (${PRECISION}) → ${ENGINE}/weights/ ..."
  export CACTUS_CLI
  (
    cd "${ENGINE}"
    _dl() {
      local id="$1" cli="$CACTUS_CLI"
      if [[ -n "${HF_TOKEN:-}" ]]; then
        "${cli}" download "$id" --precision "${PRECISION}" --token "${HF_TOKEN}"
      elif [[ -n "${HUGGING_FACE_HUB_TOKEN:-}" ]]; then
        "${cli}" download "$id" --precision "${PRECISION}" --token "${HUGGING_FACE_HUB_TOKEN}"
      else
        "${cli}" download "$id" --precision "${PRECISION}"
      fi
    }
    _dl "${CHAT_MODEL}"
    _dl "${ASR_MODEL}"
  )
else
  echo "Skipping downloads (--skip-models)."
fi

cat > "${APP_ROOT}/setup.env" <<EOF
# sys_setup.sh — app venv is separate from engine venv under third_party/cactus/venv
export CACTUS_PROJECT_ROOT="$(printf '%q' "${ENGINE}")"
EOF

APP_PY="${APP_ROOT}/.venv/bin/python"
echo ""
echo "App venv + requirements (embedded)..."
if [[ ! -d "${APP_ROOT}/.venv" ]]; then
  python3 -m venv "${APP_ROOT}/.venv"
fi
# shellcheck disable=SC1091
set -a
source "${APP_ROOT}/setup.env"
set +a
[[ -f "${APP_ROOT}/requirements.txt" ]] || {
  echo "ERROR: missing ${APP_ROOT}/requirements.txt"
  exit 1
}
"${APP_PY}" -m pip install --upgrade pip -q
"${APP_PY}" -m pip install -r "${APP_ROOT}/requirements.txt"

echo ""
echo "Done. Run the app:"
echo "  source ${APP_ROOT}/setup.env && source ${APP_ROOT}/.venv/bin/activate"
echo "  cd ${APP_ROOT} && uvicorn app.main:app --reload --host 0.0.0.0 --port 8765"
