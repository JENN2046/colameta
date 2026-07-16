# WIG-P3-CANARY-A1-R2-S1-R3 specification freeze

Stage ID: `WIG-P3-CANARY-A1-R2-S1-R3`

Status: `SPEC_CANDIDATE_READY_FOR_INDEPENDENT_REVIEW`

Supersedes specification manifest:
`5272431b672489d8ee810fd9fb51f97011bbdc22259bf1b0467d240439e5baf3`.
R3 closes the final independent-review findings for persistent Listener
readiness, sealed caller authentication at the Application boundary, exact
Fixture/Envelope/Preflight/Event wire contracts, deterministic evidence
digests, Create replay ordering, Token entropy, and semantically valid PASS
receipts.

This package freezes the minimum design for an authenticated, scope-bound
Phase 3 Authoritative Canary. It authorizes no implementation, migration,
deployment, runtime restart, snapshot refresh, authoritative activation,
commit, push, stable promotion, or use of a real Work Item.

The accepted core baseline remains:

```yaml
core_baseline:
  commit: 53d8939af22b019b2df2b555b85869ac39c5bba2
  tree: 255caefec1fcbe2c56f4c19673cc8c37cefe2427
  valid_as_r2_final_commit: false
```

R2 necessarily changes source and the Ledger schema. Any later implementation
must therefore produce a new exact commit, tree, wheel digest, verification
receipt, independent commit review, deployment authorization, and activation
authorization.

## Normative language and sources

`MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative. Machine-readable parts
of this package are authoritative for their respective concern:

- `r2-spec/authoritative-canary-tool-allowlist.v1.json`: exact MCP surface;
- `r2-spec/work-item-write-command-matrix.v1.json`: all 16 Work Item writes;
- `r2-spec/write-path-inventory.v1.json`: transport, application, nested, and
  maintenance write paths;
- `r2-spec/activation-envelope.v1.schema.json`: single-use control-plane
  activation envelope;
- `r2-spec/synthetic-fixture-contract.v1.schema.json`: exact normalized
  synthetic command and generated-ID contract;
- `r2-spec/preflight-receipt.v1.schema.json`: fresh runtime, authentication,
  Ledger and Backup evidence;
- `r2-spec/activation-lease.v1.schema.json`: Activation Lease wire contract;
- `r2-spec/activation-lease-event.v1.schema.json`: append-only Lease Event and
  hash-chain contract;
- `r2-spec/negative-test-matrix.v1.json`: minimum fail-closed verification;
- `r2-spec/r2-closeout-receipt.v1.schema.json`: implementation closeout
  evidence contract;
- `r2-spec/FREEZE_MANIFEST.json`: package content binding.

If prose and a machine-readable matrix disagree, the stricter deny/fail-closed
interpretation applies until a new spec version is reviewed.

### Digest algorithms

Unless a raw-byte rule is stated, `canonical_json` is the accepted Work Item
serializer: UTF-8 JSON with object keys sorted, `ensure_ascii=false`,
`allow_nan=false`, separators `(',', ':')`, no insignificant whitespace and no
terminal newline. Duplicate object keys are rejected during parsing.

- package file digests are SHA-256 over exact UTF-8 file bytes;
- `spec_manifest_digest` is SHA-256 over exact `FREEZE_MANIFEST.json` bytes;
- `tool_allowlist_digest` and `command_matrix_digest` are SHA-256 over their
  exact frozen file bytes;
- `authorization_digest` is SHA-256 over deterministic canonical JSON of the
  final authorization document with any digest/signature envelope omitted;
- `activation_envelope_digest`, `preflight_receipt_digest`,
  `synthetic_fixture_contract_digest`, and `fresh_ledger_baseline_digest` are
  SHA-256 over deterministic canonical JSON of their complete normalized
  payloads, excluding only their own digest/signature envelope;
- normalized command digests use the existing Work Item canonical JSON after
  application validation and before generated IDs are inserted;
- every `*_path_digest`, including project root, Canary root, HOME/XDG,
  Registry, Ledger, Backup, unclaimed Envelope, claimed Envelope and Fixture
  root, is `sha256(canonical_json({"resolved_posix_path": <absolute symlink-
  resolved POSIX path>}))`;
- `claimed_process_identity` uses the exact algorithm and inputs carried by the
  frozen Preflight Receipt Schema;
- `listener_attestation_digest` is SHA-256 over canonical JSON of
  `{claimed_process_identity, bind_address, port, process_listener_count,
  public_endpoint_created, relay_enabled, tunnel_enabled, proxy_enabled}`;
- `authenticated_request_context_binding_digest` is SHA-256 over canonical JSON
  of `{lease_id, authorization_digest, claimed_process_identity,
  runtime_instance_nonce, listener_attestation_digest, principal_id,
  session_ref}`; the digest is not a substitute for the non-serializable trust
  seal;
- `lease_snapshot_digest` is SHA-256 over canonical JSON of the complete final
  Lease row after materialization;
- the sanitized Lease snapshot export is exactly that canonical JSON payload,
  encoded as UTF-8 without a terminal newline, so its file SHA-256 equals
  `lease_snapshot_digest`;
- each Lease Event digest is
  `sha256(canonical_json(event_without_event_digest))`; its root is
  `sha256(canonical_json(event_digest_array))`, where the array is strictly
  ordered by contiguous `sequence` and contains no duplicate event ID;
- the sanitized Lease Event export is canonical JSON of the complete ordered
  Event array, UTF-8 without a terminal newline; its file digest binds the
  export while the Event root is independently recomputed from its rows;
- a listed-tool set digest is SHA-256 over canonical JSON of the sorted unique
  tool-name array.

Raw-byte and canonical-JSON digests are not interchangeable.

All JSON Schema validation in this specification uses Draft 2020-12 with an
explicitly registered strict RFC 3339 `date-time` checker; relying on a
library's empty/default `FormatChecker` is invalid. Timestamp Schemas also
enforce an RFC 3339 lexical pattern. Date-time ordering, digest recomputation,
cross-field Fixture consistency, Lease Event state-version sequencing and path
containment are additional semantic checks; shape validation alone is never
sufficient.

The machine JSON contracts and their sanitized review copies use UTF-8/LF and
omit a terminal newline because the approved source-review endpoints normalize
that boundary. Accessibility evidence MUST compare the endpoint-returned UTF-8
bytes directly with the local review-copy bytes and their SHA-256; a merely
untruncated visual read is insufficient.

## Threat model

The first Authoritative Canary freezes this threat model:

```yaml
in_scope:
  - unauthenticated loopback clients
  - clients with an incorrect or absent bearer token
  - accidental or unapproved local clients
  - malformed, stale, replayed, concurrent, or over-quota commands
  - direct transport or application-command bypass attempts
  - process/watchdog failure after Lease expiration

