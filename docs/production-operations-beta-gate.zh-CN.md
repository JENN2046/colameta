# ColaMeta Production Operations Beta Gate

本文定义 Stage 10 的维护者运维包。目标是证明 ColaMeta HTTPS MCP 不只是
能运行，而是能被未来维护者检查、审计、恢复和安全接手。

本文件不授权 stable replacement、rollback、restore、release、deploy、tag
push、package publish、GitHub issue/PR 创建、ReviewDecision、GateEvent 或
Delivery accepted。

## 1. 三层结论

`colameta ops-check` 输出三个独立结论：

```text
ops_check_ready
  本地 stable runtime、本地 Web/MCP、公网 HTTPS MCP、cloudflared、backup
  inventory 和 rollback rehearsal evidence 都满足。

connector_smoke_ready
  已提供 fresh ChatGPT Apps connector smoke 脱敏证据，且状态为 ready。

beta_gate_ready
  ops_check_ready=true 且 connector_smoke_ready=true。
```

不要把 remote HTTPS preflight 成功解读为 ChatGPT connector 已经成功。实际
connector smoke 仍必须由 ChatGPT Apps connector 工具或人工授权的 Apps 调用
产生。

## 2. Gate 判定矩阵

必须判为 `blocked`：

```text
stable service inactive
stable runtime head != expected head
running Web/MCP loaded runtime head unavailable or != expected head
remote HTTPS MCP preflight failed
local stable Web/MCP health failed
secret-like content detected in output packet
```

必须判为 `needs_attention`：

```text
external connector evidence missing
fresh ChatGPT connector smoke missing
backup missing
backup sha256 unavailable
backup archive unreadable
rollback target commit unresolved
connector smoke older than the configured freshness window
remote HTTPS MCP preflight not run because --no-network was used
```

只有所有运维检查 ready、fresh connector smoke ready，且 backup/rollback
evidence 完整时，`beta_gate_ready=true`。

## 3. 运行检查

只读检查，不写状态文件：

```bash
.venv/bin/colameta ops-check /home/jenn/src/colameta-dev \
  --public-base-url https://colameta-mcp.skmt617.top \
  --json
```

CI/offline 形态检查：

```bash
.venv/bin/colameta ops-check /home/jenn/src/colameta-dev \
  --public-base-url https://colameta-mcp.skmt617.top \
  --no-network \
  --json
```

`--no-network` 只验证 URL / endpoint 形态，不访问公网 HTTPS MCP。它会让
`remote_https_mcp_preflight` 返回 `REMOTE_PREFLIGHT_NOT_RUN`，因此不能满足
`ops_check_ready=true` 或 `beta_gate_ready=true`。

写入本地脱敏状态：

```bash
.venv/bin/colameta ops-check /home/jenn/src/colameta-dev \
  --public-base-url https://colameta-mcp.skmt617.top \
  --write-status ~/.local/state/colameta/ops/last-status.json \
  --json
```

如果 `main` 只有 receipt/docs 领先 stable runtime，可显式指定 stable runtime
应对齐的运行代码 head：

```bash
.venv/bin/colameta ops-check /home/jenn/src/colameta-dev \
  --public-base-url https://colameta-mcp.skmt617.top \
  --expected-head <stable-runtime-code-head> \
  --json
```

告警集成才使用：

```bash
.venv/bin/colameta ops-check /home/jenn/src/colameta-dev \
  --public-base-url https://colameta-mcp.skmt617.top \
  --fail-on-not-ready \
  --json
```

默认 timer 不使用 `--fail-on-not-ready`，避免普通采集在 systemd 中形成持续
失败噪声。

## 4. ChatGPT Connector Smoke 补证

`ops-check` 不替代 Apps connector 实际调用。拿到 ChatGPT Apps connector
smoke 后，只回灌脱敏字段：

```bash
.venv/bin/colameta ops-check /home/jenn/src/colameta-dev \
  --public-base-url https://colameta-mcp.skmt617.top \
  --connector-smoke-status ready \
  --connector-smoke-observed-at 2026-07-06T17:43:50Z \
  --json
```

fresh 默认窗口为 24 小时。允许用 `--connector-smoke-fresh-hours` 收窄窗口，
范围为 `1..24`。

`--connector-smoke-status` 只会原样保留 allowlisted 状态值，例如 `ready`、
`missing`、`stale`、`failed`、`needs_attention`、`blocked`、
`unavailable` 和 `unknown`。其它状态文本会在 packet 中改成固定占位符；
`Bearer ...`、JWT、token、password、secret 等 secret-like 文本会让 connector
smoke check blocked，并且不会在 `--json` 或 `--write-status` 输出中回显。

