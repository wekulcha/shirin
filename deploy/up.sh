#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

gateway_mode="auto"
case "${1:-}" in
  --cloud) gateway_mode="cloud" ;;
  --shared) gateway_mode="shared" ;;
  "") ;;
  -h|--help)
    echo "Usage: ./deploy/up.sh [--shared|--cloud]"
    echo "Default: shared gateway; SHIRIN_SHARED_GATEWAY=false selects the dedicated VM gateway."
    exit 0
    ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
if (( $# > 1 )); then
  echo "Usage: ./deploy/up.sh [--shared|--cloud]" >&2
  exit 2
fi

if [[ ! -f .env ]]; then
  template=".env.example"
  if [[ "$gateway_mode" == "cloud" ]]; then
    template="deploy/yandex-cloud.env.example"
  fi
  cp "$template" .env
  chmod 600 .env
  echo "Created .env from $template."
  echo "Fill the database credentials, three bot tokens and URLs, then run this script again."
  exit 1
fi

# Read specific values without sourcing .env as executable shell code.
read_env_value() {
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

# Services receive their tokens from env_file: .env, not the caller's shell.
# Check all three before changing containers or applying database migrations.
bot_token_names=(SHIRIN_USER_BOT_TOKEN SHIRIN_ADMIN_BOT_TOKEN SHIRIN_SUPERADMIN_BOT_TOKEN)
bot_tokens=()
for name in "${bot_token_names[@]}"; do
  token="$(read_env_value "$name")"
  if [[ -z "${token//[[:space:]]/}" ]]; then
    echo "Set a nonempty $name in .env before starting Shirin." >&2
    exit 1
  fi
  bot_tokens+=("$token")
done
for (( first = 0; first < ${#bot_tokens[@]}; first++ )); do
  for (( second = first + 1; second < ${#bot_tokens[@]}; second++ )); do
    if [[ "${bot_tokens[$first]}" == "${bot_tokens[$second]}" ]]; then
      echo "${bot_token_names[$first]} and ${bot_token_names[$second]} must contain different bot tokens in .env." >&2
      exit 1
    fi
  done
done
unset token bot_tokens

shared_gateway="${SHIRIN_SHARED_GATEWAY:-$(read_env_value SHIRIN_SHARED_GATEWAY)}"
shared_gateway="$(printf '%s' "${shared_gateway:-true}" | tr '[:upper:]' '[:lower:]')"
if [[ "$gateway_mode" == "auto" ]]; then
  case "$shared_gateway" in
    1|true|yes) gateway_mode="shared" ;;
    0|false|no) gateway_mode="cloud" ;;
    *) echo "SHIRIN_SHARED_GATEWAY must be true or false." >&2; exit 1 ;;
  esac
fi

compose=(docker compose -f docker-compose.yml)
app_services=(backend worker user_panel admin_panel superadmin_panel user_bot admin_bot superadmin_bot)
if [[ "$gateway_mode" == "cloud" ]]; then
  compose+=(-f deploy/docker-compose.cloud.yml)
  app_services+=(gateway)
  echo "Starting Shirin with its own gateway on ports 80 and 443."
else
  echo "Starting Shirin behind the existing shared gateway."
  echo "Keep the /shirin routes from deploy/Caddyfile.routes.example in that gateway."
fi

"${compose[@]}" config -q

# Network attachment is opt-in; never select or change another application's
# gateway implicitly. Fail before deployment if the requested container is absent.
shared_container=""
if [[ "$gateway_mode" == "shared" ]]; then
  shared_container="${SHIRIN_SHARED_GATEWAY_CONTAINER:-$(read_env_value SHIRIN_SHARED_GATEWAY_CONTAINER)}"
  if [[ -n "$shared_container" ]]; then
    if ! docker inspect --format '{{.Id}}' "$shared_container" >/dev/null 2>&1; then
      echo "Shared gateway container '$shared_container' was not found." >&2
      echo "Set SHIRIN_SHARED_GATEWAY_CONTAINER to the existing gateway name, or leave it empty." >&2
      exit 1
    fi
  fi
fi

# Remove the retired single 'bot' service before starting the three pollers.
# Project name is 'shirin'; Market and Kulcha containers are outside this project.
"${compose[@]}" up -d --build --wait --remove-orphans postgres

echo "Applying Shirin database migrations..."
"${compose[@]}" up --no-deps --build --exit-code-from migrate migrate

# PostgreSQL and migrations are ready. Start every application service together.
"${compose[@]}" up -d --build --no-deps "${app_services[@]}"

gateway_network="${SHIRIN_GATEWAY_NETWORK:-$(read_env_value SHIRIN_GATEWAY_NETWORK)}"
gateway_network="${gateway_network:-shirin_gateway}"
if [[ -n "$shared_container" ]]; then
  attached="false"
  while IFS= read -r network; do
    if [[ "$network" == "$gateway_network" ]]; then
      attached="true"
      break
    fi
  done < <(docker inspect --format '{{range $name, $network := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$shared_container")
  if [[ "$attached" != "true" ]]; then
    docker network connect "$gateway_network" "$shared_container"
  fi
  echo "Shared gateway '$shared_container' is connected to '$gateway_network'."
elif [[ "$gateway_mode" == "shared" ]]; then
  echo "Mini App publication requires connecting the public gateway to '$gateway_network'."
  echo "Set SHIRIN_SHARED_GATEWAY_CONTAINER to that container name in .env, or connect it manually."
fi

"${compose[@]}" ps
if [[ "$gateway_mode" == "shared" ]]; then
  echo "Apply deploy/Caddyfile.routes.example to the public gateway; ./up.sh does not edit its Caddyfile."
  echo "Verify /shirin/api/health on both panel domains: it must return Shirin JSON, not Market HTML."
fi
