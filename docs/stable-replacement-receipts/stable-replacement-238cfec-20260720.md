# Stable Replacement Receipt: 238cfec

## Summary

```yaml
date: 2026-07-20
recorded_at_utc: 2026-07-20T15:02:14Z
authorized_target_commit: 238cfec7fa2925f4383786278e34c07dedcb23e4
previous_stable_head: fcfab88b5feed0cdf669905b085775c39f8ca621
stable_runtime_dir: /home/jenn/tools/colameta
project_root: /home/jenn/src/colameta-dev
stable_replacement_result: complete
product_e2e_result: partial
```

Jenn explicitly authorized stable replacement, service restart, read-only
health verification, and a controlled two-tier acceptance. The exact target
was the merged `main` commit for PR 177.

## Preflight And Rollback

The source and stable tracked worktrees were clean. The two MCP origin services
were active/running and served the previous stable head before replacement.
Only path, ownership, mode, Git, selected systemd state, and allowlisted health
facts were inspected; no credential, token, cookie, browser state, private
configuration content, provider payload, or raw log was read.

```yaml
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-238cfec-20260720T145000Z.tar.gz
backup_sha256: a7a62bd15f060f4a495e386e70ae189e41863d7c15bd1e3125b363b3d68668b8
backup_size_bytes: 4159656
backup_validation: gzip_test_passed
backup_scope: previous stable tracked tree only
rollback_ref: stable-backup/fcfab-20260720
```

Two pre-existing untracked `Zone.Identifier` files in the stable checkout were
preserved and were not opened.

## Replacement

The stable checkout fetched the exact commit from the local project, switched
to detached `238cfec7fa2925f4383786278e34c07dedcb23e4`, and reinstalled the
package locally with `--no-deps --force-reinstall`.

```yaml
built_wheel_sha256: f1aeeb15972018c96cba5040393e65148898cfdcc783e25287d4cbf2ad2d55a7
package_reinstall_result: success
service_restart:
  colameta-stable.service: success
  colameta-mcp-remote.service: success
service_state_after_restart:
  colameta-stable.service: active/running
  colameta-mcp-remote.service: active/running
```

The Operator security stores initially failed closed because the existing
ColaMeta config and runtime directories were mode `0755`; the implemented
contract requires `0700`. Their permissions were narrowed to `0700`, no file
content was read, and the two MCP services were restarted again. Secure IPC
registration files then appeared with private modes.

## Runtime Verification

Both loopback origins, `127.0.0.1:8766` and `127.0.0.1:8767`, returned
allowlisted health evidence proving:

```yaml
ok: true
runtime_project_checkout_head: 238cfec7fa2925f4383786278e34c07dedcb23e4
runtime_loaded_code_stale: false
reload_needed_for_verification: false
installed_package_matches_project_checkout: true
installed_package_verification_status: match
```

The Commander surface exposed exactly seven tools. A live read-only call listed
five registered projects and confirmed `colameta-self-dev` with
`available=true` and `runner_managed=true`. The Apps smoke packet reported the
runtime aligned and not stale.

The public edge initially returned HTTP 530 while both origins and tunnel
services were locally healthy. A configuration-preserving restart of
`cloudflared-colameta-mcp-prod.service` restored public `/healthz` to HTTP 200;
the public response then proved the same exact runtime head and package match.

## Default Tier Acceptance

The live loopback Commander endpoint returned the exact seven-tool inventory,
read the registered project list, and returned the read-only smoke packet.
With the private Operator profile disabled, an actual `operator_batch` preview
was denied with the public allowlisted code `OPERATOR_PROFILE_DISABLED`. No
production execution permit or write was created.

## Controlled Operator Acceptance

Because no production Jenn/CIMD principal binding exists, production identity
was not fabricated. The installed stable package was instead exercised against
an isolated temporary project and private store with a synthetic, non-provider
principal. One `small_project_patch` preview was bound into one canonical
Operator ticket and dispatched through the real project-patch handler.

```yaml
required_scopes:
  - mcp:commit
requires_confirmation: true
execute_state: consumed
step_status: succeeded
real_handler_effect_observed: true
durable_ticket_state: consumed
replay_result: OPERATOR_TICKET_NOT_PENDING
public_execute_fields_allowlisted: true
temporary_state_removed: true
```

A separate isolated secure-registration IPC acceptance observed
`service_private_ipc`, a clear quarantine state, count zero, and threshold one.
It returned no descriptor identity.

## Remaining Product Gates

The real Auth0/ChatGPT remote-controlled tier is not yet end-to-end ready:

1. The live protected-resource metadata still advertises only `mcp:read` and
   `mcp:preview`; it does not advertise `mcp:plan` or `mcp:commit`.
2. The production Operator profile is disabled and no Jenn/CIMD principal
   fingerprints are configured.
3. No ChatGPT private App/CIMD client exists, so no real OAuth token or consent
   flow was available for acceptance.
4. Three running MCP services register private attention for the same project.
   The current CLI selector correctly fails closed as
   `OPERATOR_PRIVATE_SERVICE_AMBIGUOUS`, so it cannot yet observe one selected
   production process. No registration content was opened.

Auth0 discovery continued to advertise authorization code, refresh token,
PKCE, `private_key_jwt`, `none`, and CIMD support. This is discovery evidence,
not proof that a client or mutation scopes are configured.

## Boundary

No Git push, tag, release, package publication, ChatGPT App publication,
submission, provider configuration change, DNS change, tunnel configuration
change, executor run, source-project mutation, or credential read occurred.
The only non-temporary configuration mutations were narrowing two local
directory modes to `0700`. This receipt does not authorize another stable
replacement, service restart, OAuth/provider change, or public release.