out_of_scope:
  - malicious processes running as the same Unix UID
  - malicious code inside the independently reviewed exact runtime artifact
  - host administrator or kernel compromise
```

If malicious same-UID processes become in scope, a separate Unix user,
container, user/network namespace, or equivalent OS boundary is mandatory.
Bearer Token plus mode `0600` is not an OS isolation boundary.

## Required architecture

All four controls are mandatory:

```text
Private Bearer Token authentication
        +
Fresh empty Ledger
        +
Server-enforced restricted MCP surface
        +
Transactional single-Work-Item Activation Lease
```

No one control substitutes for another. A fresh Ledger removes old-fixture
risk but does not enforce quotas. A Token identifies an allowed client but does
not restrict tools or Work Items. A hidden tool definition is not enforcement.
An external timer does not replace transaction-time Lease expiry checks.

## Token authentication and trusted Principal

The Authoritative Canary MUST run with `auth_mode=token`. The one-time Token
MUST contain at least 256 bits generated by the operating-system CSPRNG and be
encoded without reducing that entropy. It is loaded from the isolated Canary
`<XDG_CONFIG_HOME>/colameta/auth.json`, owned by the Canary user, mode `0600`,
with parent directories mode `0700` or stricter. It MUST NOT appear in command
line arguments, environment variables, Git, logs, receipts, or sanitized review
bundles. It may exist in service memory for request verification.

The private `auth.json` also records non-secret generation metadata. Preflight
verifies the declared OS-CSPRNG algorithm and decoded entropy length against the
actual credential before listener bind or request authentication is enabled;
caller-supplied or weak static strings refuse startup. The Token necessarily
exists transiently in service memory while it is verified. Receipts retain only
the metadata and evidence digest, never the credential.

Missing, malformed, weakly configured, and incorrect Tokens MUST fail before
dispatch. A correct Token may mint an `AuthoritativeCanaryRequestContext` only
after the exact Lease has a persisted Listener attestation. This context is a
non-JSON, trust-sealed process capability bound to the current process identity,
runtime nonce, Listener attestation digest, Principal and session. Every Preview
and write MUST carry it through central dispatch into the Application Service.
`PrincipalContext`, an active Lease, or `mcp:commit` without this capability is
insufficient. A capability minted for another Lease or authorization is also
invalid even if process, Principal and session happen to match. No command body
may provide Actor, authority basis, Principal, request context, Lease,
authorization ID, or quota state.

The Lease binds exact `principal_id`, `session_ref`, authentication mode, and
permission set. A correct Token with a mismatched Principal or session fails
closed. Generic `mcp:commit` remains unrelated to Work Item permissions.

The capability factory remains private to the authenticated HTTP composition
root. Direct Python, CLI, Worker, Agent or control-plane calls cannot mint or
deserialize it. The Application Service validates its trust seal and exact
binding digest inside every Preview and write transaction.

The one-time Token MUST be deleted or rotated immediately after the endpoint is
stopped or the Lease becomes terminal. Closeout MUST prove that the old Token
no longer authenticates and that no plaintext copy remains in `auth.json`,
logs, receipts, environment, command line, bundle, or Git.

## Runtime isolation and startup preflight

R2 uses a new Canary root. Before the process can claim a prepared Lease, a
fail-closed Preflight MUST resolve and verify:

- `HOME`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, and `XDG_CACHE_HOME` are below
  the exact Canary root;
- the selected Registry is below that root, contains exactly one Lease-bound
  project, and the global Registry is neither selected nor open;
- executable, current working directory, project root, settings, Ledger,
  Backup, Token file, Fixture root, unclaimed activation envelope and the
  deterministic claimed-envelope path are below the Canary root;
- before Lease claim, no Canary listener exists and the authorization-bound
  intended endpoint is exactly `127.0.0.1:<port>`;
- after a successful claim, exactly one socket is bound to that loopback
  endpoint, and request dispatch remains disabled until a post-bind listener
  attestation succeeds;
- non-loopback binding, public URL, Relay, Tunnel, Proxy, DNS/firewall change,
  Connector registration, and multi-user access are absent;
- no Outbox/Delivery/Stable/Product/Connector/Executor background worker is
  composed.

The Preflight receipt MUST validate against
`preflight-receipt.v1.schema.json`. It records the recomputable process-identity
inputs (including Linux boot ID and `/proc/<pid>/stat` start-time ticks), raw
root-relative path evidence plus normalized path digests, preclaim listener
evidence, Registry selection, Token CSPRNG/entropy evidence,
exact Principal/session/permission binding, exact business-table counts,
schema/generation, signing-key presence, source/runtime digests, restricted
surface, and generation-bound Backup. It is
valid for at most 120 seconds. Unknown, missing, stale, or failed checks refuse
Lease claim and listener exposure.

## Restricted MCP surface

The profile name is `authoritative_canary`; default and unknown behavior is
deny. Its exact allowlist contains 14 tools: five Read, two Preview, and seven
Lease-controlled Write tools. All nonlisted tools, including Git, Files, Plan,
Executor management, Product, Stable Promotion, Delivery, legacy import,
historical binding, blocker mutation, Outbox mutation, and project mutation,
MUST be absent and non-dispatchable.

The Canary composition root MUST NOT start an Outbox/Delivery dispatcher,
Stable Promotion manager, Product mutation worker, Connector, Relay, Tunnel, or
background Executor. Gate-generated Outbox facts remain pending evidence and
cannot create an external side effect during the activation window.

Enforcement MUST occur in the central call path, not only in `tools/list` or an
HTTP route wrapper. These paths MUST share the same allowlist check:

- JSON-RPC `tools/call` / `call_tool`;
- any direct named JSON-RPC tool alias;
- HTTP Actions routes;
- `call_tool_for_agent` and Cloud Agent dispatch;
- routed project tool dispatch;
- Web/CLI adapters if they reuse the Canary composition root.

For the Canary endpoint, direct named tool aliases and HTTP Actions SHOULD be
disabled rather than duplicated. MCP Resources MUST be empty or disabled. The
only ordinary protocol methods are initialization, initialized notification,
ping/health, `tools/list`, and `tools/call`.

At startup the service MUST compare the actual definition names, actual central
dispatch names, and frozen allowlist. Any missing or extra tool refuses startup.
`tools/list` MUST return exactly the 14 frozen names. Directly naming a hidden
tool MUST fail with no side effect even when it still exists in the process-wide
normal registry.

## Fresh Ledger and pre-activation baseline

R2 MUST use a new project data directory and a new Ledger. It MUST NOT restore
or copy the D1/A1 Generation 2 Ledger or its 15 fixtures. Before Lease
activation, the following business-fact counts are exactly zero:

```yaml
work_items: 0
task_versions: 0
execution_attempts: 0
artifact_refs: 0
decision_records: 0
gate_events: 0
acceptance_manifests: 0
delivery_receipts: 0
audit_events: 0
blocker_events: 0
outbox_events: 0
inbox_events: 0
```

Those 12 exact names are mandatory; arbitrary zero-valued keys are invalid.
The normalized baseline also includes schema version `5`, current database
generation, Preview signing-key presence, zero external associations and
Attempt Events, and no prior active or terminal Activation Lease for this
authorization. Its canonical digest is `fresh_ledger_baseline_digest`.

The implementation MUST add forward-only Ledger schema v5 for Activation Lease
control records. Schema initialization, exact migrations, and
preview signing-key provisioning occur before activation. During an active
Lease, Preview signing MUST read an existing key and fail closed if missing; it
MUST NOT implicitly create a key through an unguarded write transaction.

After schema/key provisioning and before activation, the control plane creates
a SQLite Backup-API snapshot and records database generation, schema version,
integrity, foreign-key result, digest, permissions, and source binding. A D1/A1
backup is evidence only and is not an R2 activation backup.

The prepared Lease MUST bind the exact Preflight Receipt digest, observation
and expiry timestamps, Fresh Ledger baseline digest, Backup Receipt digest, and
Backup file SHA-256. `database_generation` alone is insufficient because normal
domain writes do not increment it. During the activation-claim transaction the
service rechecks the exact zero baseline and rejects a Preflight older than 120
seconds.

## Transactional Activation Lease

The Lease is a source-integrated local control-plane capability stored in the
same SQLite database so scope and quota enforcement share the business
transaction. A proxy-only or second-port Guard is not a conforming R2
implementation.
The Lease contains no bearer token. Its storage model is:

- `activation_leases`: one mutable CAS-controlled record per authorization;
- `activation_lease_events`: append-only issue/activate/consume/reject/freeze/
  expire/close/revoke evidence;
- at most one active Lease per Ledger;
- a nullable `authorized_work_item_id` that becomes immutable after the first
  successful create;
- a `state_version` used for Lease CAS and concurrency tests.

Lease lifecycle is one-way:

```text
prepared -> claimed -> active -> write_frozen -> closed
       \         \       \-> expired
        \         \-------> revoked
         \----------------> revoked
