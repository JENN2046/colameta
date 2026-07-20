# Jenn Private Operator Local Health IPC

Status: same-project multi-instance aggregation implemented locally; validation in progress; not delivered or deployed

## Required outcome

`colameta status` and `colameta operator-config status` must be able to read the
quarantine attention state from every validated running ColaMeta service process
for the explicitly selected project.
The channel is local, private, read-only, and diagnostic-only. It is not an
authorization input and must never appear in MCP, HTTP health endpoints, Web
Console responses, connector health, tickets, logs, or provider responses.

The CLI now queries the selected service set through the private IPC and never reads
`private_operator_local_runtime_status()` in the CLI process. An IPC failure
produces `unknown/unavailable`; there is no fallback to the CLI process's
zero-value `clear` result.

## Threat model and limits

Version 1 is Linux-only. It requires:

- `AF_UNIX`, `SOCK_SEQPACKET`, `SOCK_CLOEXEC`, and `SO_PEERCRED`;
- `os.pidfd_open` and `/proc/<pid>/stat` process start identity;
- component-by-component `dirfd` traversal using `O_DIRECTORY`, `O_NOFOLLOW`,
  `O_CLOEXEC`, `fstat`, and `*at` operations;
- a private registration root owned by the effective UID with mode `0700`;
- registration files owned by the effective UID with mode `0600`.

Missing primitives, unsafe storage, ambiguous process discovery, or any failed
identity check make the observation unavailable. There is no TCP, loopback
HTTP, public-health, pathname-socket, `/tmp`, snapshot-file, or non-Linux
fallback.

This design rejects different-UID peers, rejects a same-UID server whose PID or
process generation differs from the frozen candidate, and makes path
replacement fail closed. It does not prove that a frozen same-UID candidate is
genuine ColaMeta code: a fully compromised same-UID account can create a
well-formed registration and matching listener. Consequently v1 provides no
confidentiality, integrity, or authenticity guarantee against a hostile
same-UID process. `SO_PEERCRED + pidfd` proves only that the connected peer is
the frozen candidate process. Strong isolation requires a separate service UID,
namespace, MAC policy, or protected system service.

The observation may affect only local text/JSON diagnostics. It must not feed
authorization, scope resolution, ticket or claim state, execution, commit,
validation, automatic recovery, service control, or any public projection.

## Architecture

Add `runner/private_operator_health_ipc.py` with four internal components:

- `PrivateOperatorHealthIPCServer`: owns the abstract listener and samples
  `private_operator_local_runtime_status()` inside the service process;
- `PrivateOperatorHealthIPCClient`: freezes all live service processes for an
  explicitly selected project, verifies every registration and peer identity,
  and returns one detached aggregate local projection;
- `PrivateOperatorIPCRegistration`: strict frozen registration schema;
- `private_operator_ipc_unavailable(reason_code)`: fixed, local-only failure
  projection without paths or exception text.

`scripts/runner_cli.py` owns server lifecycle integration and invokes the
client for local status. These shared/public modules must not import the IPC
module or receive any IPC values:

- `runner/mcp_server.py`;
- `runner/runtime_observability.py`;
- `runner/web_console.py`.

## Service selection without lifecycle-metadata or argv trust

The private IPC client does not trust `ServiceLifecycleStore` metadata as an
identity root. Its current pathname storage is not protected by pinned dirfds,
and its recorded command or `/proc/<pid>/cmdline` may contain authentication
arguments. The IPC client must not read lifecycle `command`, process cmdline,
process environment, logs, or any other credential-adjacent process state.

Instead, the client enumerates only the pinned private registration root while
holding `registry.lock`. The directory may contain that one reserved lock leaf
and at most 64 names matching `service-[1-9][0-9]{0,9}.json`. Unknown names,
excessive entries, unsafe leaves, or enumeration failure make the observation
unavailable. Each candidate is opened and parsed through the secure
registration path described below, then filtered by the requested canonical
project's fingerprint.

