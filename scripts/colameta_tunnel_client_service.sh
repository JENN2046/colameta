#!/usr/bin/env bash
set -euo pipefail

# Keep secrets out of xtrace output even if the caller enables bash -x.
set +x

MODE="${1:-start}"

PROJECT_ROOT="${COLAMETA_PROJECT_ROOT:-/home/jenn/src/colameta-dev}"
TUNNEL_CLIENT_BIN="${TUNNEL_CLIENT_BIN:-/home/jenn/tools/tunnel-client/bin/tunnel-client}"
TUNNEL_CLIENT_PROFILE="${TUNNEL_CLIENT_PROFILE:-colameta-sandbox}"
TUNNEL_HEALTH_LISTEN_ADDR="${TUNNEL_HEALTH_LISTEN_ADDR:-127.0.0.1:8080}"
TUNNEL_CLIENT_ENV_FILE="${TUNNEL_CLIENT_ENV_FILE:-$PROJECT_ROOT/.env.local}"
TUNNEL_CLIENT_STATE_DIR="${TUNNEL_CLIENT_STATE_DIR:-$HOME/.local/state/colameta}"
TUNNEL_CLIENT_PID_FILE="${TUNNEL_CLIENT_PID_FILE:-$TUNNEL_CLIENT_STATE_DIR/tunnel-client.pid}"
TUNNEL_CLIENT_HEALTH_URL_FILE="${TUNNEL_CLIENT_HEALTH_URL_FILE:-$TUNNEL_CLIENT_STATE_DIR/tunnel-client-health.url}"
TUNNEL_CLIENT_LOG_FILE="${TUNNEL_CLIENT_LOG_FILE:-$TUNNEL_CLIENT_STATE_DIR/tunnel-client.log}"
TUNNEL_CLIENT_LOG_LEVEL="${TUNNEL_CLIENT_LOG_LEVEL:-info}"

usage() {
  cat <<'USAGE'
Usage: colameta_tunnel_client_service.sh [check|start|health]

Modes:
  check   Validate executable/profile/key presence without printing secrets.
  start   Run tunnel-client for systemd --user.
  health  Emit tunnel-client health JSON from the loopback admin endpoint.
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 78
}

strip_quotes() {
  local value="$1"
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

load_env_key() {
  local name="$1"
  local file="$2"
  local line value

  [[ -f "$file" ]] || return 0
  line="$(grep -m 1 -E "^[[:space:]]*${name}=" "$file" 2>/dev/null || true)"
  [[ -n "$line" ]] || return 0

  value="${line#*=}"
  value="${value%%#*}"
  value="${value%"${value##*[![:space:]]}"}"
  value="$(strip_quotes "$value")"

  if [[ -n "$value" ]]; then
    export "$name=$value"
  fi
}

load_control_plane_key() {
  if [[ -f "$TUNNEL_CLIENT_ENV_FILE" ]]; then
    load_env_key CONTROL_PLANE_API_KEY "$TUNNEL_CLIENT_ENV_FILE"
    load_env_key OPENAI_API_KEY "$TUNNEL_CLIENT_ENV_FILE"
  fi

  if [[ -z "${CONTROL_PLANE_API_KEY:-}" && -n "${OPENAI_API_KEY:-}" ]]; then
    export CONTROL_PLANE_API_KEY="$OPENAI_API_KEY"
  fi

  [[ -n "${CONTROL_PLANE_API_KEY:-}" ]] || die "CONTROL_PLANE_API_KEY or OPENAI_API_KEY is required in the environment or env file."
}

health_port() {
  local addr="$TUNNEL_HEALTH_LISTEN_ADDR"
  printf '%s' "${addr##*:}"
}

check_profile() {
  "$TUNNEL_CLIENT_BIN" profiles list --json | grep -q "\"name\": \"$TUNNEL_CLIENT_PROFILE\""
}

check_mode() {
  [[ -x "$TUNNEL_CLIENT_BIN" ]] || die "tunnel-client is not executable: $TUNNEL_CLIENT_BIN"
  [[ -d "$PROJECT_ROOT" ]] || die "project root is missing: $PROJECT_ROOT"
  check_profile || die "tunnel-client profile is not listed: $TUNNEL_CLIENT_PROFILE"
  load_control_plane_key
  mkdir -p "$TUNNEL_CLIENT_STATE_DIR"

  printf 'tunnel_client_bin=ok\n'
  printf 'project_root=ok\n'
  printf 'profile=ok:%s\n' "$TUNNEL_CLIENT_PROFILE"
  printf 'key=present\n'
  printf 'health_listen_addr=%s\n' "$TUNNEL_HEALTH_LISTEN_ADDR"
  printf 'state_dir=%s\n' "$TUNNEL_CLIENT_STATE_DIR"
}

start_mode() {
  [[ -x "$TUNNEL_CLIENT_BIN" ]] || die "tunnel-client is not executable: $TUNNEL_CLIENT_BIN"
  [[ -d "$PROJECT_ROOT" ]] || die "project root is missing: $PROJECT_ROOT"
  load_control_plane_key
  mkdir -p "$TUNNEL_CLIENT_STATE_DIR"

  exec "$TUNNEL_CLIENT_BIN" run \
    --profile "$TUNNEL_CLIENT_PROFILE" \
    --health.listen-addr "$TUNNEL_HEALTH_LISTEN_ADDR" \
    --health.url-file "$TUNNEL_CLIENT_HEALTH_URL_FILE" \
    --pid.file "$TUNNEL_CLIENT_PID_FILE" \
    --log.file "$TUNNEL_CLIENT_LOG_FILE" \
    --log.level "$TUNNEL_CLIENT_LOG_LEVEL"
}

health_mode() {
  local port pid_arg=() pids
  port="$(health_port)"

  if [[ -s "$TUNNEL_CLIENT_PID_FILE" ]]; then
    pid_arg=(--pid "$(sed -n '1p' "$TUNNEL_CLIENT_PID_FILE")")
  else
    pids="$(pgrep -x tunnel-client || true)"
    if [[ "$(printf '%s\n' "$pids" | sed '/^$/d' | wc -l)" -eq 1 ]]; then
      pid_arg=(--pid "$pids")
    fi
  fi

  exec "$TUNNEL_CLIENT_BIN" health --port "$port" "${pid_arg[@]}" --json
}

case "$MODE" in
  check)
    check_mode
    ;;
  start)
    start_mode
    ;;
  health)
    health_mode
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 64
    ;;
esac
