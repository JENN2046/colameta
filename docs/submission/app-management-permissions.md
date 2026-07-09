# App Management Permissions Evidence

## owner
Repository owner: `JENN2046`.

Submission operator: Jenn, or a delegated operator with explicit access to the
OpenAI Platform plugin submission portal for the target organization.

## dashboard_access
OpenAI's plugin/app submission flow requires app management permissions before a
plugin containing an MCP-backed app can be drafted, submitted, reviewed, or
published.

This repository evidence does not prove that the current operator session has
`api.apps.write` or `api.apps.read` in the OpenAI Platform Dashboard. That
permission must be confirmed from the Dashboard before
`app_management_permissions_confirmed=true`.

## approval_notes
Keep this field unready until the human operator confirms:

- the submitting organization/account is correct;
- the operator has permission to create or update the plugin draft;
- the operator has permission to submit for review;
- the operator understands that publication is a separate manual action after
  approval;
- no agent is authorized to create drafts, submit review, or publish from this
  evidence alone.
