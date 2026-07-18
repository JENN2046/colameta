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
Stable runtime baseline: `8639e83d6a7a572e1db1be26267aef7737313643`

Public remote MCP preflight at that baseline:

- expected and loaded runtime heads matched;
- `runtime_loaded_code_stale=false`;
- `reload_needed_for_verification=false`;
- health, MCP, and protected-resource metadata endpoints returned expected status.

Apps connector smoke at that baseline:

- connector runtime health: `healthy`;
- operator closeout: `connector_closeout_ready`;
- evidence gap count: 0;
- stable replacement status: `stable_aligned`.

The submission annotation changes were committed in
`9cf53f07378aec0ac33d9792dddec58546fb1d6f`, deployed to the stable/public
runtime, and verified with the same expected-head-bound checks. Rerun those
checks if the MCP server or runtime release changes before submission.

## review_status
Source review found no normal-profile tool inputs requesting credentials, MFA,
payment, government-ID, biometric, or health data. Commander widget CSP contains
no external connect or resource domains. Human security/privacy review is still
required before marking `security_review_ready=true`.
