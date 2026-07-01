# Connector Tunnel Closeout Pre-Alignment Evidence

Date: 2026-07-01

Status: `blocked_pending_stable_alignment`

This receipt records connector/tunnel evidence collected before aligning the
stable service to the latest CI-success candidate. It is evidence only. It does
not authorize stable replacement, executor run, route transition,
ReviewDecision, GateEvent, or Delivery State accepted.

## Commit And CI

```yaml
candidate_commit_at_collection: d25a124ccc89aa9e137917d115bb839745824c18
candidate_short_at_collection: d25a124
origin_main_at_collection: d25a124ccc89aa9e137917d115bb839745824c18
ci:
  name: CI
  status: completed
  conclusion: success
  run_id: 28523924198
  url: https://github.com/JENN2046/colameta/actions/runs/28523924198
```

## Stable Runtime State

```yaml
stable_runtime_dir: /home/jenn/tools/colameta
stable_head_before_alignment: 5403363e4ca62d896c7db1815c842bb3993a5923
stable_service_pid: 2299609
stable_web: http://127.0.0.1:8801
stable_mcp: http://127.0.0.1:8766/mcp
stable_web_health: healthy
stable_mcp_health: healthy
```

The stable service is running and usable, but it is not yet aligned to
the latest dev repository state.

## Sanitized Tunnel Evidence

Evidence source:

```text
tunnel-client health --port 8080 --pid 4034 --json
```

Sanitized summary only:

```yaml
observed_at: 2026-07-01T14:20:29.048742Z
exit_code: 0
tunnel_client:
  status: healthy
  reason_code: TUNNEL_CLIENT_HEALTHZ_READY
  healthz_ok: true
  healthz_status: 200
control_plane:
  status: healthy
  reason_code: TUNNEL_CONTROL_PLANE_READYZ_READY
  readyz_ok: true
  readyz_status: 200
```

No tunnel-client config, proxy config, runtime key, token, cookie, credential,
provider raw response, or log raw content was read or copied.

## Stable MCP Closeout Result Before Alignment

`get_connector_runtime_health_status` was called on stable MCP with only the
sanitized evidence above.

```yaml
stable_mcp_result:
  ok: true
  local_service: healthy
  external_connector: healthy
  tunnel_client: healthy
  control_plane: healthy
  operator_closeout: local_service_ready_runtime_unverified
  decision: blocked
```

Interpretation:

```text
External connector/tunnel evidence is healthy.
Closeout is still blocked because the running stable runtime has not yet been
aligned to the latest dev checkout and cannot close runtime provenance with the
latest dev checkout.
```

## Required Next Step

Stable alignment requires Jenn's explicit exact authorization:

```text
授权替换稳定服务到 <exact_current_CI_success_commit_sha>
```

After replacement, rerun:

```text
colameta status /home/jenn/src/colameta-dev
get_runtime_version_status(project_name="colameta-self-dev")
get_connector_runtime_health_status(project_name="colameta-self-dev", sanitized tunnel/control-plane evidence)
```

Expected closeout after successful alignment:

```yaml
local_service: healthy
external_connector: healthy
operator_closeout: connector_closeout_ready
decision: ready
```

## Not Performed

```text
stable replacement
stable service restart
executor run
route transition
ReviewDecision creation
GateEvent emission
Delivery State accepted
provider/proxy/tunnel config mutation
secret/token/cookie/credential read
```