```

`expired`, `revoked`, and `closed` are terminal. A frozen or terminal Lease is
never reactivated; another attempt requires a separately authorized new Lease.

### One-shot activation bootstrap

The bootstrap removes the process-identity/startup cycle:

1. After a separate activation authorization, the new bootstrap process starts
   with the authorization-selected `runtime_instance_nonce`, Token configuration
   and `authoritative_canary` composition, but with no Lease, no Listener and
   `effective_authoritative_writes=frozen`. It derives
   `expected_process_identity = sha256(canonical_json({pid,
   process_start_ticks, boot_id, executable_sha256,
   runtime_instance_nonce}))`, writes the schema-
   valid Fresh Preflight Receipt below the Canary root, and waits without
   accepting requests.
2. The offline local control-plane command verifies that receipt and its age,
   atomically writes and fsyncs a mode-`0600` schema-valid activation envelope
   at the unclaimed path, then uses one `BEGIN IMMEDIATE` transaction to insert
   the `prepared` Lease and its `lease_issued` Event. Both bind the exact
   Preflight digest, unclaimed and claimed Envelope paths, runtime nonce and
   `expected_process_identity`; `claimed_process_identity` remains `null`. A
   crash before the Lease transaction leaves only an unusable orphan envelope;
   a failed Lease transaction removes or seals that orphan without making it
   claimable. A prepared Lease is never committed without its durable Envelope.
3. The same waiting process reads the prepared Lease, proves its freshly
   derived identity equals `expected_process_identity`, then atomically moves
   the unclaimed envelope with no replacement to the deterministic process-
   identity claim path and fsyncs the parent directory. The unclaimed path must
   be absent before validation continues. It then reads the claimed envelope
   and reruns all source, isolation, Token, Fresh Preflight, Backup, time,
   Principal, project, tool-surface and policy checks.
4. One `BEGIN IMMEDIATE` transaction rechecks the Fresh Ledger baseline,
   verifies the Preflight is no older than 120 seconds, confirms that no other
   Lease is active, rechecks actual identity equals the bound expected identity,
   writes the claimed process identity, changes
   `prepared -> claimed`, records `CLOCK_MONOTONIC` claim/deadline nanoseconds
   with a delta no greater than 1,800 seconds, and appends exactly one
   `process_claimed` event.
5. Only after that transaction commits may the process bind the loopback
   socket. Before serving any request it verifies the exact address, port,
   socket count and absence of other exposure. A second `BEGIN IMMEDIATE`
   transaction stores `listener_attested_at`, the Listener attestation digest
   and request-context binding digest, changes `claimed -> active`, and appends
   exactly one `listener_attested` Lease Event. Only that commit enables the
   accept loop or Application writes. A mismatch closes the socket and revokes
   the claimed Lease.
6. A bootstrap process that exits before Envelope issuance invalidates its
   Preflight and expected identity. Claim failure exits nonzero without a
   listener. A crash after the atomic
   envelope move leaves the unclaimed path absent; a crash after Lease claim
   leaves a Lease bound to the dead process. Neither state can be reused by a
   later process and both require a new activation authorization.

The activation envelope is not an MCP command and contains no Bearer Token. It
is single-use, authorization-digest-bound, stored below the isolated Canary
root, and retained only at the claimed path until closeout replaces it with a
sanitized digest/evidence record. Copying it back to the unclaimed path or
claiming it after any failed/crashed attempt is forbidden.

`active` therefore always means both process-claimed and Listener-attested.
There is no writable state between those facts. A direct Application call while
the Lease is `prepared` or `claimed`, or without the sealed authenticated
request context, fails before domain access.

The Lease binds:

- exact authorization and spec-manifest digests;
- exact activation-envelope, Fresh Preflight, Fresh Ledger baseline, Backup
  Receipt and Backup file digests;
- new implementation commit, tree, wheel/artifact digest, runtime instance and
  nonce, expected and claimed process identities, loopback endpoint,
  executable/CWD/settings/Token/Envelope/Fixture/Ledger/Backup and other
  isolated-path digests, project name/root digest, and database generation;
- exact tool allowlist and command-matrix digests;
- Principal ID, session, Token authentication mode, and permissions;
- `origin.kind=manual` and the exact prefix
  `synthetic://WIG-P3-AUTH-CANARY-A1-R2/`;
