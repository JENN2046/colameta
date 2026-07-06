# Managed Tunnel Service

This is the local operator plan for running the ColaMeta ChatGPT Apps tunnel as a
`systemd --user` service. It is intentionally local-only and does not read or
print token values, cookies, raw logs, provider responses, or tunnel-client
configuration.

## Files

- `scripts/colameta_tunnel_client_service.sh`
  - `check`: verifies executable/profile/key presence without printing secret
    values.
  - `start`: runs `tunnel-client run --profile colameta-sandbox`.
  - `health`: emits approved loopback `/healthz` and `/readyz` JSON.
- `systemd/user/colameta-tunnel-client.service`
  - user service unit template for the startup script.
- `.env.local`
  - ignored local secret file. It may contain `OPENAI_API_KEY` or
    `CONTROL_PLANE_API_KEY`.

The startup script maps `OPENAI_API_KEY` to `CONTROL_PLANE_API_KEY` in process
environment when the latter is absent. It never puts the key in command-line
arguments.

## Validate Without Starting

```bash
/home/jenn/src/colameta-dev/scripts/colameta_tunnel_client_service.sh check
systemd-analyze verify /home/jenn/src/colameta-dev/systemd/user/colameta-tunnel-client.service
```

The `check` output should show `key=present`, not the key value.

## Install As A User Service

Do this only when replacing the current ad-hoc tunnel process with a managed
service.

```bash
mkdir -p ~/.config/systemd/user
ln -sfn /home/jenn/src/colameta-dev/systemd/user/colameta-tunnel-client.service \
  ~/.config/systemd/user/colameta-tunnel-client.service
systemctl --user daemon-reload
systemctl --user enable colameta-tunnel-client.service
```

To start it under systemd:

```bash
systemctl --user start colameta-tunnel-client.service
```

If a manual `tunnel-client` process is already listening on `127.0.0.1:8080`,
stop that manual process before starting the managed service. Do not use force
kill unless the process is already stuck.

## Health Evidence

After the service starts:

```bash
/home/jenn/src/colameta-dev/scripts/colameta_tunnel_client_service.sh health
```

Approved closeout evidence is limited to these facts:

- `healthz.ok=true` maps to `TUNNEL_CLIENT_HEALTHZ_READY`.
- `readyz.ok=true` maps to `TUNNEL_CONTROL_PLANE_READYZ_READY`.
- Use the observed timestamp and the command shape as `evidence_source`.

Do not paste token values, cookies, raw logs, provider responses, tunnel-client
config, or proxy config into closeout evidence.

## Operational Notes

- The unit is not enabled or started by this repository file.
- The unit uses `Restart=on-failure` and a local loopback admin listener at
  `127.0.0.1:8080`.
- Runtime files are written under `~/.local/state/colameta/`.
- The current ColaMeta Web/MCP service must still be healthy on `127.0.0.1:8801`
  and `127.0.0.1:8766`.
