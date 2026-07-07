# ColaMeta Remote HTTPS MCP Service

Status: implementation guardrails and operator runbook.

This document defines the safe path from the local/tunnel ColaMeta MCP setup to
a stable HTTPS remote MCP service for ChatGPT Developer Mode. It does not
authorize DNS, TLS, cloud resource creation, deployment, production routing, or
public app submission by itself.

## Target Contract

Use a stable HTTPS service base URL:

```text
https://mcp.example.com
```

Use this ChatGPT connector URL:

```text
https://mcp.example.com/mcp
```

Do not pass the `/mcp` connector URL as `--public-base-url`; ColaMeta appends
`/mcp` internally when it publishes protected-resource metadata.

OpenAI Apps SDK deployment guidance expects a stable HTTPS endpoint with
dependable TLS, low-latency responses on `/mcp`, and logs/metrics for failure
diagnosis. ChatGPT connector setup expects the public connector URL to be the
server's `/mcp` endpoint. Authenticated MCP servers are expected to implement an
OAuth 2.1 flow that follows the MCP authorization spec, including protected
resource metadata, OAuth metadata, PKCE S256, and per-request bearer token
validation.

Reference docs:

- https://developers.openai.com/apps-sdk/deploy
- https://developers.openai.com/apps-sdk/deploy/connect-chatgpt
- https://developers.openai.com/apps-sdk/build/auth
- https://developers.openai.com/apps-sdk/deploy/testing
- https://developers.openai.com/apps-sdk/deploy/submission

## Recommended First Production Shape

For Jenn-only remote operation:

```text
ChatGPT
  -> HTTPS public endpoint /mcp
  -> reverse proxy or managed ingress with TLS
  -> loopback ColaMeta MCP process
  -> /home/jenn/src/colameta-dev project state
```

Run ColaMeta on loopback behind the HTTPS ingress:

```bash
.venv/bin/colameta serve /home/jenn/src/colameta-dev \
  --no-web \
  --mcp-host 127.0.0.1 \
  --mcp-port 8766 \
  --auth-mode oauth \
  --public-base-url https://mcp.example.com
```

Equivalent source-only command:

```bash
.venv/bin/colameta mcp-http-server /home/jenn/src/colameta-dev \
  --host 127.0.0.1 \
  --port 8766 \
  --auth-mode oauth \
  --public-base-url https://mcp.example.com
```

The CLI now rejects remote `http://` URLs for OAuth MCP. Local `http://localhost`
and loopback URLs are still allowed only for local development.

## Reverse Proxy Requirements

The HTTPS proxy or ingress must:

- terminate TLS with a trusted certificate;
- route `GET /healthz`, `GET /mcp`, `POST /mcp`,
  `GET /.well-known/oauth-protected-resource`,
  `GET /.well-known/oauth-authorization-server`, `GET /authorize`,
  `POST /register`, `POST /token`, and `POST /revoke` to the loopback MCP
  process;
- preserve `Authorization`, `Content-Type`, and request bodies;
- avoid buffering or timing out long MCP responses too aggressively;
- log request id, method, path, status, latency, and upstream error class;
- never log bearer token values, cookies, authorization codes, or request bodies
  containing secrets.

Minimal proxy sketch:

```nginx
location / {
  proxy_pass http://127.0.0.1:8766;
  proxy_http_version 1.1;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-Proto https;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header Authorization $http_authorization;
  proxy_read_timeout 300s;
  proxy_buffering off;
}
```

This repository does not install or mutate the proxy config.

## Auth Boundary

Current ColaMeta OAuth support is built into `MCPOAuthProvider` and stores
clients/tokens in the project runtime store. This is acceptable only for a
single-node, Jenn-operated private connector after HTTPS, process isolation,
and access logging are in place.

Before public directory submission or multi-user exposure, replace or extend
the auth layer with an established identity provider or equivalent production
authorization server. The resource server must verify issuer, audience/resource,
expiration, replay risk, and required scopes on every request.

## External OAuth Resource Server Mode

For a production-grade ChatGPT connector, prefer `external-oauth`. In this mode,
ColaMeta is only the MCP resource server:

- `GET /.well-known/oauth-protected-resource` advertises the MCP resource and
  external authorization server issuer;