- a maximum 1,800-second window;
- one generated Work Item and its resource quotas.

The implementation closeout receipt MUST identify the exact `lease_id`,
authorization and envelope digests, expected and claimed process identities,
Listener and request-context binding digests, final Lease snapshot digest and
state version, and the ordered Lease Event root/count. It MUST also bind
sanitized canonical exports of the complete final Lease snapshot and ordered
Lease Events so an independent reviewer can recompute the snapshot digest,
every Event digest, the hash chain and the Event root. A set of boolean test
conclusions without this exact Lease binding and recomputable evidence is not
sufficient. Export paths are relative to one digest-bound sanitized evidence
root and may not escape it.

Lease issuance, activation, closure, revocation, backup, restore, and migration
are control-plane operations. None is an MCP tool on the Canary endpoint.

### Synthetic Fixture contract

Origin Prefix is a routing label, not proof that content is synthetic. The
activation authorization therefore supplies one canonical
`synthetic_fixture_contract` that validates against
`synthetic-fixture-contract.v1.schema.json`; its digest is bound by the Lease.
It contains:

- the exact normalized Work Item Create command digest;
- exactly two ordered normalized Task Version payload digests, including the
  initial version, for the returned-for-revision scenario;
- an exact synthetic `objective_ref` prefix;
- the exact fixture-root path digest below the isolated Canary root;
- allowed Artifact kinds limited to `validation`, `test_report`,
  `evidence_receipt`, and `report`;
