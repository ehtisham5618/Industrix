#!/bin/sh
# EAP-5 watchdog setup and launcher for Linux (POSIX sh). Idempotent; offline at runtime.
#   sh EAP_5_Watchdog/scripts/setup_watchdog.sh [check|validate|run|start|status|stop]
# Environment: PYTHON=/path/to/python  CONFIG=/path/to/watchdog.json  INSTALL=1  ALLOW_GLOBAL_INSTALL=1
set -eu
ACTION="${1:-validate}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

fail() {
  printf 'SETUP FAILED: %s\n' "$1" >&2
  if [ -n "${2:-}" ]; then printf '  Fix: %s\n' "$2" >&2; fi
  exit 1
}

case "$ACTION" in
  check|validate|run|start|status|stop) ;;
  *) fail "unknown action: $ACTION" "use check|validate|run|start|status|stop" ;;
esac
case "$(uname -s)" in
  Linux) ;;
  *) printf 'WARNING: %s is not the validated Linux target; continuing\n' "$(uname -s)" >&2 ;;
esac

# 1. Interpreter: $PYTHON > active venv > python3 > python. Never creates or modifies a global environment.
if [ -z "${PYTHON:-}" ]; then
  if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PYTHON="$VIRTUAL_ENV/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON="$(command -v python)"
  else
    fail "no Python interpreter found" "set PYTHON=/path/to/python"
  fi
fi
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "Python 3.11+ required" "set PYTHON to a newer interpreter"
IN_VENV="$("$PYTHON" -c 'import sys; print(sys.prefix != sys.base_prefix)')"
printf 'Python: %s (venv=%s)\n' "$PYTHON" "$IN_VENV"

# 2. Watchdog dependencies. Install only on request; never silently into a global interpreter.
if ! "$PYTHON" -c 'import pydantic, psutil' 2>/dev/null; then
  [ "${INSTALL:-0}" = "1" ] || fail "watchdog dependencies missing (pydantic, psutil)" "rerun with INSTALL=1 inside a virtual environment"
  if [ "$IN_VENV" != "True" ] && [ "${ALLOW_GLOBAL_INSTALL:-0}" != "1" ]; then
    fail "refusing to install into a non-virtual-environment interpreter" "activate a venv, or set ALLOW_GLOBAL_INSTALL=1"
  fi
  "$PYTHON" -m pip install -r "$ROOT/EAP_5_Watchdog/requirements.txt" || fail "pip install failed" "check the local package index"
fi
printf 'Watchdog dependencies: OK\n'

# 3. Service dependencies are reported, not installed.
"$PYTHON" -c 'import uvicorn, fastapi, ultralytics' 2>/dev/null \
  || printf 'WARNING: backend dependencies missing (see requirements.txt)\n' >&2
"$PYTHON" -c 'import streamlit' 2>/dev/null \
  || printf 'WARNING: dashboard dependencies missing (see Frontend/requirements.txt)\n' >&2
if [ "$ACTION" = "check" ]; then printf 'CHECK OK\n'; exit 0; fi

# 4. Validate configuration (executables, working directories, local model file + checksum; no downloads).
cd "$ROOT"
if [ -n "${CONFIG:-}" ]; then set -- --config "$CONFIG"; else set --; fi
"$PYTHON" -m EAP_5_Watchdog validate "$@" || fail "configuration validation failed" "see PROBLEM lines above"
if [ "$ACTION" = "validate" ]; then exit 0; fi
exec "$PYTHON" -m EAP_5_Watchdog "$ACTION" "$@"
