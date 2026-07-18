# Initial Plugin Submission Release Notes

ColaMeta is being submitted as an MCP-backed ChatGPT plugin for the first time.
It helps authorized operators inspect AI engineering project health, review
plans and evidence, run bounded validations and executor workflows, and manage
Git and release-readiness tasks through permission-scoped tools.

This submission provides:

- a production HTTPS MCP endpoint using external OAuth;
- 82 normal-profile tools with complete input and output schemas;
- explicit `readOnlyHint`, `openWorldHint`, and `destructiveHint` annotations
  with behavior-specific justifications for every tool;
- five positive and three negative reviewer test cases;
- desktop and narrow-viewport product evidence; and
- privacy, security, support, and terms documentation.

Review baseline:

- release commit: `9cf53f07378aec0ac33d9792dddec58546fb1d6f`;
- MCP endpoint: `https://colameta-mcp.skmt617.top/mcp`;
- submission inventory SHA-256:
  `35879d78190404893ad9fb6c2796e2a23e49ef4b39222492b8a7b09080cb643d`.

The reviewer account must be supplied through the OpenAI Platform submission
portal and tested without MFA, SMS, email confirmation, or private-network
access. Do not place reviewer credentials in this repository.
