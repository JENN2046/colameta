# ColaMeta Private Beta systemd Operations

The private Beta stack uses system-level units because the WSL instance does
not provide a persistent per-user systemd manager. The stack has one ownership
boundary:

- `colameta-stable.service`: local Web on `127.0.0.1:8801` and local MCP on
  `127.0.0.1:8766`;
- `colameta-mcp-remote.service`: external-OAuth MCP origin on
  `127.0.0.1:8767`;
- `cloudflared-colameta-mcp-prod.service`: public tunnel, ordered after the
  OAuth origin without stop propagation during an origin restart;
- `colameta-local-healthcheck.timer`: one-minute local endpoint checks with a
  rate-limited stack recovery on failure; and
- `colameta-public-healthcheck.timer`: five-minute public HTTPS checks that
  report failures without restarting the stack for transient internet errors.

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
owner. Stop any manually launched processes on ports 8801, 8766 and 8767
before the first activation.

## Operate

```bash
sudo systemctl status colameta-private-beta.target
sudo systemctl restart colameta-private-beta.target
sudo systemctl stop colameta-private-beta.target
sudo systemctl list-timers 'colameta-*'
sudo journalctl --namespace=colameta -u colameta-stable.service
sudo journalctl --namespace=colameta -u colameta-mcp-remote.service
sudo journalctl --namespace=colameta -u cloudflared-colameta-mcp-prod.service
```

`systemctl stop colameta-private-beta.target` propagates a graceful stop to all
three long-running services. Explicitly stopping the target does not trigger
`Restart=always`; systemd restarts a service only when its process exits while
the unit is expected to remain active.

## Verify

```bash
curl --fail http://127.0.0.1:8801/
curl --fail http://127.0.0.1:8766/mcp
curl --fail http://127.0.0.1:8767/healthz
/home/jenn/tools/colameta/.venv/bin/python \
  /home/jenn/tools/colameta/scripts/remote_https_mcp_preflight.py \
  https://colameta-mcp.skmt617.top \
  --expected-head "$(git -C /home/jenn/src/colameta-dev rev-parse HEAD)"
```

For a controlled restart test, record the current `MainPID`, send `SIGTERM` to
that exact service PID, and verify that systemd assigns a different running
`MainPID`. Do not kill by process-name pattern.

## Roll back

Stop and disable the target, copy the newest backed-up units from
`/home/jenn/tools/colameta-systemd-backups/<timestamp>/` into
`/etc/systemd/system/`, remove only newly introduced ColaMeta units, then run
`sudo systemctl daemon-reload`. The stable source/package backup remains
separate from systemd configuration backups.