For every matching registration, the client opens a pidfd and reads only
`/proc/<pid>/stat` start ticks. Zero live generation-matching registrations is
always `unavailable` with `OPERATOR_PRIVATE_REGISTRATION_NOT_FOUND`; the
registry-only client cannot distinguish a stopped service from a running
service whose IPC startup failed. When an exact project path is supplied,
every live generation matching that project is selected. Without an exact
project path, more than one live generation remains
`OPERATOR_PRIVATE_SERVICE_AMBIGUOUS`. The client never scans arbitrary PIDs,
picks the first registration, or guesses an endpoint.

The stat parser locates the final `)` terminating the parenthesized `comm`
field, then indexes the remaining fields; it never uses a naive whole-line
space split. Missing, malformed, boolean-like, zero, or out-of-range start ticks
are invalid.

After selection, the client retains every pidfd and frozen process start tick.
It keeps every pidfd open until all responses and all post-query registrations
have been fully validated, and uses zero-timeout polling before connect and
after each response; a readable pidfd means that process exited. A dead pidfd,
PID reuse, changed start identity, unreadable process identity, connection
failure, malformed response, or changed registration from any selected
instance fails the whole observation closed. The client never reports a
partial count.

Only after every instance passes does the client sum the per-process quarantine
counts. The aggregate is bounded by `65535 * 64`; its attention state and fixed
local alert are recomputed from the sum. The aggregation is diagnostic-only and
does not change authorization or any public surface.

## Private registration root

The preferred root is `$XDG_RUNTIME_DIR/colameta/private-operator-health`. The
existing XDG runtime directory must be a real directory owned by the effective
UID and not group- or other-writable. It must already exist. ColaMeta may create
exactly `colameta` and then `private-operator-health`, each under the pinned
parent fd. Creation uses mode `0700`, immediate `fchmod(0700)`, `fstat` identity
and ownership verification, and parent-directory `fsync` before continuing.
An existing component is validated, never chmod-repaired.

If `XDG_RUNTIME_DIR` is absent, the only fallback is
`<user_config_dir>/runtime/private-operator-health`. The user config directory
must already exist and pass ownership/non-writability validation; ColaMeta may
create exactly `runtime` and `private-operator-health` under pinned fds using
the same create-and-verify sequence. There is no `/tmp` fallback. Every
existing component is opened relative to the previous descriptor with
`O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`. The final root must be current-UID `0700`;
unsafe existing objects are rejected without permission repair.

The service retains the pinned root fd until shutdown. Registration create,
replace, read, and cleanup all use the pinned fd. A registration read opens the
leaf with `O_NOFOLLOW|O_CLOEXEC`, then verifies regular-file type, UID, exact
mode, link count, and size through `fstat` before reading. Temporary creation,
file `fsync`, atomic `renameat`, directory `fsync`, and `unlinkat` stay beneath
the same root fd.

The root contains one reserved `registry.lock` leaf plus at most 64 registration
leaves. The lock is a current-UID regular file with mode `0600`, opened with
`O_NOFOLLOW|O_CLOEXEC`, verified by `fstat`, and held exclusively for every
enumeration, publish, GC, and cleanup operation. Temporary leaves exist only
while that lock is held. An unexpected leaf or saturation fails closed.

All owned descriptors have one owner and are closed on every exit. Close
failures use the existing private fd-quarantine mechanism in the process that
owns the fd; service and CLI quarantine deltas are kept distinct. Descriptor
numbers are never projected.

## Registration and generation

Each service start creates a random 128-bit `instance_id`, reads its immutable
Linux process start ticks, binds the abstract socket, and then publishes
`service-<pid>.json`:

```json
{
  "schema_version": "colameta.private_operator_health_registration.v1",
  "pid": 1234,
  "process_start_ticks": 987654,
  "instance_id": "0123456789abcdef0123456789abcdef",
  "project_fingerprint": "64-lowercase-hex-characters"
}
```

