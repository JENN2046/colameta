# Stable Replacement Receipt — 064f622

```yaml
receipt_type: stable_replacement
recorded_at: 2026-09-06T01:24:01Z
result: passed
authorization:
  target_commit: 064f622bc1e388c18aacb91cc9d500ff2e2bff13
  restarted_services:
    - colameta-stable.service
    - colameta-mcp-remote.service
  unchanged_surfaces:
    - tunnel
    - DNS
    - OAuth
    - MCP registration
    - advanced service
    - private-beta target
candidate:
  origin_main: 064f622bc1e388c18aacb91cc9d500ff2e2bff13
  tree: beb3327e47a869fdb91eb880141dfa53a9bee4d0
  exact_main_ci: https://github.com/JENN2046/colameta/actions/runs/34002272186
  exact_main_ci_result: success
previous_stable:
  commit: fa535cd97df84ce67b0e950cb94714b40978f38f
  backup_archive: /home/jenn/tools/colameta-stable-backups/stable-before-064f622-20260906T011858Z.tar.gz
  backup_sha256: 6068d4c004d1f98ef4a5a4d3184ae9f3dbcffd6d1fd8a026bf2db07567526e9d
  rollback_ref: refs/heads/stable-backup/fa535cd-20260906T011858Z-before-064f622
installed_candidate:
  stable_checkout: /home/jenn/tools/colameta
  detached_head: 064f622bc1e388c18aacb91cc9d500ff2e2bff13
  retained_wheel: /home/jenn/tools/colameta-stable-backups/wheel-064f622-20260906T011858Z/colameta-0.1.2-py3-none-any.whl
  retained_wheel_sha256: 76989d5e0432eebf95d5c8e8b6e7582cbb9af67c78b2d8b5a38ef9b3ef258e03
  final_install_source: file:///home/jenn/tools/colameta
  pip_check: passed
runtime:
  stable_web_http: 200
  stable_commander_mcp_http: 200
  remote_mcp_http: 200
  public_https_health_http: 200
  public_protected_resource_metadata_http: 200
  unauthenticated_public_mcp_http: 401
  runtime_project_checkout_head: 064f622bc1e388c18aacb91cc9d500ff2e2bff13
  installed_package_matches_project_checkout: true
  installed_package_project_source_clean: true
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  commander_visible_tool_count: 9
  tunnel_pid_unchanged: 3415
read_only_acceptance:
  negative_intent_auto_preview: passed
  plain_project_status_auto_preview: passed
  public_profile_id: web_gpt_commander
  preview_ids: []
  gate_review_request_inspect: passed
  gate_review_side_effects: false
  connector_packet_local_runtime: healthy
  external_connector_replay: passed
  fresh_web_gate_a_live_access: passed
  fresh_web_gate_b_public_profile_contract: passed
  fresh_web_gate_c_negative_intent: passed
  fresh_web_gate_d_plain_project_status: passed
  fresh_web_gate_e_persona_preservation: passed
  authority_separation: passed
  severity_counts:
    P0: 0
    P1: 0
    P2: 0
```

The first retained-wheel installation restored the package but did not preserve
the checkout binding used by runtime provenance. Before final acceptance, the
same exact source was reinstalled from the detached stable checkout with
`--no-deps --force-reinstall`. Only the two authorized services were restarted
again. Final health evidence then bound all three served endpoints to the exact
target and cleared both loaded-code freshness signals.

Direct Commander `tools/list` returned the expected nine-tool catalog. The two
R1 read-only `auto_preview` reproducers selected `project_status`, preserved
`web_gpt_commander`, emitted no preview IDs, and reported no side effects. The
local connector smoke packet could not by itself prove an actual external App
call and therefore initially left two external evidence gaps. A subsequent
Fresh Web GPT replay against this exact Stable passed live access, public
`profile_id` schema discovery, both exact `auto_preview` reproducers, caller
persona preservation, and authority separation. It reported no public
projection errors, no preview IDs, and severity counts `P0=0`, `P1=0`, and
`P2=0`.

The Fresh Web runtime cross-check observed the exact target in both the runtime
checkout and installed-package project head, package verification `match`, no
loaded-code staleness, no reload requirement, and 38 of 38 loaded module
fingerprints verified. Process-level `loaded_runtime.head` remained unavailable
because the installed package has no Git directory; the package/source and
module-fingerprint evidence closed that observability condition without
weakening the acceptance gate.

No Git push, tag, release, DNS change, tunnel restart, OAuth change, MCP
registration change, advanced-service installation or start, private-beta
target change, executor run, validation run, ReviewDecision, GateEvent, or
delivery-state mutation was performed.
