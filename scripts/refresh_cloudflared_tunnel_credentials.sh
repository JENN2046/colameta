#!/usr/bin/env bash
set -euo pipefail
set +x

umask 077

cloudflared_bin="/home/jenn/.local/bin/cloudflared"
config_file="/home/jenn/.config/colameta/cloudflared/colameta-mcp-prod.yml"
credentials_dir_expected="/home/jenn/.cloudflared"
tunnel_name="colameta-mcp-prod"
service_name="cloudflared-colameta-mcp-prod.service"
ready_url="http://127.0.0.1:20241/ready"
public_base_url="https://colameta-mcp.skmt617.top"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$repo_root/.venv/bin/python"
preflight_script="$repo_root/scripts/remote_https_mcp_preflight.py"

refresh_dir=""
fresh_credentials=""
rollback_credentials=""
service_stopped="no"
credential_state="original"

fail() {
  printf 'credential_refresh=%s\n' "$1"
  exit 1
}

rollback_applied_credentials() {
  [[ "$credential_state" == "applied_unvalidated" ]] || return 0
  service_stopped="yes"
  if ! sudo systemctl stop "$service_name"; then
    return 1
  fi
  rollback_credentials="$refresh_dir/rollback.json"
  if ! cp --preserve=mode,timestamps "$backup_credentials" "$rollback_credentials"; then
    return 1
  fi
  if ! chmod 0600 "$rollback_credentials"; then
    return 1
  fi
  if ! mv -- "$rollback_credentials" "$credentials_file"; then
    return 1
  fi
  rollback_credentials=""
  credential_state="original"
  if ! sudo systemctl start "$service_name"; then
    return 1
  fi
  service_stopped="no"
}

cleanup() {
  exit_status=$?
  trap - EXIT
  trap '' HUP INT TERM
  set +e
  if [[ "$credential_state" == "applied_unvalidated" ]]; then
    if ! rollback_applied_credentials >/dev/null 2>&1; then
      printf 'credential_refresh_cleanup=rollback_failed\n'
    fi
  fi
  if [[ -n "$fresh_credentials" && -f "$fresh_credentials" ]]; then
    rm -f -- "$fresh_credentials"
  fi
  if [[ -n "$rollback_credentials" && -f "$rollback_credentials" ]]; then
    rm -f -- "$rollback_credentials"
  fi
  if [[ -n "$refresh_dir" && -d "$refresh_dir" ]]; then
    rmdir -- "$refresh_dir" 2>/dev/null || true
  fi
  if [[
    "$service_stopped" == "yes" &&
      "$credential_state" != "applied_unvalidated"
  ]]; then
    sudo systemctl start "$service_name" >/dev/null 2>&1 || true
  fi
  exit "$exit_status"
}

trap cleanup EXIT
trap 'exit 130' HUP INT TERM

[[ "$(id -un)" == "jenn" ]] || fail "wrong_user"
[[ -x "$cloudflared_bin" ]] || fail "cloudflared_missing"
[[ -f "$config_file" && ! -L "$config_file" ]] || fail "config_unavailable"
[[ -x "$python_bin" ]] || fail "python_missing"
[[ -f "$preflight_script" && ! -L "$preflight_script" ]] ||
  fail "preflight_missing"

for required_command in awk basename chmod cp curl date dirname mktemp mv rmdir sleep sudo tr; do
  command -v "$required_command" >/dev/null 2>&1 ||
    fail "required_command_missing"
done

credentials_file="$(
  awk '$1 == "credentials-file:" {print $2; exit}' "$config_file" |
    tr -d "\"'"
)"
[[ -n "$credentials_file" ]] || fail "credentials_path_missing"

credentials_dir="$(dirname -- "$credentials_file")"
credentials_name="$(basename -- "$credentials_file")"

[[ "$credentials_dir" == "$credentials_dir_expected" ]] ||
  fail "credentials_path_outside_boundary"
[[ "$credentials_name" == *.json ]] || fail "credentials_filename_invalid"
[[ -f "$credentials_file" && ! -L "$credentials_file" ]] ||
  fail "credentials_file_unavailable"

sudo -v

refresh_dir="$(mktemp -d "$credentials_dir/.colameta-mcp-prod-refresh.XXXXXX")"
chmod 0700 "$refresh_dir"
fresh_credentials="$refresh_dir/credentials.json"

printf 'credential_refresh_phase=fetch\n'
if ! "$cloudflared_bin" tunnel token \
  --cred-file "$fresh_credentials" \
  "$tunnel_name" \
  >/dev/null 2>&1; then
  fail "fetch_failed"
fi

[[ -f "$fresh_credentials" && ! -L "$fresh_credentials" ]] ||
  fail "fresh_credentials_unavailable"
[[ -s "$fresh_credentials" ]] || fail "fresh_credentials_empty"
chmod 0600 "$fresh_credentials"

backup_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_credentials="${credentials_file}.backup-${backup_stamp}"
[[ ! -e "$backup_credentials" ]] || fail "backup_already_exists"
cp --preserve=mode,timestamps "$credentials_file" "$backup_credentials"
chmod 0600 "$backup_credentials"
printf 'credentials_backup=retained\n'

service_stopped="yes"
if ! sudo systemctl stop "$service_name"; then
  fail "service_stop_failed"
fi

credential_state="applied_unvalidated"
if ! mv -- "$fresh_credentials" "$credentials_file"; then
  fail "atomic_replace_failed"
fi
fresh_credentials=""

if ! sudo systemctl start "$service_name"; then
  if ! rollback_applied_credentials; then
    fail "service_start_failed_rollback_restart_failed"
  fi
  fail "service_start_failed_rolled_back"
fi
service_stopped="no"

ready_http="000"
for _attempt in {1..30}; do
  ready_http="$(
    curl -s --max-time 1 \
      -o /dev/null \
      -w '%{http_code}' \
      "$ready_url" ||
      true
  )"
  [[ "$ready_http" == "200" ]] && break
  sleep 1
done

service_active="no"
if sudo systemctl is-active --quiet "$service_name"; then
  service_active="yes"
fi
printf 'service_active=%s\n' "$service_active"
printf 'tunnel_ready_http=%s\n' "$ready_http"

if [[ "$ready_http" != "200" ]]; then
  if ! rollback_applied_credentials; then
    fail "applied_not_ready_rollback_restart_failed"
  fi
  fail "applied_not_ready"
fi

if [[ "$service_active" != "yes" ]]; then
  if ! rollback_applied_credentials; then
    fail "applied_service_inactive_rollback_restart_failed"
  fi
  fail "applied_service_inactive"
fi

if ! "$python_bin" "$preflight_script" "$public_base_url"; then
  printf 'public_preflight=fail\n'
  if ! rollback_applied_credentials; then
    fail "applied_public_preflight_failed_rollback_restart_failed"
  fi
  fail "applied_public_preflight_failed"
fi

if ! sudo systemctl is-active --quiet "$service_name"; then
  if ! rollback_applied_credentials; then
    fail "applied_service_inactive_after_preflight_rollback_restart_failed"
  fi
  fail "applied_service_inactive_after_preflight"
fi

printf 'public_preflight=pass\n'
credential_state="validated"
printf 'credential_refresh=ok\n'
