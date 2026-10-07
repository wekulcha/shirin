#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

gateway_mode="auto"
compact_workers="auto"
for option in "$@"; do
  case "$option" in
    --cloud|--shared)
      if [[ "$gateway_mode" != "auto" ]]; then
        echo "Choose only one of --shared or --cloud." >&2
        exit 2
      fi
      gateway_mode="${option#--}"
      ;;
    --compact) compact_workers="true" ;;
    -h|--help)
      echo "Usage: ./down.sh [--shared|--cloud] [--compact]"
      echo "Defaults follow SHIRIN_SHARED_GATEWAY and SHIRIN_COMPACT_WORKERS in .env."
      echo "Stops only Shirin, including containers from the previous worker mode."
      echo "Database and uploaded media volumes are retained."
      exit 0
      ;;
    *) echo "Unknown option: $option" >&2; exit 2 ;;
  esac
done

# Read flags without executing the user's .env as shell code.
read_env_value() {
  [[ -f .env ]] || return 0
  awk -F= -v key="$1" '
    {
      field = $1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", field)
    }
    field == key {
      value = substr($0, index($0, "=") + 1)
      sub(/[[:space:]]*#.*/, "", value)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      gsub(/^["\047]|["\047]$/, "", value)
      print value
    }
  ' .env | tail -n 1
}

if [[ "$gateway_mode" == "auto" ]]; then
  shared_gateway="${SHIRIN_SHARED_GATEWAY:-$(read_env_value SHIRIN_SHARED_GATEWAY)}"
  shared_gateway="$(printf '%s' "${shared_gateway:-true}" | tr '[:upper:]' '[:lower:]')"
  case "$shared_gateway" in
    1|true|yes) gateway_mode="shared" ;;
    0|false|no) gateway_mode="cloud" ;;
    *) echo "SHIRIN_SHARED_GATEWAY must be true or false." >&2; exit 1 ;;
  esac
fi
if [[ "$compact_workers" == "auto" ]]; then
  compact_workers="${SHIRIN_COMPACT_WORKERS:-$(read_env_value SHIRIN_COMPACT_WORKERS)}"
  compact_workers="$(printf '%s' "${compact_workers:-false}" | tr '[:upper:]' '[:lower:]')"
fi

# Include inactive profiles as well, so a previous separate worker mode is
# stopped even when the current .env selects compact mode. Never delete volumes.
compose=(docker compose -f docker-compose.yml --profile '*')
case "$compact_workers" in
  1|true|yes) compose+=(-f deploy/docker-compose.compact.yml) ;;
  0|false|no) ;;
  *) echo "SHIRIN_COMPACT_WORKERS must be true or false." >&2; exit 1 ;;
esac
if [[ "$gateway_mode" == "cloud" ]]; then
  compose+=(-f deploy/docker-compose.cloud.yml)
fi

# Orphans cover a compact worker or gateway started using an earlier selection.
"${compose[@]}" down --remove-orphans
