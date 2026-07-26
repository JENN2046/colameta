# Stable Replacement Receipt — 6c72507

```yaml
receipt_type: stable_replacement
recorded_on: 2026-07-26
result: passed
formal_audit_closeout:
  observed_at: 2026-07-26T14:05:29Z
  decision: passed
  engineering_baseline: 6c7250712cc2bc177e85bdbbcbbf4659556de815
  deployed_runtime_baseline: 6c7250712cc2bc177e85bdbbcbbf4659556de815
  commit_scope: receipt_only
  remote_delivery: not_performed
authorization:
  scope: "controlled deployment, service restart, and live readiness verification"
  target_commit: 6c7250712cc2bc177e85bdbbcbbf4659556de815
  no_push_tag_release_or_tunnel_restart: true
candidate_traceability:
  dev_repository: /home/jenn/src/colameta-dev
  candidate_head: 6c7250712cc2bc177e85bdbbcbbf4659556de815
  local_main_matches_origin_main: true
  exact_main_ci_run: https://github.com/JENN2046/colameta/actions/runs/30203790082
  exact_main_ci_result: passed
previous_stable:
  commit: 919a58a96787e8943923847257cc84692cad28ae
  backup_archive: /home/jenn/tools/colameta-stable-backups/stable-before-6c72507-20260726T134657Z.tar.gz
  backup_sha256: b63243e6d3db4f0281a9070182ba114194e8d0d783a8496cb66fd26723e8c334
  rollback_ref: stable-backup/919a58a-20260726-before-6c72507-20260726T134657Z
  preserved_untracked_files:
    - AGENTS.md:Zone.Identifier
    - AGENTS - 副本.md:Zone.Identifier
stable_action:
  stable_checkout_detached_head: 6c7250712cc2bc177e85bdbbcbbf4659556de815
  retained_wheel: /home/jenn/tools/colameta-stable-backups/wheel-6c72507-20260726T134657Z/colameta-0.1.2-py3-none-any.whl
  retained_wheel_sha256: 1652fcff5b00abc6f0cc25f24ca8ad9b0c64b8445fd38924cadc56e77f36aea2
  final_install_source: file:///home/jenn/tools/colameta
  final_install_bound_to_stable_checkout: true
  exact_added_runtime_dependency: PyYAML==6.0.3
  pip_check: passed
  systemd_unit_backup: /home/jenn/tools/colameta-systemd-backups/20260726T134812Z
  removed_stale_runtime_drop_in:
    path: /run/systemd/system/colameta-mcp-remote.service.d/90-colameta-dev-runtime.conf
    backup: /home/jenn/tools/colameta-systemd-backups/20260726T134812Z/90-colameta-dev-runtime.conf
    backup_sha256: 97595a6a42058dcec60bef6978ec98a3cc98721a16ea3f91c5a27679dc678360
  restarted_services:
    - colameta-stable.service
    - colameta-mcp-advanced.service
    - colameta-mcp-remote.service
  tunnel_restarted: false
```

## Formal audit closeout

The engineering baseline, deployed runtime, local `main`, and `origin/main` were
reconciled to exact commit
`6c7250712cc2bc177e85bdbbcbbf4659556de815`. The exact GitHub CI run was
re-read and remained completed with conclusion `success`. Backup, wheel, and
drop-in SHA-256 values were recomputed; the archive and wheel integrity checks
passed. Installed systemd unit fragments matched the repository copies
byte-for-byte.

Local health, package/source provenance, Cloudflare readiness, and the complete
public HTTPS MCP preflight were repeated at closeout time and passed. This
receipt therefore closes the audit record for `6c725071…` as the engineering
and deployed-runtime baseline. The dedicated audit commit containing this
document changes no implementation or runtime configuration and does not
replace the deployed-runtime SHA.

## Controlled installation

The retained wheel passed ZIP validation and was installed with
`--no-deps --force-reinstall`. The first dependency check detected that the new
candidate requires exact `PyYAML==6.0.3`. No service had been restarted at that
point. The exact dependency was installed, `pip check` passed, and only then did
the restart sequence begin.