- Artifact URI policy `file` plus resolved-path containment below the fixture
  root and mandatory immutable SHA-256 verification;
- the permitted two Runtime Attempt objectives and expected Task Version;
- the permitted Decision actions and lifecycle scenario;
- `external_associations_allowed=false`, empty Plan Version references, and no
  real Git Commit, project Plan, Report, production URI, Delivery destination,
  Stable candidate, or Product Submission reference.

Generated Work Item, Attempt, Artifact, Decision and Gate IDs are represented
by typed placeholders in the fixture contract. The application service binds
each placeholder to the first generated ID in the same transaction and rejects
later mismatches. Every allowed Preview and write validates its normalized
content against the fixture contract; matching only the Origin Prefix or Work
Item ID is insufficient.

The Fixture's ordered `command_slots` carry each normalized command object,
its recomputed digest, idempotency binding, expected fact delta and generated-ID
slots. It also carries the exact two Runtime Attempt objective bindings, four
Decision actions, six lifecycle transitions, Artifact URI/path/digest policy,
  the seven required command names, and explicit empty external-association and
Plan-Version arrays. At least one immutable verified Artifact must bind each
Task Version. Sequences MUST be contiguous and unique, and these cross-field
declarations MUST agree with the normalized command slots.
Commands not present in the authorization-reviewed slots are denied even if
their command name, Origin or Work Item matches. Exact replay refers to the
already consumed slot and cannot advance the sequence.

