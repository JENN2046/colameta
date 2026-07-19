# ColaMeta Private Beta systemd Operations

The private Beta stack uses system-level units because the WSL instance does
not provide a persistent per-user systemd manager. The stack has one ownership
boundary:

- `colameta-stable.service`: local Web on `127.0.0.1:8801` and the focused
  seven-tool Commander MCP on `127.0.0.1:8766`;
- `colameta-mcp-remote.service`: external-OAuth MCP origin on
  `127.0.0.1:8767`, also using the seven-tool Commander profile;
- `colameta-mcp-advanced.service`: loopback-only advanced MCP on
  `127.0.0.1:8768`, retaining the complete 82-tool normal profile;
- `cloudflared-colameta-mcp-prod.service`: public tunnel, ordered after the
  OAuth origin without stop propagation during an origin restart;
- `colameta-tunnel-client.service`: managed tunnel used by the existing
  ChatGPT Apps connector, ordered after the local MCP service;
- `colameta-local-healthcheck.timer`: one-minute local endpoint checks with a
  rate-limited stack recovery on failure;
- `colameta-public-healthcheck.timer`: five-minute public HTTPS checks that
  report failures without restarting the stack for transient internet errors;
  and
- `colameta-managed-tunnel-healthcheck.timer`: five-minute managed-tunnel
  health and control-plane readiness checks that report without restarting the
  healthy local or public stack.

All long-running services use `Restart=always`, bounded start limits, explicit
stop signals and 30-second stop timeouts. They log to the `colameta` journal
namespace. The namespace keeps at most 256 MiB persistently, rotates files at
32 MiB or one day, compresses archived journals, and retains at most 14 days.

The target uses `Wants=` rather than `Requires=` for its long-running services.
This is intentional: an individual process failure must not deactivate the
target or stop healthy siblings while `Restart=always` is recovering that
process. `PartOf=colameta-private-beta.target` still propagates an explicit
operator stop or restart of the target to the whole stack.

## Install

```bash
./scripts/install_private_beta_systemd.sh
sudo systemd-analyze verify /etc/systemd/system/colameta-*.service \
  /etc/systemd/system/colameta-*.timer \
  /etc/systemd/system/colameta-private-beta.target \
  /etc/systemd/system/cloudflared-colameta-mcp-prod.service
sudo systemctl start colameta-private-beta.target
```

The installer backs up replaced unit files below
`/home/jenn/tools/colameta-systemd-backups/` and does not start or stop the
stack. It disables child-unit boot symlinks and enables only
`colameta-private-beta.target`, so the target remains the single startup
owner. Stop any manually launched processes on ports 8801, 8766, 8767 and 8768
before the first activation.

## Operate

```bash
sudo systemctl status colameta-private-beta.target
sudo systemctl restart colameta-private-beta.target
sudo systemctl stop colameta-private-beta.target
sudo systemctl list-timers 'colameta-*'
sudo journalctl --namespace=colameta -u colameta-stable.service
sudo journalctl --namespace=colameta -u colameta-mcp-remote.service
sudo journalctl --namespace=colameta -u colameta-mcp-advanced.service
sudo journalctl --namespace=colameta -u cloudflared-colameta-mcp-prod.service
sudo journalctl --namespace=colameta -u colameta-tunnel-client.service
```

`systemctl stop colameta-private-beta.target` propagates a graceful stop to all
five long-running services. Explicitly stopping the target does not trigger
`Restart=always`; systemd restarts a service only when its process exits while
the unit is expected to remain active.

The managed tunnel writes its own bounded diagnostic file at
`/home/jenn/.local/state/colameta/tunnel-client.log`. The installer adds a
daily/10 MiB logrotate policy with 14 compressed rotations. It never prints or
copies the tunnel profile, API key, or connector credentials.

## Verify

```bash
curl --fail http://127.0.0.1:8801/
curl --fail http://127.0.0.1:8766/mcp
curl --fail http://127.0.0.1:8767/healthz
curl --fail http://127.0.0.1:8768/mcp
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/readyz
/home/jenn/tools/colameta/.venv/bin/python \
  /home/jenn/tools/colameta/scripts/remote_https_mcp_preflight.py \
  https://colameta-mcp.skmt617.top \
  --expected-head "$(git -C /home/jenn/src/colameta-dev rev-parse HEAD)"
```

The default connector and public OAuth endpoint expose these seven high-level
tools: `list_registered_projects`, `get_apps_connector_smoke_packet`,
`render_commander_app`, `analyze_project_state`, `run_mcp_workflow`,
`manage_validation_run`, and `manage_git`. The connector smoke packet is
read-only (`mcp:read`); it does not authorize executor runs, Git writes, or
stable replacement. Calls to any hidden tool are rejected by the active
exposure profile, including calls made from a stale connector cache. Operators
who need the complete 82-tool catalog can connect a local advanced client to
`http://127.0.0.1:8768/mcp`; that endpoint is not bound to a public interface or
forwarded by either tunnel.

For a controlled restart test, record the current `MainPID`, send `SIGTERM` to
that exact service PID, and verify that systemd assigns a different running
`MainPID`. Do not kill by process-name pattern.

## ChatGPT Apps connector smoke
After the local and public health checks pass, call `list_registered_projects` through the existing ChatGPT Apps connector and confirm it includes `colameta-self-dev`. Then call `analyze_project_state(project_name="colameta-self-dev")` and confirm the returned Git HEAD matches the deployed checkout. If the Apps call reports an internal tunnel 404 while ports 8766 and 8080 are healthy, check `colameta-tunnel-client.service`; do not read tokens, cookies, connector configuration, or raw logs.


## Roll back

Stop and disable the target, copy the newest backed-up units from
`/home/jenn/tools/colameta-systemd-backups/<timestamp>/` into
`/etc/systemd/system/`, remove only newly introduced ColaMeta units, then run
`sudo systemctl daemon-reload`. Restore
`logrotate-colameta-tunnel-client` from the same backup directory to
`/etc/logrotate.d/colameta-tunnel-client`, or remove the installed logrotate
file when the backup is absent. The stable source/package backup remains
separate from systemd configuration backups.