The systemd installer updated the private-beta units and created the recorded
unit backup. A pre-existing runtime drop-in injected the development checkout
through `PYTHONPATH`, which made remote-service provenance unsuitable for a
stable replacement. The exact drop-in was backed up and removed, systemd was
reloaded, and the package was reinstalled from the exact detached stable
checkout. Final package metadata resolves to the stable checkout, and the
generated `build/` and `colameta.egg-info/` directories were moved, without
deletion, to:

```text
/home/jenn/tools/colameta-stable-backups/generated-build-6c72507-20260726T134657Z
```

The remote external-OAuth service now uses the repository contract's narrowed
scope set: `mcp:read,mcp:preview`. No runtime `PYTHONPATH` drop-in remains.

## Restart and local runtime verification

The three ColaMeta code services were restarted sequentially. A health gate was
required after each restart before proceeding to the next service. Final state:

```yaml
colameta-stable.service: active/running
colameta-mcp-advanced.service: active/running
colameta-mcp-remote.service: active/running
cloudflared-colameta-mcp-prod.service: active/running
```

Loopback Web and MCP health endpoints on ports `8801`, `8766`, `8767`, and
`8768` all returned HTTP 200 with `ok=true`. Every endpoint reported:

```yaml
runtime_project_checkout_head: 6c7250712cc2bc177e85bdbbcbbf4659556de815
installed_package_matches_project_checkout: true
installed_package_project_source_clean: true
runtime_loaded_code_stale: false
reload_needed_for_verification: false
```

The installed stable checkout remained tracked-clean; its two pre-existing
untracked `Zone.Identifier` files were preserved.

## Commander and connector acceptance

Direct `tools/list` on the stable Commander endpoint returned exactly nine
tools:

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

The live ColaMeta connector then passed these read-only checks:

1. `list_registered_projects` returned `ok=true` and included the available
   `colameta-self-dev` project.
2. `analyze_project_state` returned the Commander profile, exactly nine visible
   tools, clean `main`, and exact project HEAD `6c725071…`.
3. `run_mcp_workflow(workflow="gate_review_request", phase="inspect")` returned
   `status=succeeded`, `read_only=true`, `side_effects=false`, and
   `candidate_count=0`.
4. `get_apps_connector_smoke_packet`, using only sanitized loopback and public
   preflight evidence, returned overall connector health `healthy`,
   `connector_closeout_ready`, decision `ready`, and zero evidence gaps.

No executor run, validation run, Git write, ReviewDecision, GateEvent, or
Delivery state mutation occurred during these checks.

## Cloudflare and public HTTPS readiness

The existing Cloudflare connector was deliberately not restarted. Its original
PID remained active/running throughout deployment. Final sanitized evidence:

```yaml
cloudflared_ready_http: 200
cloudflared_tunnel_ha_connections: 4
public_https_preflight_ok: true
public_healthz_http: 200
public_mcp_readiness_http: 200
protected_resource_metadata_http: 200
public_runtime_head: 6c7250712cc2bc177e85bdbbcbbf4659556de815
public_runtime_loaded_code_stale: false
public_reload_needed_for_verification: false
```

The external authorization-server metadata endpoint is intentionally delegated
to the configured external OAuth provider. The preflight classified that
external-auth response correctly and reported no failure.

## Rollback boundary

Rollback is not automatic authority. If separately authorized, restore the
recorded archive or rollback ref to exact commit
`919a58a96787e8943923847257cc84692cad28ae`, restore systemd state from the
recorded backup as applicable, reinstall from the restored stable checkout,
restart only the three recorded ColaMeta code services, and repeat the local,
Commander, connector, and public HTTPS checks.

No Git commit, push, tag, release, PyPI publication, DNS change, tunnel route
change, credential read, tunnel restart, or provider configuration mutation was
performed as part of this replacement.
