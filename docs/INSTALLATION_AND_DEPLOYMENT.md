# ColaMeta Installation And Deployment

[中文](INSTALLATION_AND_DEPLOYMENT.zh-CN.md)

This guide covers package installation, source development, loopback services,
the seven-tool private App surface, the repository's private-Beta systemd
stack, stable replacement, verification, and rollback.

It is an operator runbook, not standing authorization to expose a host, change
DNS or OAuth, restart services, replace stable, push Git, publish a package, or
submit an App. Apply the narrowest section that matches the current task and
obtain action-scoped authorization at every protected boundary.

## 1. Choose A Deployment Shape

| Shape | Intended use | Network/auth posture |
| --- | --- | --- |
| Python package in a venv | Normal CLI use | No listener until started |
| Editable source checkout | ColaMeta development and tests | Local only by default |
| Loopback Web/MCP | One machine, local browser or local MCP client | `127.0.0.1`; local development auth |
| Seven-tool Commander | ChatGPT/Codex private App | Commander profile; HTTPS and OAuth externally |
| Private-Beta systemd stack | Jenn's persistent local/private deployment | System-level units, loopback origins, managed ingress |

Do not bind MCP or Web to `0.0.0.0` merely to make a local problem disappear.
Use loopback behind an explicitly approved HTTPS ingress for a remote private
App.

## 2. Requirements

- Python 3.10 or newer;
- Git;
- `venv` and pip;
- a local executor such as Codex or OpenCode when implementation runs are
  required;
- systemd, a trusted HTTPS endpoint, and an OAuth provider only for the
  corresponding deployment shapes.

## 3. Install

### Published package

Prefer an isolated environment:

```bash
python3 -m venv path/to/venv
path/to/venv/bin/python -m pip install --upgrade pip
path/to/venv/bin/python -m pip install colameta
path/to/venv/bin/colameta --version
```

### Source checkout

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python -m compileall adapters runner schemas scripts tests
.venv/bin/python -m pytest -q
.venv/bin/python scripts/self_hosting_smoke.py
```

For a frozen offline environment, replace the network-backed pip steps with the
approved wheel directory and `--no-index --find-links <wheel-directory>`. Keep
the environment rooted in this checkout; do not reuse a venv whose interpreter
or package provenance points at another ColaMeta tree.

## 4. Register A Project

```bash
colameta add /path/to/project managed
# or
colameta add /path/to/project source-only

colameta list
colameta status /path/to/project --json
```

Use `managed` when ColaMeta owns version planning, validation, receipts, review
handoff, and Git closure. Use `source-only` for a lighter read/inspect surface.
MCP service-mode calls route by registered `project_name`; they do not accept an
arbitrary remote project path.

## 5. Start A Local Loopback Service

For the normal registered-project service:

```bash
colameta start
```

Default endpoints are:

```text
Web: http://127.0.0.1:8799
MCP: http://127.0.0.1:8765/mcp
```

For an explicit local development process:

```bash
colameta serve /path/to/project --auth-mode none --open
```

`auth-mode=none` is for loopback development only. A network-visible Web bind
also requires `--allow-external-web` and an explicit Web read token. A remote
MCP private App requires HTTPS and OAuth; see
[Remote HTTPS MCP Service](remote-https-mcp-service.md).

## 6. Run The Seven-Tool Private App Surface

Select the Commander exposure profile without adding an eighth tool:

```bash
MCP_EXPOSURE_PROFILE=commander \
  colameta serve /path/to/project \
  --no-web \
  --mcp-host 127.0.0.1 \
  --mcp-port 8767 \
  --auth-mode external-oauth \
  --public-base-url https://mcp.example.com \
  --oauth-issuer https://idp.example.com/ \
  --oauth-jwks-url https://idp.example.com/.well-known/jwks.json \
  --oauth-audience https://mcp.example.com/mcp \
  --oauth-scopes mcp:read,mcp:preview