`ops-check` 还要求本地 stable Web `/api/healthz` 和 MCP `/healthz` 返回的运行态
证据同时满足：`loaded_runtime_head` 与 `expected_head` 一致、
`runtime_loaded_code_stale=false`、`reload_needed_for_verification=false`，并且
`installed_package_project_source_clean=true`、
`installed_package_source_cleanliness_status=clean`。
对于通过 non-editable pip install 启动的 packaged stable service，如果
`loaded_runtime_head` 为空，也可以用 healthz 返回的 packaged runtime provenance
证明：`runtime_project_checkout_head` 等于 `expected_head`，
`runtime_loaded_code_stale=false`，`reload_needed_for_verification=false`，
且 installed-package/source-checkout verification 为 `match`，并且
`installed_package_project_source_clean=true`、
`installed_package_source_cleanliness_status=clean`。如果 `loaded_runtime_head`
已报告但不同于 `expected_head`，则必须 fail-closed，不能用 packaged runtime
provenance fallback 覆盖这条运行中代码证据。source roots 存在未提交或
untracked 变化时，即使这些变化已经被安装到 site-packages，也会 fail-closed。
这些 healthz runtime provenance 字段描述 loaded/stable runtime source root，而不是
`serve <project_root>` 传入的被服务项目；packaged install 会从 distribution
`direct_url.json` 恢复安装来源 checkout，用于 `runtime_project_checkout_head` 和
source-clean/package-match 证据。
stable checkout 磁盘 HEAD 对齐但服务未重启时，这项会 fail-closed，而不会把
disk HEAD 当作运行中代码证据。公开 healthz 中的 packaged provenance 是进程内
缓存的轻量摘要，避免远程轮询反复触发源码 hash 校验；缓存 key 包含当前 checkout
HEAD 和 source-root cleanliness 状态，HEAD 或 clean/dirty 状态变化时会重新计算。

`--public-base-url` 必须代表公网 remote MCP endpoint。`http://` loopback 只允许
`--no-network` 离线形态检查；`https://127.0.0.1`、`https://localhost` 或其它
loopback HTTPS URL 会直接 rejected。private / link-local IP literal，例如
`https://192.168.1.10` 或 RFC4193 IPv6，也会 rejected。短写或整数型 numeric IPv4
形式，例如 `https://127.1`、`https://2130706433`，会先按 IPv4 地址解释后再判定，
不能绕过公网 endpoint 要求。local-only DNS 名称也会 rejected，包括 `.local`、
`.localhost`、`.home.arpa` 等后缀和 single-label host，例如 `https://colameta`。
联网 remote preflight 还会校验公网 `/healthz` 的 runtime provenance：public MCP
endpoint 必须证明正在服务 `expected_head`，且 reload/source-clean evidence 为 ready；
只满足 OAuth metadata contract 但指向旧实例或错误实例时会 blocked。`external-oauth`
protected-resource metadata 里的 authorization server 也必须是公网 HTTPS 外部 IdP，
不能是 loopback/private/local-only host，也不能是 MCP `public_base_url`。每个 probe 的最终
响应 URL 必须仍是同一 public HTTPS endpoint；redirect 到 loopback、private LAN、
其它 host、其它 path、query 或 fragment 都会 rejected。30x redirects 会在跟随
`Location` 前直接失败，避免 operator 机器先访问内网目标再报告失败。每个 metadata
或 error response body 读取上限为 64 KiB，超过上限会 fail preflight，不会完整缓存
异常响应。显式传入的
`--expected-head` 必须是完整 40-character commit SHA，不能以 malformed 或
abbreviated SHA 静默跳过 runtime provenance 校验。

`project_root`、`public_base_url`、connector smoke 字段和 status write path 在 packet
构造或 JSON 输出前都会先做 secret-like redaction。若 operator 误把 token-like 文本
粘进路径或参数，输出会使用固定占位符并 blocked，而不会回显原始值。

## 5. Systemd Timer

安装或更新 user unit：

```bash
mkdir -p ~/.config/systemd/user
ln -sfn /home/jenn/src/colameta-dev/systemd/user/colameta-ops-check.service \
  ~/.config/systemd/user/colameta-ops-check.service
ln -sfn /home/jenn/src/colameta-dev/systemd/user/colameta-ops-check.timer \
  ~/.config/systemd/user/colameta-ops-check.timer
systemctl --user daemon-reload
systemctl --user enable colameta-ops-check.timer
systemctl --user start colameta-ops-check.timer
```

查看：

```bash
systemctl --user status colameta-ops-check.timer
systemctl --user status colameta-ops-check.service
cat ~/.local/state/colameta/ops/last-status.json
```

停用：

```bash
systemctl --user disable --now colameta-ops-check.timer
```

## 6. Backup / Rollback Rehearsal

`ops-check` 的 rehearsal 是只读证明，不执行 restore。

最低 evidence：

```text
backup inventory 至少存在 stable-before-*.tar.gz
backup sha256 可重新计算
backup archive 可 tar -tzf 等价列目录
rollback target commit 可解析
rehearsal_executed_restore=false
```

真正 rollback 或 restore 必须单独授权，并另写 receipt。

## 7. 禁止动作

Stage 10 运维检查不做：

```text
不接 Auth0 / Cloudflare 管理 API
不读取 token、cookie、secret、.env 值、provider config、raw logs
不发送通知
不自动 rollback
不自动 stable replacement
不自动创建 GitHub issue / PR
不修改 Beta classifier
不 release、deploy、tag push、package publish
```

## 8. Beta 状态

`beta_gate_ready=true` 只表示 Beta Gate evidence ready。是否把项目从 Alpha
改成 Beta，必须作为后续独立产品/发布决策。
