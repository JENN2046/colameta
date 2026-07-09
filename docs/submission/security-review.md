# Security And Privacy Review Evidence

## least_privilege
The Commander and release-evidence draft paths are read-only. Write tools remain separate and require `mcp:commit` scope. Remote/public MCP policy denies commit/plan scopes unless explicitly authorized by the configured service policy.

## consent
The generated submission evidence payload is a preview only. Operators must review and replace any draft text before calling `fill_submission_evidence_files`. The preview keeps `mark_ready=false` by default.

## redaction
This draft is built from sanitized service facts: tool names, scopes, runtime freshness, and connector summary statuses. It does not read token values, cookies, browser login state, provider config, raw logs, tunnel-client config, or proxy config.

## privacy_policy
Privacy policy draft: docs/privacy-policy.md
Published candidate URL: https://github.com/JENN2046/colameta/blob/main/docs/privacy-policy.md
Human privacy review is still required before marking `security_review_ready=true`.

## monitoring
Runtime reload awareness: installed_package_project_checkout_dirty
Reload needed for verification: true
Connector overall status: local_runtime_observed_external_connector_unverified
Operator closeout status: local_service_attention_needed

## review_status
Human security/privacy review is still required before marking `security_review_ready=true`.
