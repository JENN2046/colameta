# ColaMeta 安装与部署说明书

[English](INSTALLATION_AND_DEPLOYMENT.md)

本文统一说明 Python 包安装、源码开发环境、loopback 服务、七工具私人 App、仓库自带的
private-Beta systemd 栈、稳定运行时替换、验收和回滚。

它是操作说明，不是持续授权。暴露网络、修改 DNS/OAuth、重启服务、替换 stable、Git push、
发布包或提交公开 App，仍然分别需要与动作匹配的明确授权。

## 1. 先选部署形态

| 形态 | 用途 | 网络/认证边界 |
| --- | --- | --- |
| venv 内 Python 包 | 普通 CLI 使用 | 启动服务前不监听端口 |
| editable 源码环境 | 开发 ColaMeta、跑测试 | 默认仅本地 |
| loopback Web/MCP | 本机浏览器或本地 MCP client | `127.0.0.1`；本地开发认证 |
| 七工具 Commander | ChatGPT/Codex 私人 App | Commander profile；外部入口必须 HTTPS + OAuth |
| private-Beta systemd | Jenn 当前持久本地/私人部署 | system-level unit、loopback origin、受管 ingress |

不要为了绕过本地连接问题就把 MCP/Web 绑定到 `0.0.0.0`。远程私人 App 应使用经过明确批准的
HTTPS ingress 转发到 loopback origin。

## 2. 环境要求

- Python 3.10 或以上；
- Git；
- `venv` 和 pip；
- 需要实现任务时，准备 Codex、OpenCode 等本地执行器；
- 只有采用对应部署形态时，才需要 systemd、可信 HTTPS endpoint 和 OAuth provider。

## 3. 安装

### 安装发布包

推荐使用隔离环境：

```bash
python3 -m venv path/to/venv
path/to/venv/bin/python -m pip install --upgrade pip
path/to/venv/bin/python -m pip install colameta
path/to/venv/bin/colameta --version
```

### 从源码开发

在仓库根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python -m compileall adapters runner schemas scripts tests
.venv/bin/python -m pytest -q
.venv/bin/python scripts/self_hosting_smoke.py
```

使用冻结的离线依赖时，把联网 pip 步骤替换为获准的 wheel 目录和
`--no-index --find-links <wheel-directory>`。`.venv` 必须属于当前 checkout；不要复用解释器或
包来源指向另一棵 ColaMeta 目录的环境。

## 4. 登记项目

```bash
colameta add /path/to/project managed
# 或
colameta add /path/to/project source-only

colameta list
colameta status /path/to/project --json
```

需要版本计划、验证、receipt、review handoff 和 Git 闭环时用 `managed`；只需要较轻的读取/
检查入口时用 `source-only`。MCP service mode 按已登记 `project_name` 路由，不接受远端调用方
任意指定本机路径。

## 5. 启动本机 loopback 服务

普通已登记项目入口：

```bash
colameta start
```

默认地址：

```text
Web: http://127.0.0.1:8799
MCP: http://127.0.0.1:8765/mcp
```

显式本地开发进程：

```bash
colameta serve /path/to/project --auth-mode none --open
```

`auth-mode=none` 只用于 loopback 开发。Web 绑定到外部地址还必须显式提供
`--allow-external-web` 和 Web read token。远程 MCP 私人 App 必须使用 HTTPS 与 OAuth，见
[Remote HTTPS MCP Service](remote-https-mcp-service.md)。

## 6. 启动七工具私人 App 入口

通过 Commander exposure profile 保持恰好 7 个工具：

```bash
MCP_EXPOSURE_PROFILE=commander \
  colameta serve /path/to/project \
  --no-web \
  --mcp-host 127.0.0.1 \
  --mcp-port 8767 \
  --auth-mode external-oauth \
  --public-base-url https://mcp.example.com \
  --oauth-issuer https://idp.example.com/ \
  --oauth-jwks-url https://idp.example.com/.well-known/jwks.json \
  --oauth-audience https://mcp.example.com/mcp \
  --oauth-scopes mcp:read,mcp:preview
