# Connector / Runtime Health Observability

`get_runtime_version_status` includes `connector_runtime_health`, a read-only
health card that separates local ColaMeta runtime evidence from external MCP
connector evidence.

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

## Closeout Semantics

`operator_closeout.decision` is `ready` only when local runtime, local Web/MCP,
and supplied external connector evidence are all healthy. Missing external
connector evidence remains blocked as `local_runtime_ready_external_connector_unverified`.

When blocked, `operator_closeout.safe_next_actions` points to approved status
surfaces and sanitized evidence collection. It does not authorize reading
tunnel-client config, proxy config, provider auth, tokens, cookies, private
memory, or raw provider responses, and it does not authorize network/proxy
mutation, stable service replacement, executor run, route transition, or
Delivery State acceptance.