### Required transaction order

Every allowed write MUST use one `BEGIN IMMEDIATE` transaction:

```text
BEGIN IMMEDIATE
  -> load the one expected Listener-attested active Lease
  -> verify status, time window, authorization/spec/source/runtime digests
  -> verify the sealed Token-authenticated request context, project, trusted
     Principal/session and synthetic command digest
  -> reconcile actual bounded/denied-table facts with Lease usage and bindings
  -> resolve idempotency and determine which new facts would be created
  -> if exact replay, verify its existing facts and bound Work Item, then return
     without mutable-scope rejection, quota charge or Lease Event
  -> otherwise verify next Fixture slot, command and Work Item mutation scope
  -> verify all resulting fact counts against quotas
  -> perform the domain write
  -> atomically bind the first generated work_item_id when applicable
  -> update Lease usage/state_version only for newly created facts
  -> append Lease audit evidence
COMMIT
```

No rejected domain operation may leave a partial domain fact or quota
increment. A hard Guard violation MAY commit only the Lease freeze/terminal
status and one Lease event, with no domain mutation. The first create and Lease
Work Item binding MUST be atomic; concurrent create applies can produce at most
one Work Item.

The successful Create replay is the only Create allowed after
`authorized_work_item_id` becomes non-null. It must resolve by the exact Preview,
creation operation, normalized digest and already bound Work Item before the
"new Create requires an unbound Lease" rule is evaluated. A competing Create
remains a hard scope violation.

### Quota accounting

Quotas count newly committed facts, not API calls:

```yaml
maximum_new_work_items: 1
maximum_task_versions: 2
maximum_runtime_attempts: 2
maximum_artifacts: 4
maximum_decisions: 4
maximum_applied_gate_events: 8
maximum_rejected_gate_events: 8
maximum_gate_events_total: 16
maximum_lease_events: 40
```

The initial Task Version created with the Work Item consumes one Task Version.
Artifacts created inside `complete_execution_attempt` consume the same Artifact
quota as direct registration. Gate rejection records consume rejected and total
Gate quotas. Derived Audit, Outbox, Attempt Event, and Acceptance Manifest facts
are bounded by the command that creates them.

An exact idempotent replay that creates no new fact consumes no additional
quota. An idempotency conflict is rejected and consumes nothing. Idempotency
resolution and quota accounting MUST occur in the same transaction.

Every newly committed allowed domain command appends at most one Lease Event
with a unique source/idempotency binding. Exact idempotent replay appends no new
Lease Event. Authentication failures append none. A hard Guard condition may
append one deduplicated freeze/terminal event. The total number of Lease Events
may never exceed 40, including issue, activation and closeout events.

Lease Events obey a frozen semantic transition matrix: `lease_issued` creates
`prepared`; `process_claimed` moves `prepared -> claimed`;
`listener_attested` moves `claimed -> active`; domain events retain `active`;
freeze, expiry, close and revoke events use only their declared lifecycle
edges. Event 1 has state version `0`; thereafter contiguous Event sequence `n`
has `state_version_before=n-2` and `state_version_after=n-1`. Command events
bind the exact authenticated-request-context, source/idempotency key, Principal
and fact delta. These relationships are validated in addition to the Event
Schema shape.

Before every allowed write, actual primary fact counts MUST equal Lease usage:
Work Item, Task Version, Runtime Attempt, Artifact, Decision and applied/
rejected/total Gate counts. Denied tables must remain zero; derived Acceptance,
Audit, Outbox and Attempt Event counts must match their deterministic source
facts. Any mismatch is treated as an out-of-band write, rejects the domain
operation and freezes the Lease.

`gate_events_total` MUST always equal `applied_gate_events +
rejected_gate_events`. Window validation MUST enforce `issued_at <= not_before
< expires_at` and `expires_at - not_before <= 1,800 seconds`; JSON Schema shape
validation alone is insufficient.