The project fingerprint is SHA-256 over the canonical real project root. The
registration contains no count, alert, socket path, project name, OAuth data,
ticket, batch, claim, token, descriptor, or error text. Its schema is exact-key;
duplicate or unknown JSON keys are invalid.

The client derives the abstract address only after validating the registration:

```text
NUL + "colameta.private-attention.v1." + decimal_uid + "." + instance_id
```

The abstract address is not a secret. Its purpose is generation routing. The
kernel removes it automatically when the listener closes, so there is no
socket pathname, socket symlink, stale socket leaf, chmod, or unlink race.

Registration is published only after bind and listen succeed. A client performs
only the bounded, strict-name registration enumeration above; it never scans
process argv or guesses instances. The chosen registration PID, process start
ticks, project fingerprint, and instance ID are frozen before connect and
rechecked after response validation.

### Registration CAS and bounded GC

Every validated registration freezes `st_dev`, `st_ino`, its full canonical
JSON, PID, start ticks, instance ID, and project fingerprint while the pinned
root and registry lock are held. Before cleanup, code reopens the same name with
`O_NOFOLLOW`, repeats `fstat` and full-schema validation, and requires the inode
identity and full canonical record to equal the frozen expected registration.
The full reopen-and-compare is repeated immediately before `unlinkat`; only
then may unlink and root-directory `fsync` run. A currently different
inode or record, root identity change, parse failure, or compare failure leaves
the leaf untouched and returns a fixed unavailable state. This is an exact
cooperative CAS under `registry.lock`, not a kernel-atomic conditional unlink
and not historical ABA detection. A same-UID process that ignores the advisory
lock remains inside the stated same-UID threat limitation. If the exact original
inode and record were temporarily renamed and fully restored, deleting that
exact object is allowed.

At server startup, bounded GC may inspect all strict-name registrations under
the same lock. It deletes only a fully validated generation
whose pidfd/start-time evidence proves that generation is dead. A live
generation is never removed. Unsafe or unparsed leaves are never followed,
opened as special files, repaired, or bulk-deleted. More than 64 registrations
is saturation and prevents IPC publication/query until locally resolved. A
client query is read-only: it validates and rejects stale registrations but
does not delete them.

## Peer authentication and bounded transport

The client obtains `SO_PEERCRED` immediately after connect and requires:

- peer UID equals the effective UID;
- peer PID equals the selected and registered service PID;
- peer PID start ticks equal the frozen registration;
- pidfd still represents a live process before request and after response.

The server obtains `SO_PEERCRED` before reading and requires the peer UID to
equal its effective UID and the peer PID to be positive. Client PID is not
logged or returned. A denied peer is closed without a response. Same-UID access
is acceptable only because the payload is minimal read-only diagnostics and
carries no authorization. Abstract names can be visible in local kernel socket
tables, so an unauthorized local process may still cause bounded diagnostic
unavailability by filling the backlog; this never yields data or authority.

Listener backlog is at most 4. A single bounded worker serves connections
sequentially. Accept, receive, and send deadlines are 250 ms. Exactly one
request and one response `SOCK_SEQPACKET` record are allowed per connection,
each at most 1024 bytes. Idle or flooding clients cannot create unbounded
threads, queues, descriptors, or memory.

Receive uses `recvmsg(1025)` and rejects `MSG_TRUNC` or a record longer than
1024 bytes. After parsing the first request and before sampling, the server uses
nonblocking poll/peek to reject an already-queued second record. The client uses
the same truncation checks and rejects an already-queued second response.
Accept timeout is a normal loop event, not listener failure. Tests enqueue both
records before the first receive to make the second-record case deterministic.

## Exact protocol

Request:

```json
{
  "protocol": "colameta.private_attention.v1",
  "operation": "read_attention",
  "instance_id": "0123456789abcdef0123456789abcdef",
  "project_fingerprint": "64-lowercase-hex-characters",
  "nonce": "32-lowercase-hex-characters"
}
```

Response:

```json
{
  "protocol": "colameta.private_attention.v1",
  "operation": "read_attention_result",
  "instance_id": "0123456789abcdef0123456789abcdef",
  "project_fingerprint": "64-lowercase-hex-characters",
  "nonce": "exact-request-nonce",
  "quarantined_close_fd_count": 1,
  "quarantine_attention_threshold": 1,
  "quarantine_status": "attention",
  "local_alert_code": "OPERATOR_FD_QUARANTINE_ATTENTION"
}
```

Both parsers reject invalid UTF-8, invalid JSON, duplicate keys, unknown keys,
wrong types, invalid regex values, trailing/second packets, and oversize
records. The count must be a non-boolean integer in `0..65535`. The threshold is
exactly `1`. The client recomputes status and alert consistency from the count.
The nonce prevents response mix-up; it is not an authorization secret.

If the in-process supplier produces a count outside `0..65535`, inconsistent
fields, or raises, the server sends no snapshot and marks only the private IPC
request unavailable. It does not clamp, wrap, cache, or reuse an older value,
and the public service remains unaffected.

No request or response carries a path, PID, start ticks, descriptor, ticket,
batch, claim, OAuth value, provider data, exception, traceback, or command.

## Local projection

A verified response becomes:

```json
{
  "observation_source": "service_private_ipc",
  "observation_status": "observed",
  "quarantined_close_fd_count": 1,
  "quarantine_attention_threshold": 1,
  "quarantine_status": "attention",
  "local_alert_code": "OPERATOR_FD_QUARANTINE_ATTENTION"
}
```

Failure becomes:

```json
{
  "observation_source": "service_private_ipc",
  "observation_status": "unavailable",
  "quarantined_close_fd_count": null,
  "quarantine_attention_threshold": 1,
  "quarantine_status": "unknown",
  "local_alert_code": "OPERATOR_PRIVATE_HEALTH_UNAVAILABLE",
  "reason_code": "OPERATOR_PRIVATE_IPC_UNAVAILABLE"
}
```

Only fixed enumerated local reason codes are accepted. Raw errors, endpoint
names, instance IDs, nonces, project fingerprints, PIDs, start ticks, and fd
identities never reach output or logs. No matching registration produces
`observation_status=unavailable`, `quarantine_status=unknown`, and the fixed
local unavailable alert; it never produces `clear`. The ordinary service-status
fields may independently say the service is stopped, but the private IPC
projection does not infer `not_running` from absence.

Both local commands use this projection. The existing direct calls to the CLI
process's `private_operator_local_runtime_status()` are removed from their
output paths.

`colameta status <project_path>` filters registrations by that exact canonical
project fingerprint and aggregates all validated instances for only that
project. `colameta operator-config status` remains usable without a project
argument only when exactly one live validated registration exists across all
projects. Zero is unavailable/no-registration; more than one is ambiguous.
It may additionally accept an explicit `--project-path <path>` to select by
fingerprint and enable same-project aggregation. It must never pick the first
registration, reuse a last-selected project implicitly, aggregate across
different projects, or cross-read another project.

### Descriptor outcome semantics

- Listener and accepted sockets plus the service root/lock/registration fds are
  service-owned; client socket, pidfd, and client root/lock/registration fds are
  CLI-owned.
- A client-owned close failure before the query function returns changes the
  local result to unavailable and increments only the CLI process quarantine.
- An accepted-socket close failure after a valid response was sent does not
  retroactively invalidate that snapshot. It increments the service quarantine,
  so the next query observes attention.
- Listener or service-root close failure occurs during shutdown and has no
  synthetic client result; it increments only the service quarantine.
- A rejected peer receives no payload. Internal denial reasons are asserted by
  service-side test observation, not supplied to that peer.