```

The Commander profile exposes exactly:

1. `list_registered_projects`
2. `get_apps_connector_smoke_packet`
3. `render_commander_app`
4. `analyze_project_state`
5. `run_mcp_workflow`
6. `manage_validation_run`
7. `manage_git`

`gate_review_request` is a workflow inside `run_mcp_workflow`, not another
tool. Start with:

```json
{
  "workflow": "gate_review_request",
  "phase": "inspect",
  "project_name": "<registered-project-name>"
}
```

Inspect and status are read-only. Preview creates a bounded signed Work Item
Gate preview. Apply requires the complete signed preview, exact bindings,
`confirm_gate_review=true`, `mcp:commit`, and the configured trusted private
Operator subject/client plus Work Item authority claims. Default/public remote
principals do not gain general commit authority.

The command above intentionally enables only read and preview scopes, so it is
ready for inspect/preview but not apply. Enabling private apply is a separate
protected operation: follow the interactive `colameta operator-config enable`
workflow in the [Jenn Private Operator Protocol](jenn-private-operator-protocol.md),
then grant only the bound private principal the required scope and claims.

## 7. Install The Repository Private-Beta systemd Stack

This repository includes a host-specific stack for Jenn's environment. Review
all checked-in unit paths before using it elsewhere:

```bash
./scripts/install_private_beta_systemd.sh
sudo systemd-analyze verify /etc/systemd/system/colameta-*.service \
  /etc/systemd/system/cloudflared-colameta-mcp-prod.service \
  /etc/systemd/system/colameta-*.timer \
  /etc/systemd/system/colameta-private-beta.target
sudo systemctl start colameta-private-beta.target
```

The installer backs up replaced unit files and installs/enables the target; it
does not start or stop the stack. The current stack uses:

```text
127.0.0.1:8801  stable Web
127.0.0.1:8766  stable seven-tool Commander MCP
127.0.0.1:8767  external-OAuth seven-tool MCP origin
127.0.0.1:8768  loopback advanced MCP catalog
```

Read [Private Beta systemd Operations](private-beta-systemd.md) before
installing or operating these units.

## 8. Stable Replacement

Stable replacement is separate from installation and requires an exact target:

```text
授权替换稳定服务到 <exact_commit_sha>
```

The bounded sequence is:

1. prove the candidate commit and validation evidence;
   record whether the exact object is on `origin/main` and whether remote CI
   actually validated it;
2. confirm the stable tracked worktree and service identities;
3. back up the previous tracked tree, record SHA-256, and create a rollback ref;
4. fetch and detach the stable checkout at the exact authorized commit;
5. build one local wheel and reinstall it with `--no-deps --force-reinstall`;
6. restart only the specifically authorized services;
7. verify service state, loopback endpoints, runtime provenance, the seven-tool
   inventory, private App connector smoke, and `gate_review_request/inspect`;
8. write a stable-replacement receipt.

Do not infer replacement authority from CI, a preview, a receipt, or ordinary
`dev_ahead_stable` drift. See the recorded
[2dc7895 stable replacement](stable-replacement-receipts/stable-replacement-2dc7895-20260720.md)
for a redacted evidence example, not a reusable authorization.
The preferred candidate is merged and CI-verified. An exactly authorized local
candidate is possible, but its receipt must disclose that it was not pushed and
was not validated by remote CI.

## 9. Verify

Local checks:

```bash
colameta status /path/to/project --json
curl --fail http://127.0.0.1:8799/api/healthz
curl --fail http://127.0.0.1:8765/healthz
```

For the repository private-Beta stack, use the ports in section 7 and confirm:

```text
service active/running
loaded_runtime_head == authorized target
runtime_loaded_code_stale == false
reload_needed_for_verification == false
Commander visible_tool_count == 7
private App list_registered_projects succeeds
connector closeout == connector_closeout_ready / ready
gate_review_request inspect succeeds without side effects
```

If the target project has Work Item governance disabled and no candidates, a
successful inspect with `candidate_count=0` is the truthful result. Do not
fabricate a Work Item merely to force preview/apply.

## 10. Roll Back

Rollback is another protected lifecycle action. Obtain exact authorization,
then use the backup file, checksum, and rollback ref recorded in the replacement
receipt. Reinstall the restored exact source, restart only authorized services,
and repeat the same runtime and private App verification. Never use a broad
recursive delete or an unverified archive as the rollback mechanism.

## 11. Security And Delivery Boundary

- Never put bearer tokens, cookies, credentials, private keys, provider raw
  responses, browser login state, or raw logs in commands, docs, receipts, or
  Git.
- Do not expose Web or MCP directly to the internet without an approved HTTPS
  ingress and authentication design.
- Package publication, Git push/tag, public App submission, DNS changes, tunnel
  changes, stable replacement, and service restart are separate actions with
  separate authority.
- Read-only health and smoke results are evidence; they do not create
  ReviewDecision, GateEvent, Delivery State accepted, or executor authority.
