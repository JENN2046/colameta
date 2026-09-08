# Stable replacement receipt: ca29480 (2026-09-05)

## Result

`PASS`

The stable ColaMeta checkout and installed runtime were replaced from
`30272552053699e84568b615f8c1d56390c39236` with the exact merged `main`
commit `ca294802f02d7a3d9d50cd9f64c0a04b4a432ff5`. The final Web and MCP health
responses report the target checkout, `runtime_loaded_code_stale=false`,
`reload_needed=false`, and an installed package that matches the project
checkout.

## Authorization and boundary

Jenn explicitly authorized replacement to
`ca294802f02d7a3d9d50cd9f64c0a04b4a432ff5`, with restarts limited to:

- `colameta-stable.service`;
- `colameta-mcp-remote.service`.

No tunnel, DNS, OAuth, provider, advanced-service, or private-beta target
configuration was changed. No advanced service or private-beta target was
installed. No tag, release, package publication, migration, or production data
write occurred.

## Source and CI evidence

- Target commit:
  `ca294802f02d7a3d9d50cd9f64c0a04b4a432ff5`.
- Target subject: `Merge pull request #213 from JENN2046/codex/live-acceptance-fix-pack`.
- The target was verified as the GitHub `origin/main` head before replacement.
- GitHub Actions run `33943937469` completed successfully for the merged
  commit, including Python 3.10 through 3.14 and the quality gates.
- Stable checkout after replacement: detached at the exact target, with no
  tracked changes.

## Rollback and artifact evidence

Before changing the stable checkout, the previous stable tree was archived and
a dedicated local rollback ref was created.

```text
previous_commit: 30272552053699e84568b615f8c1d56390c39236
rollback_ref: stable-backup/3027255-20260905T080001Z-before-ca29480
backup: /home/jenn/tools/colameta-stable-backups/stable-before-ca29480-20260905T080001Z.tar.gz
backup_size: 5150021 bytes
backup_sha256: 1d1e830bca2818a7b029630ebd74547707dad2c6488cbef8130c8107aaffda48
wheel: /home/jenn/tools/colameta-stable-backups/colameta-ca29480-20260905T080001Z.whl
wheel_size: 1706297 bytes
wheel_sha256: b775e57c847b2208a56f9bffa45ba660ca64bae7a25dec4167038455e280ffe6
```

The gzip archive integrity check and the retained wheel ZIP integrity check
both passed. The rollback ref resolves to the recorded previous commit.

## Installation

The stable virtual environment did not contain the `setuptools` build backend,
so the first direct build command stopped before package installation or any
service restart. A wheel was then built from the exact stable checkout with the
validated development build environment, using `--no-deps` and
`--no-build-isolation`, and installed into the stable virtual environment.

The initial wheel install did not preserve source provenance in
`direct_url.json`; health remained conservative and reported the source binding
as unverified. The package was therefore reinstalled from the exact stable
checkout with the same no-dependency, no-build-isolation boundary. The final
installed metadata binds the package to `/home/jenn/tools/colameta`, and all
runtime provenance checks pass.

Only the two authorized services were restarted. They were restarted once after
the wheel install and once after the source-bound reinstall:

```text
colameta-stable.service: active, result=success, final PID 2226825
colameta-mcp-remote.service: active, result=success, final PID 2226853
```

## Runtime verification

Final loopback health results:

- Web `127.0.0.1:8801/api/healthz`: healthy and bound to the exact target;
- Commander MCP `127.0.0.1:8766/healthz`: healthy, auth mode `none`, routing
  profile `registry`;
- remote-origin MCP `127.0.0.1:8767/healthz`: healthy, auth mode
  `external-oauth`, routing profile `registry`.

All three report:

```text
runtime_project_checkout_head: ca294802f02d7a3d9d50cd9f64c0a04b4a432ff5
runtime_loaded_code_stale: false
reload_needed: false
installed_package_matches_project_checkout: true
source_worktree_clean: true
```

The installed `runner` module resolves inside the stable virtual environment.
Ports 8801 and 8766 are owned by the final `colameta-stable.service` process;
port 8767 is owned by the final `colameta-mcp-remote.service` process. Port 8768
remains absent, as expected for the explicitly excluded advanced service.

## Commander and connector acceptance

The stable Commander endpoint returned exactly these nine public tools:

```text
list_registered_projects
get_apps_connector_smoke_packet
render_commander_app
analyze_project_state
review_manifest
read_result_artifact
run_mcp_workflow
manage_validation_run
manage_git
```

Read-only acceptance results:

1. `list_registered_projects` returned `ok=true` and included
   `colameta-self-dev`.
2. `analyze_project_state(project_name="colameta-self-dev")` returned
   `ok=true`, `read_only=true`, `side_effects=false`, and
   `visible_tool_count=9`.
3. `run_mcp_workflow(workflow="gate_review_request", phase="inspect")`
   returned `status=succeeded`, `read_only=true`, `side_effects=false`, and one
   existing sanitized candidate. No preview or transition was requested.
4. `get_apps_connector_smoke_packet`, supplied only the allowlisted service
   status, reason code, evidence source, and observation time, returned
   `overall_status=healthy`, `connector_closeout_ready`, `evidence_gap_count=0`,
   `read_only=true`, and `side_effects=false`.

No Work Item, ReviewDecision, GateEvent, Delivery State transition, executor
run, validation run, Git write, or confirmation-bearing preview was created by
these acceptance calls.

## Unchanged surrounding services

The tunnel services remained active with their pre-replacement PIDs and start
times:

```text
cloudflared-colameta-mcp-prod.service: PID 3415, active since 2026-08-30 04:25:23 HDT
colameta-tunnel-client.service: PID 3157, active since 2026-08-30 04:25:22 HDT
```

This confirms they were not restarted during the replacement. Their private
configuration, credentials, raw logs, and provider responses were not read.

## Closure

The stable runtime is serving the authorized target with clean source and
verified installed-package provenance. Rollback material is present and
checksummed. This receipt authorizes no future replacement, restart, release,
or external configuration change.
