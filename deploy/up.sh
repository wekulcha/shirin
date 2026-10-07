#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

gateway_mode="auto"
build_images="true"
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
    --no-build) build_images="false" ;;
    --compact) compact_workers="true" ;;
    -h|--help)
      echo "Usage: ./up.sh [--shared|--cloud] [--compact] [--no-build]"
      echo "Default: build four application images sequentially, then migrate and start."
      echo "--no-build reuses local images without building or pulling; all images must exist."
      echo "Changes from git pull are NOT included until images are rebuilt."
      echo "--compact runs three bots and notifications in one background process."
      echo "Set SHIRIN_COMPACT_WORKERS=true in .env to keep compact mode on future runs."
      echo "Default gateway: shared; SHIRIN_SHARED_GATEWAY=false selects the dedicated VM gateway."
      exit 0
      ;;
    *) echo "Unknown option: $option" >&2; exit 2 ;;
  esac
done

# Keep Compose operations serial on small VMs. These control scheduling only,
# not the memory used by a Docker build or a running application.
export COMPOSE_PARALLEL_LIMIT=1
export COMPOSE_BAKE=false

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

if [[ "$compact_workers" == "auto" ]]; then
  compact_workers="${SHIRIN_COMPACT_WORKERS:-$(read_env_value SHIRIN_COMPACT_WORKERS)}"
  compact_workers="$(printf '%s' "${compact_workers:-false}" | tr '[:upper:]' '[:lower:]')"
fi
case "$compact_workers" in
  1|true|yes) compact_workers="true" ;;
  0|false|no) compact_workers="false" ;;
  *) echo "SHIRIN_COMPACT_WORKERS must be true or false." >&2; exit 1 ;;
esac

compose=(docker compose -f docker-compose.yml)
compose_project="${COMPOSE_PROJECT_NAME:-$(read_env_value COMPOSE_PROJECT_NAME)}"
compose_project="${compose_project:-shirin}"
app_services=(backend user_panel admin_panel superadmin_panel)
obsolete_services=(workers bot)
if [[ "$compact_workers" == "true" ]]; then
  compose+=(-f deploy/docker-compose.compact.yml)
  app_services+=(workers)
  obsolete_services=(worker user_bot admin_bot superadmin_bot bot)
  echo "Using one background process for Shirin's three bots and notifications."
else
  app_services+=(worker user_bot admin_bot superadmin_bot)
fi
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

# Build before changing running containers or applying migrations. All Python
# services use the image produced by backend; build it only once.
if [[ "$build_images" == "true" ]]; then
  # Acquire only stock runtime images here. Application images are local builds;
  # never let `up` try pulling their :latest tags from a registry.
  stock_services=(postgres)
  if [[ "$gateway_mode" == "cloud" ]]; then
    stock_services+=(gateway)
  fi
  "${compose[@]}" pull --policy missing "${stock_services[@]}"
  for service in backend user_panel admin_panel superadmin_panel; do
    echo "Building Shirin $service..."
    "${compose[@]}" build "$service"
  done
else
  echo "Reusing existing images; changes from git pull are not included without a rebuild."
  images="$("${compose[@]}" config --images)"
  missing_images=()
  while IFS= read -r image; do
    [[ -n "$image" ]] || continue
    if ! docker image inspect "$image" >/dev/null 2>&1; then
      missing_images+=("$image")
    fi
  done < <(printf '%s\n' "$images" | sort -u)
  if (( ${#missing_images[@]} )); then
    printf 'Missing local image: %s\n' "${missing_images[@]}" >&2
    echo "Run ./up.sh without --no-build to build missing application images, or load prebuilt images first." >&2
    echo "No containers or database migrations were started." >&2
    exit 1
  fi
  if [[ "$compact_workers" == "true" ]]; then
    # Compose includes backend's dependencies here (migrate and PostgreSQL),
    # rather than returning only one image. The Shirin backend image carries
    # this capability label; the stock PostgreSQL image does not.
    backend_images="$("${compose[@]}" config --images backend)"
    supports_compact="false"
    while IFS= read -r image; do
      [[ -n "$image" ]] || continue
      capability="$(docker image inspect --format '{{ index .Config.Labels "org.wekulcha.shirin.compact-workers" }}' "$image")"
      if [[ "$capability" == "1" ]]; then
        supports_compact="true"
      fi
    done < <(printf '%s\n' "$backend_images" | sort -u)
    if [[ "$supports_compact" != "true" ]]; then
      echo "The local backend image does not support compact workers yet." >&2
      echo "Run ./up.sh --compact without --no-build once to build the updated code." >&2
      echo "No containers or database migrations were started." >&2
      exit 1
    fi
  fi
fi

# Keep existing workers intact until both builds and migrations succeed.
"${compose[@]}" up -d --no-build --pull never --wait postgres

echo "Applying Shirin database migrations..."
"${compose[@]}" up --no-deps --no-build --pull never --exit-code-from migrate migrate

# Switch background modes without running two pollers for the same bot token.
# Both labels must match; never stop another project's similarly named service.
for service in "${obsolete_services[@]}"; do
  containers="$(docker ps -aq --filter "label=com.docker.compose.project=$compose_project" --filter "label=com.docker.compose.service=$service")"
  while IFS= read -r container; do
    [[ -n "$container" ]] || continue
    docker stop "$container"
    docker rm "$container"
  done <<< "$containers"
done

# PostgreSQL and migrations are ready. Start every application service together.
# Any remaining project orphans are removed only now.
"${compose[@]}" up -d --no-build --pull never --no-deps --remove-orphans "${app_services[@]}"

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