- Every fd-failure matrix row records owner process, failure phase, whether a
  response was sent, whether the supplier ran, peer payload presence, service
  and CLI quarantine deltas, and closure of all non-quarantined fds.

## Lifecycle and restart semantics

The listener starts after project/service validation and before public MCP or
Web worker threads. IPC startup failure does not add a public endpoint or weaken
operator authorization. The service may continue, but local status reports the
fixed unavailable state.

The coordinator owns one server object and closes it from a unified `finally`
covering normal stop, SIGTERM, keyboard interrupt, worker startup failure,
worker death, and every early return after registration. Shutdown stops accept,
closes the listener, joins the IPC worker, securely removes only the exact
verified registration through the pinned root, closes remaining descriptors,
and releases the root fd.

Each exit-edge integration test asserts listener stop, worker join, exact
registration CAS cleanup, and descriptor ownership. IPC startup failure leaves
no registration. A supplier exception terminates only that connection, never
the public MCP/Web service, and never returns a cached snapshot. Cleanup failure
preserves the replacement or unverified leaf and reports only a local fixed
failure.

An abrupt exit leaves at most a stale private registration. Clients reject it
because the PID/pidfd/start-time checks fail. A later service removes a stale
registration only after strict parsing and proof that its PID is dead or has a
different process generation. It never unlinks an unsafe, wrong-owner,
wrong-mode, unparsed, or live registration.

A restarted service has a new process generation and instance ID. The
quarantine count is not stored in the registration or restored, so an
authenticated observation begins at zero. Responses from the previous
generation are rejected.

## Public-surface exclusion

Runtime conformance tests must invoke the final public surfaces and prove the
absence of `private_operator_runtime`, `service_private_ipc`, quarantine fields,
both local alert codes, instance/nonce/peer/process fields, and IPC reason
codes. Coverage includes:

- MCP `tools/list` and each of the seven descriptors by name;
- final `_call_tool` results for a read workflow and an operator workflow;
- MCP `/healthz` and Web `/api/healthz`;
- connector runtime health and Apps smoke packets;
- public error projections and OpenAPI output.

Source-boundary tests reject imports of the IPC module from `mcp_server`,
`runtime_observability`, and `web_console`. Matrix rows supply concrete handler
names and request objects, recursively scan the final handler value, and prove
that each row's input reached the intended handler. Separate positive local-CLI
rows prove the private projection appears only in `colameta status` and
`operator-config status`. Log-capture tests reject registration data, protocol
packets, PIDs, instance IDs, nonces, fd identities, and raw exceptions.

## Implemented validation gates

1. Implement strict schema, secure registration root, registration discovery,
   pidfd/start-time identity, and fixed unavailable projections.
2. Implement abstract-socket server/client, bounded protocol, peer checks, and
   unified descriptor cleanup.
3. Integrate the server into foreground `serve`, detached service children, and
   standalone `mcp-http-server`; integrate the client into both local commands.
4. Remove every CLI-process gauge fallback.
5. Make `jenn-private-operator-local-ipc-negative-test-matrix.json` directly
   drive one parameterized test. A meta-test validates each action's exact
   driver schema, fails on unknown actions or fields, records every consumed
   driver-field path, records every asserted expected-field path, and rejects
   duplicate, ignored, partially asserted, or unexecuted rows.
6. Add real subprocess restart/multi-fd tests and final public handler
   conformance; then run targeted tests, compileall, full pytest,
   self-hosting smoke, and `git diff --check`.

The implementation follows this order. The 154-row JSON matrix directly drives
`test_negative_matrix_case`; its companion meta-test enforces unique case IDs,
the exact action schema, complete driver-field consumption, complete expected
leaf assertion, and complete action routing. Real subprocess cases cover a new
service generation and a multi-fd attention snapshot. These local changes do
not authorize service restart, stable replacement, publish, push, provider
changes, or execution of a real Operator batch.