Authentication failures occur before Lease access and MUST NOT let an
unauthenticated caller freeze the Lease. Ordinary domain rejections and exact
idempotent replays also do not freeze it. A trusted caller's Lease integrity,
source/runtime, Principal/session, project, Work Item scope, denied-command,
quota, or expiry violation MUST reject the domain mutation and move the
effective Lease policy to write-frozen (or expired/revoked as appropriate).
Internal Guard errors fail the same way. At most one terminal/freeze event is
appended for that condition, preventing rejection-event spam.

### Expiration and rollback

Every non-Read request checks `not_before` and `expires_at` using the service's
trusted UTC clock. After expiry, Preview and write commands fail closed even if
an external watchdog has failed. While a nonterminal Lease is write-frozen,
Token-authenticated Reads remain available for closeout. When a Lease becomes
expired, revoked or closed, the endpoint stops and revokes the one-time Token;
subsequent evidence reads use the offline read-only control plane, not the old
endpoint credential.

`get_execution_attempt_dispatch_authority` remains readable for diagnosis but
MUST return `dispatch_authorized=false` unless the exact Lease is active, the
runtime binding is current, and the Attempt is otherwise domain-eligible.

The process also keeps a monotonic deadline initialized at activation; the
earlier of the persisted UTC expiry and monotonic 1,800-second deadline wins.
A missing, negative, inverted or extended monotonic deadline is a hard Guard
failure. Its absolute value is meaningful only to the bound process and is
never reused after restart.
A process restart invalidates the active runtime binding and requires a fresh
Preflight plus separately reviewed activation decision rather than resetting
the timer.

The synchronous safety boundary is `effective_authoritative_writes=frozen`.
Changing the configured `gate_mode` string is a control-plane operation and is
not relied upon for correctness. A watchdog MAY stop the endpoint; the operator
then restarts in Shadow and verifies:

```yaml
gate_mode: shadow
authoritative_transitions: false
active_activation_lease: false
post_window_authoritative_writes: 0
```

No automatic code deployment, feature escalation, backup restore, schema
downgrade, or deletion of append-only evidence is permitted as rollback.
Closeout stops the endpoint, verifies the port is no longer listening, deletes
or rotates the one-time Token, proves the old Token fails authentication, then
restarts only under a separately permitted Shadow configuration.

## Machine-valid closeout semantics

The implementation-conformance receipt validates against
`r2-closeout-receipt.v1.schema.json` and the frozen semantic checks. It records
an ephemeral isolated conformance harness, not deployment or activation of the
existing D1 Canary. A later deployed Canary activation requires its own
separately authorized activation receipt. `result=PASS` is valid only when:

- every frozen verification slot is present exactly once and has `exit_code=0`
  and `passed=true` plus an evidence path and digest below the bound sanitized
  evidence root;
- the Lease final status is `closed`, its snapshot and ordered Event root are
  recomputable from bound sanitized exports, and the Event chain and transition
  semantics validate against the Lease Event Schema;
- `gaps` and `blockers` are empty;
- all four protected `AGENTS*` paths and their frozen hashes match exactly;
- Token entropy, weak-token rejection, exact tool surface, Fresh Ledger,
  Fixture, request capability, Listener readiness and closeout revocation
  evidence are present.

`PASS_WITH_GAPS` requires at least one documented gap and no blocker. `BLOCKED`
requires at least one blocker. A nonzero or explicitly failed verification,
missing required slot, revoked/frozen Lease, fake protected path, invalid time
ordering, or irreproducible digest cannot validate as `PASS`.

## Complete write-path policy

All 16 public Work Item writes are classified in the command matrix. Seven are
allowed under the Lease and nine are denied. `apply_blocker` and
`clear_blocker` are denied because they alter effective Gate conditions.
Delivery, Outbox, legacy import, and historical binding are denied.

Additional paths are classified in the write-path inventory:

- `restore_ledger`: denied for the entire activation window;
- migration: exact startup schema only, before activation;
- backup: control plane only, before/after the window, never the endpoint;
- export: read-only control plane only, never the endpoint;
- signing-key creation: pre-activation only;
- direct `authoritative_transitions=True`: refuses authoritative writes without
  the exact active Lease;
- direct repository/application mutation outside the reviewed composition root:
  prohibited and covered by architecture tests.

Normal Shadow and unbound compatibility paths outside the Authoritative Canary
profile retain their existing behavior. The Canary restriction MUST NOT silently
turn into the general production policy.

## Implementation work packages after separate authorization

No package below is authorized by this spec freeze:

1. **R2-I1 — schema and policy core:** migration v5, Lease/Event repository,
   prepared/claimed/attested lifecycle, unique hash-chained Lease Event
   idempotency, bounded event accounting, fact reconciliation, expiry and audit.