- `POST /mcp` requires `Authorization: Bearer <JWT>`;
- ColaMeta verifies the JWT against the external IdP JWKS, issuer,
  audience/resource, expiration/not-before, algorithm, and tool scopes;
- ColaMeta enforces the configured `--oauth-scopes` as the resource-server
  allowlist, not only as metadata;
- ColaMeta applies the `remote_public` tool policy after OAuth scope validation:
  read/preview tools are allowed, while every `mcp:commit` and `mcp:plan`
  action is denied before the tool handler runs;
- ColaMeta does not serve `/authorize`, `/register`, `/token`, or `/revoke`.

Example:

```bash
.venv/bin/colameta serve /home/jenn/src/colameta-dev \
  --no-web \
  --mcp-host 127.0.0.1 \
  --mcp-port 8767 \
  --auth-mode external-oauth \
  --public-base-url https://colameta-mcp.skmt617.top \
  --oauth-issuer https://YOUR_IDP_DOMAIN/ \
  --oauth-jwks-url https://YOUR_IDP_DOMAIN/.well-known/jwks.json \
  --oauth-audience https://colameta-mcp.skmt617.top/mcp \
  --oauth-scopes mcp:read,mcp:preview
```

The issuer, JWKS URL, audience, scopes, algorithms, and leeway are not secrets.
Do not put client secrets, bearer tokens, cookies, or refresh tokens in these
flags, service files, docs, receipts, or logs.

ChatGPT connector setup should use OAuth with the IdP as the authorization
server. Use a predefined client or the IdP's supported dynamic registration
flow, then set the connector URL to:

```text
https://colameta-mcp.skmt617.top/mcp
```

Do not grant `mcp:commit` or `mcp:plan` to public or default ChatGPT
connectors. Enabling remote write/plan operations requires a separate trusted
operator channel or local confirmation design; `external-oauth` public remote
mode is intentionally read/preview only.

The current `oauth` mode remains available for Jenn-only private operation and
local bring-up. Do not treat it as the long-term public or multi-user auth
boundary.

## Preflight

Shape-only check:

```bash
.venv/bin/python scripts/remote_https_mcp_preflight.py https://mcp.example.com --no-network
```

Live endpoint check after the HTTPS service exists:

```bash
.venv/bin/python scripts/remote_https_mcp_preflight.py https://mcp.example.com
```

Expected live checks:

- `/healthz` returns `service=colameta-mcp`, `ok=true`, and `auth_mode=oauth`
  or `auth_mode=external-oauth`;
- `/mcp` advertises the protected resource metadata URL and the same auth mode;
- `/.well-known/oauth-protected-resource` returns resource metadata for
  `https://mcp.example.com/mcp`;
- in `oauth` mode, `/.well-known/oauth-authorization-server` returns local
  authorization, token, registration, revocation, and PKCE S256 metadata;
- in `external-oauth` mode, the local authorization-server endpoint returns
  `EXTERNAL_AUTH_SERVER`, and clients must use the external IdP advertised in
  protected-resource metadata. The advertised external IdP must be a public
  HTTPS authorization server and must not be the MCP service base URL.

The preflight output intentionally reports status and JSON field names only. It
does not read local secret files and does not print tokens, cookies, config, or
logs.

## ChatGPT Developer Mode Test

After the live preflight passes:

1. Enable ChatGPT Developer Mode.
2. Create a connector with URL `https://mcp.example.com/mcp`.
3. Confirm ChatGPT can list tools.
4. Open a new chat, enable the connector, and run a small golden prompt set:
   read-only status, project listing, invalid project name, and one negative
   prompt that should not trigger a tool.
5. Record only redacted evidence: status, reason code, endpoint class,
   observed time, and whether tool listing succeeded.

## Submission Boundary

Private/internal use should stay in Developer Mode. Public submission requires a
separate explicit decision, organization verification, app permissions, privacy
and security review, and a completed Developer Mode test record.

## Blocked Without Explicit Authorization

The following remain blocked until Jenn gives action-scoped authorization:

- creating or changing DNS records;
- requesting, installing, or rotating production TLS certificates;
- creating cloud resources or managed ingress;
- changing production routing or exposing this machine directly to the public
  internet;
- submitting the app to a public directory;
- publishing releases, pushing tags, or deploying package artifacts.
