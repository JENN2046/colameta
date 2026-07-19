# Read-Only Soak Receipt — b6c864c — 2026-07-19

## Scope

This receipt records a bounded read-only observation window after the explicitly
authorized stable replacement to
`b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29`. No service restart, replacement,
configuration change, Dashboard write, credential read, or submission action
was performed during this soak.

## Observation window

```yaml
first_sample_utc: 2026-07-19T07:00:27Z
last_sample_utc: 2026-07-19T07:10:06Z
observed_window: 9m39s
sample_count: 6
stable_target: b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29
```

## Samples

| UTC | Stable/remote/tunnel state | Health provenance | Connector evidence |
|---|---|---|---|
| 07:00:27 | active/running; PID 19087/19096/59509; NRestarts 0 | local, remote, public exact b6; clean; not stale | seven-tool and Stage 0–6 match |
| 07:02:04 | active/running; same PIDs; NRestarts 0 | local, remote, public exact b6; clean; not stale | ready/healthy; zero gaps |
| 07:03:58 | active/running; same PIDs; NRestarts 0 | local, remote, public exact b6; clean; not stale | `colameta-self-dev` available and Runner-managed |
| 07:06:13 | active/running; same PIDs; NRestarts 0 | local, remote, public exact b6; clean; not stale | public preflight passed; failures empty |
| 07:07:14 | active/running; same PIDs; NRestarts 0 | local, remote, public exact b6; clean; not stale | ready/healthy; zero gaps |
| 07:10:06 | same PIDs present and running; user bus unavailable | local, remote, public exact b6; clean; not stale | no connector drift observed |

At 07:08:48Z an additional endpoint-only observation passed for all three
health endpoints. The shell could not connect to the user service-manager bus at
that instant, so that observation is not counted as proof of service-manager
state or restart counters.

## Result and limits

The bounded window found no loaded-code drift, package mismatch, endpoint
failure, connector evidence gap, or observed process replacement. This is a
short post-replacement soak only; it is not evidence for a 24-hour or 72-hour
reliability claim and does not make the submission ready.

The separate submission review identified unresolved authenticated Dashboard,
web/mobile, and public-response data-minimization gates. See
`docs/submission/dashboard-review-20260719.md` and
`docs/submission/security-review.md`.
