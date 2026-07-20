# Connector / Runtime Health Observability

See [Installation And Deployment](INSTALLATION_AND_DEPLOYMENT.md) for the
deployment and post-restart smoke sequence.

`get_runtime_version_status` includes `connector_runtime_health`, and MCP exposes
`get_connector_runtime_health_status` as a dedicated read-only closeout card.
Both separate local ColaMeta runtime evidence from external MCP connector
evidence.

The goal is to distinguish these cases without reading secrets or mutating
service state:

- the local ColaMeta service is stopped, stale, or serving mismatched PID/ports;
- the local Web/MCP endpoints are healthy, but the external connector path is
  not proven;
- runtime loaded-code provenance is current, stale, or unverified;
- tunnel-client or control-plane health is unavailable from safe status
  surfaces and must fail closed.

## Evidence Boundary

The health card only summarizes evidence that a safe local status surface has
already collected. It does not read tunnel-client config, proxy config, provider
auth, tokens, cookies, private memory, or raw provider responses. It also does
not perform paid provider probes and does not modify service lifecycle, network,
proxy, Git, plan, executor, or delivery state.

When connector evidence is missing, the external connector status is
`unverified`, not healthy.

## Main Fields

- `runtime`: loaded-code and reload/provenance summary derived from runtime
  observability.
- `local_service`: PID, source, endpoint, and health summary when service
  metadata or process-table discovery is available.
- `external_connector`: tunnel-client and control-plane status when safe
  evidence exists; otherwise fail-closed `unverified` summaries.
- `evidence_gaps`: compact list of missing safe evidence, such as sanitized
  tunnel-client runtime status or tunnel control-plane status.
- `operator_closeout`: read-only operator routing that says whether local
  service, runtime freshness, or external connector evidence blocks closeout.
- `reason_codes`: compact codes for operator routing.
- `safety_boundary`: explicit non-actions and private-state boundaries.

Common reason codes include:

- `LOCAL_SERVICE_HEALTHY`
- `LOCAL_SERVICE_HEALTH_UNVERIFIED`
- `LOCAL_SERVICE_STALE`
- `WEB_ENDPOINT_HEALTHY`
- `MCP_ENDPOINT_HEALTHY`
- `RUNTIME_LOADED_CODE_CURRENT`
- `RUNTIME_RELOAD_NEEDED_FOR_VERIFICATION`
- `CONNECTOR_HEALTH_UNVERIFIED`
- `TUNNEL_CONTROL_PLANE_UNVERIFIED`

## User-Facing Surfaces

Current safe surfaces:

- MCP `get_runtime_version_status` returns the full
  `connector_runtime_health` card.
- MCP `get_connector_runtime_health_status` returns the same closeout shape as a
  first-class read-only tool. It accepts optional caller-provided sanitized
  `tunnel_client` and `control_plane` summaries with only these fields:
  `status`, `reason_code`, `evidence_source`, and `last_observed_at`.
- The seven-tool private App exposes `get_apps_connector_smoke_packet`, which
  packages the same connector/runtime closeout without exposing the dedicated
  advanced health tool.
- Web `/api/status` includes a compact card based on the fact that the Web API
  itself is responding; MCP and external connector evidence remain unverified
  unless supplied by another safe status path.
- CLI `colameta status` appends a one-line connector/runtime summary after the
  existing service status output. This line reports the local evidence source
  (`metadata`, `process_table`, or `metadata_absent`), the operator closeout
  state, and compact reason codes.

The status output is evidence only. It does not authorize stable replacement,
restart, route transition, executor run, ReviewDecision, GateEvent, or Delivery
State acceptance.

The dedicated MCP tool rejects external evidence objects with extra fields. This
keeps raw values such as runtime keys, tokens, cookies, credentials, proxy config,
tunnel-client config, logs, or provider responses out of the tool result and out
of normal closeout handling.

## Closeout Semantics

`operator_closeout.decision` is `ready` only when local runtime, local Web/MCP,
and supplied external connector evidence are all healthy. Missing external
connector evidence remains blocked as `local_runtime_ready_external_connector_unverified`.

A successful authorized private App call is valid sanitized end-to-end
connector evidence when it is described truthfully as that call. Do not relabel
it as a `/healthz` or `/readyz` probe that was never performed. The final packet
must still report `overall_status=healthy`, `connector_closeout_ready / ready`,
and zero evidence gaps.

When blocked, `operator_closeout.safe_next_actions` points to approved status
surfaces and sanitized evidence collection. It does not authorize reading
tunnel-client config, proxy config, provider auth, tokens, cookies, private
memory, or raw provider responses, and it does not authorize network/proxy
mutation, stable service replacement, executor run, route transition, or
Delivery State acceptance.

## Receipt / Closeout Packet

A connector/tunnel closeout receipt is a short evidence packet, not a state
transition. It should record:

- source refs: dev HEAD, origin/main, stable service commit when known, and the
  exact read-only status surfaces used;
- local evidence: Web health, MCP health, runtime freshness, and whether the
  dedicated connector health tool is available on the service being checked;
- external evidence: separate `tunnel_client` and `control_plane` summaries,
  each with `status`, `reason_code`, `evidence_source`, and
  `last_observed_at` when safely available;
- closeout decision: `ready` only when local runtime, Web/MCP, tunnel-client,
  and control-plane evidence are healthy; otherwise `blocked`;
- residual gaps and forbidden actions.

Allowed external statuses are `healthy`, `degraded`, `unavailable`, and
`unverified`. A missing component is `unverified`, not healthy. A degraded or
unavailable component blocks closeout even when the other component is healthy.

Receipts must not include raw tokens, cookies, credentials, provider responses,
tunnel-client config, proxy config, private memory, logs, runtime keys, or
browser/login state. A receipt also does not authorize connector repair,
tunnel-client restart, proxy/provider mutation, stable service replacement,
executor run, route transition, ReviewDecision, GateEvent, commit, push, release,
deploy, or Delivery State acceptance.
