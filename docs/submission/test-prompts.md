# Test Prompts Evidence

## prompt_id
T001

## prompt_text
List the registered ColaMeta projects available to the ChatGPT App connector.

## workflow_covered
Project discovery and project-name routing bootstrap.

## expected_tool_calls
`list_registered_projects` with empty arguments. Expected behavior: read-only project list response that includes `colameta-self-dev` without requiring a project selection side effect.

## prompt_id
T002

## prompt_text
Open the ColaMeta Commander manifest for `colameta-self-dev` and show the safe read actions and release evidence panel.

## workflow_covered
Commander manifest, Apps panel routing, release evidence section exposure, and read-only action inventory.

## expected_tool_calls
`get_commander_app_manifest` with `project_name=colameta-self-dev`. Expected behavior: read-only manifest with initial reads, read actions, and `release_submission_evidence` in the Commander panel sections.

## prompt_id
T003

## prompt_text
Show the Product Console map for `colameta-self-dev`, including release submission evidence progress.

## workflow_covered
Product Console summary, release submission evidence bundle, and blocked readiness surface.

## expected_tool_calls
`get_product_console_map` with `project_name=colameta-self-dev`. Expected behavior: read-only `product_console_map` response with release evidence progress and current blocker summary.

## prompt_id
T004

## prompt_text
Check release submission readiness for `colameta-self-dev` and list the current blockers and evidence counts.

## workflow_covered
Release submission readiness aggregation, product/public endpoint blockers, and submission evidence progress accounting.

## expected_tool_calls
`get_release_submission_readiness` with `project_name=colameta-self-dev`. Expected behavior: read-only readiness packet that remains blocked while product/public endpoint evidence is not ready.

## prompt_id
T005

## prompt_text
Generate a reviewable auto draft for MCP tool information evidence without writing files or marking ready fields.

## workflow_covered
Submission evidence auto-draft generation and write-boundary separation.

## expected_tool_calls
`get_submission_evidence_auto_draft` with `project_name=colameta-self-dev` and `selected_keys=["mcp_tool_info"]`. Expected behavior: read-only `draft_ready` response with a copyable `fill_submission_evidence_files` call where `mark_ready=false`.

## review_notes
These prompts cover read-only project routing, Commander surface metadata, Product Console readiness, release submission readiness, and submission evidence draft generation. They do not cover mobile UI screenshots, destructive/commit flows, public endpoint preflight, or manual Dashboard submission.
