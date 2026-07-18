#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
unit_source="$repo_root/systemd/system"
backup_root="/home/jenn/tools/colameta-systemd-backups"
backup_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$backup_root/$backup_stamp"

units=(
  colameta-private-beta.target
  colameta-stable.service
  colameta-mcp-remote.service
  cloudflared-colameta-mcp-prod.service
  colameta-local-healthcheck.service
  colameta-local-healthcheck.timer
  colameta-public-healthcheck.service
  colameta-public-healthcheck.timer
  colameta-stack-recover.service
)

sudo install -d -m 0750 -o jenn -g jenn "$backup_root" "$backup_dir"
for unit in "${units[@]}"; do
  if [[ -e "/etc/systemd/system/$unit" ]]; then
    sudo cp --preserve=mode,timestamps "/etc/systemd/system/$unit" "$backup_dir/$unit"
    sudo chown jenn:jenn "$backup_dir/$unit"
  fi
  sudo install -m 0644 -o root -g root "$unit_source/$unit" "/etc/systemd/system/$unit"
done

sudo install -d -m 0755 -o root -g root /etc/systemd/journald@colameta.conf.d
sudo install -m 0644 -o root -g root \
  "$unit_source/journald-colameta.conf" \
  /etc/systemd/journald@colameta.conf.d/limits.conf

sudo systemctl daemon-reload
sudo systemctl disable \
  colameta-stable.service \
  colameta-mcp-remote.service \
  cloudflared-colameta-mcp-prod.service \
  colameta-local-healthcheck.timer \
  colameta-public-healthcheck.timer \
  >/dev/null 2>&1 || true
sudo systemctl enable colameta-private-beta.target

printf 'Installed ColaMeta private Beta systemd stack.\n'
printf 'Backup directory: %s\n' "$backup_dir"
printf 'Activate with: sudo systemctl start colameta-private-beta.target\n'
