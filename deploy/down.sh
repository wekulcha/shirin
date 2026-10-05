#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

case "${1:-}" in
  ""|--shared) compose=(docker compose -f docker-compose.yml) ;;
  --cloud) compose=(docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml) ;;
  -h|--help)
    echo "Usage: ./deploy/down.sh [--shared|--cloud]"
    echo "Stops only Shirin. Database and uploaded media volumes are retained."
    exit 0
    ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
if (( $# > 1 )); then
  echo "Usage: ./deploy/down.sh [--shared|--cloud]" >&2
  exit 2
fi

# --remove-orphans also removes a Shirin gateway started with --cloud, even when
# this invocation uses the default file. No volumes are deleted.
"${compose[@]}" down --remove-orphans
