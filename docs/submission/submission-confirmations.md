# Submission Confirmations Evidence

## human_reviewer
Required reviewer: Jenn or an explicitly delegated submission reviewer.

## confirmed_items
Not yet confirmed. Before Dashboard submission, the human reviewer must confirm:

- stable/public MCP endpoint readiness is green;
- ChatGPT Apps connector smoke succeeds from the real external connector;
- logo and screenshots are final;
- localized listing text and screenshots are final;
- test prompts and test responses have been rerun from the real ChatGPT Apps
  surface;
- security/privacy review is complete;
- app management permissions are verified in the OpenAI Platform Dashboard;
- submission metadata matches the current MCP server snapshot;
- no token, cookie, credential, raw provider response, tunnel config, proxy
  config, or raw logs are included in submission evidence.

## submission_boundary
This repository evidence does not create an OpenAI App draft, submit the app for
review, publish a plugin/app, replace the stable service, or mark Delivery
accepted.

`submission_confirmations_ready` must remain false until the human reviewer
checks the final Dashboard form and explicitly approves submission.