```

Commander 只暴露：

1. `list_registered_projects`
2. `get_apps_connector_smoke_packet`
3. `render_commander_app`
4. `analyze_project_state`
5. `run_mcp_workflow`
6. `manage_validation_run`
7. `manage_git`

`gate_review_request` 是 `run_mcp_workflow` 内部 workflow，不是第 8 个工具。首调用：

```json
{
  "workflow": "gate_review_request",
  "phase": "inspect",
  "project_name": "<registered-project-name>"
}
```

inspect/status 只读；preview 生成有界签名 Work Item Gate preview；apply 必须回传完整签名
preview、精确 bindings、`confirm_gate_review=true`，并同时满足 `mcp:commit`、已配置的可信私人
Operator subject/client 和 Work Item authority claims。默认/公共远端 principal 不会因此获得通用
commit 权限。

上面的启动示例故意只启用 read/preview scope，因此可以做 inspect/preview，不能直接 apply。
开启私人 apply 是独立受保护操作：先按
[Jenn Private Operator Protocol](jenn-private-operator-protocol.md) 交互执行
`colameta operator-config enable`，再只给已绑定的私人 principal 配置所需 scope 与 claims。

## 7. 安装仓库 private-Beta systemd 栈

仓库自带的是 Jenn 当前环境专用部署，换机器前必须先审查所有 unit 路径：

```bash
./scripts/install_private_beta_systemd.sh
sudo systemd-analyze verify /etc/systemd/system/colameta-*.service \
  /etc/systemd/system/cloudflared-colameta-mcp-prod.service \
  /etc/systemd/system/colameta-*.timer \
  /etc/systemd/system/colameta-private-beta.target
sudo systemctl start colameta-private-beta.target
```

安装脚本会备份被替换的 unit，安装并 enable target；它不会启动或停止服务。当前端口：

```text
127.0.0.1:8801  stable Web
127.0.0.1:8766  stable 七工具 Commander MCP
127.0.0.1:8767  external-OAuth 七工具 MCP origin
127.0.0.1:8768  loopback advanced MCP catalog
```

执行前先读 [Private Beta systemd Operations](private-beta-systemd.md)。

## 8. 稳定运行时替换

stable replacement 与安装是两条边界，必须绑定精确目标：

```text
授权替换稳定服务到 <exact_commit_sha>
```

有界顺序：

1. 证明候选 commit 和验证证据；
   记录精确 object 是否已在 `origin/main`、远端 CI 是否真的验证过它；
2. 确认 stable tracked worktree 与服务身份；
3. 备份旧 tracked tree、记录 SHA-256、创建 rollback ref；
4. 让 stable checkout fetch 并 detached 到精确授权 commit；
5. 本地构建单一 wheel，以 `--no-deps --force-reinstall` 重装；
6. 只重启被明确授权的服务；
7. 验证服务状态、loopback endpoint、runtime provenance、七工具清单、私人 App connector smoke
   与 `gate_review_request/inspect`；
8. 写 stable-replacement receipt。

不能从 CI、preview、receipt 或普通 `dev_ahead_stable` 漂移自动推导替换授权。可参考已脱敏的
[2dc7895 stable replacement](stable-replacement-receipts/stable-replacement-2dc7895-20260720.md)，
但它不是可复用授权。
优先使用已 merge 且 CI 验证过的候选。也可以精确授权本地候选，但 receipt 必须披露它未 push、
远端 CI 没有验证该精确 object。

## 9. 验收

本地检查：

```bash
colameta status /path/to/project --json
curl --fail http://127.0.0.1:8799/api/healthz
curl --fail http://127.0.0.1:8765/healthz
```

仓库 private-Beta 栈按第 7 节端口检查，并确认：

```text
service active/running
loaded_runtime_head == authorized target
runtime_loaded_code_stale == false
reload_needed_for_verification == false
Commander visible_tool_count == 7
私人 App list_registered_projects 成功
connector closeout == connector_closeout_ready / ready
gate_review_request inspect 成功且零副作用
```

如果目标项目没有启用 Work Item governance、候选为 0，那么
`candidate_count=0` 的成功 inspect 就是真实结果。不要为了强行跑 preview/apply 而伪造 Work Item。

## 10. 回滚

回滚也是受保护的 lifecycle 动作。取得精确授权后，使用 replacement receipt 中记录的 backup、
checksum 和 rollback ref；重装恢复后的精确源码，只重启被授权服务，并重跑同一组 runtime 与
私人 App 验收。不要用宽泛递归删除或未校验 archive 做回滚。

## 11. 安全与交付边界

- 不把 bearer token、cookie、credential、private key、provider raw response、browser login
  state 或 raw log 写入命令、文档、receipt 或 Git。
- 没有经过批准的 HTTPS ingress 与认证设计时，不直接把 Web/MCP 暴露到公网。
- 包发布、Git push/tag、公开 App submission、DNS/tunnel 修改、stable replacement 和服务重启是
  彼此独立的动作，权限不能互相推导。
- 只读 health/smoke 是 evidence，不会创建 ReviewDecision、GateEvent、Delivery State accepted
  或 executor authority。