2. **R2-I2 — application write refactor:** one connection across Lease checks,
   idempotency, nested fact creation and quota updates; all 16 writes and
   maintenance paths classified.
3. **R2-I3 — transport restriction:** `authoritative_canary` exact registry,
   central dispatch enforcement, sealed authenticated request capability,
   protocol/resource reduction, CSPRNG Token and schema-valid runtime-isolation
   Preflight.
4. **R2-I4 — composition and control plane:** fresh-Ledger bootstrap, signing
   key provisioning, synthetic Fixture contract, activation envelope,
   waiting-process Preflight handshake, prepared/claimed Lease transitions,
   closure, Backup, Token revocation and Shadow restart runbook.
5. **R2-I5 — verification and closeout:** focused negative/concurrency tests,
   full regressions, security checks, wheel/runtime binding, protected-assets
   check, machine-readable receipt and independent review bundle.

Each implementation package may be combined in one reviewed source candidate,
but no deployment or activation follows automatically from test success.

## R2 implementation acceptance criteria

An implementation candidate is reviewable only when all are true:

1. a new exact commit/tree and wheel digest are bound;
2. the exact 12-table Fresh Ledger baseline, canonical baseline digest,
   Preflight Receipt, at-most-120-second freshness and generation-bound Backup
   are independently readable and Lease-bound;
3. isolated HOME/XDG/Registry paths, single project, loopback listener and
   absence of public/Relay/Tunnel/Proxy/background-worker paths are proven;
4. no/malformed/wrong Token requests return 401 and create no fact;
   weak Token configuration refuses startup, and Token entropy is at least 256
   CSPRNG bits;
5. `tools/list`, central dispatch, direct aliases, Actions and Agent dispatch
   enforce exactly the frozen 14-tool surface;
6. the schema-valid envelope is atomically and durably consumed before
   validation, `prepared -> claimed` occurs before listener bind,
   `claimed -> active` occurs only with persisted Listener attestation, request
   dispatch and Application writes wait for that commit, and a failed/crashed
   claim cannot be reused;
7. every Create, Task Version, Attempt, Artifact, Decision and Transition
   matches the Lease-bound synthetic Fixture contract; real references fail;
8. missing, expired, mismatched, revoked, or closed Lease rejects every Preview
   and write path;
9. direct Python authoritative construction cannot bypass the Lease or Token;
   a valid Lease and Principal without the sealed authenticated request context
   is rejected;
10. concurrent first-create produces one Work Item and one Lease binding;
    exact replay after binding returns that Work Item with no new fact, quota or
    Lease Event;
11. every quota counts new nested facts, actual table counts reconcile with
    usage, and idempotent replay creates neither a quota charge nor Lease Event;
12. Lease Events remain deduplicated and below the frozen maximum of 40;
13. restore, migration, Delivery, blocker, historical, legacy and Outbox writes
   are unavailable during activation;
14. no Outbox/Delivery/Stable/Product/Connector/Executor background worker is
    composed and Gate-generated Outbox facts remain pending;
15. invalid or stale time windows fail, and expiry freezes writes without
    depending on a watchdog;
16. an expired/frozen Lease also removes Runtime Attempt dispatch authority;
17. endpoint stop, old-Token rejection and restart-to-Shadow closeout are
    verified;
18. existing service, stable runtime, real Work Items and protected `AGENTS*`
    assets remain untouched;
19. no Push, Stable Promotion, existing-service replacement, deployed Canary
    activation, or change to the existing D1 Shadow Canary occurs during
    implementation review; an ephemeral isolated conformance harness is not a
    deployment authorization;
20. every sanitized machine contract and root Manifest is returned by both
    approved review endpoints as exact digest-matching bytes without
    truncation or terminal-newline reconstruction.
21. the final closeout Schema plus frozen semantic verifier rejects PASS when
    any required command is nonzero/failed/missing, the Lease is not closed,
    protected paths differ, gaps or blockers exist, time ordering is invalid,
    or any bound digest cannot be independently recomputed.

## Authority boundary after this freeze

```yaml
specification:
  status: READY_FOR_INDEPENDENT_REVIEW

implementation:
  authorized: false

runtime:
  current_canary_must_remain_shadow: true
  restart_authorized: false
  snapshot_refresh_authorized: false

release:
  commit_authorized: false
  push_authorized: false
  stable_promotion_authorized: false
  existing_service_replacement_authorized: false
  authoritative_activation_authorized: false
```
