# DNS / Proxy / Cloudflare Tunnel 运行手册

## 目的

这份手册用于处理 remote MCP preflight 或 ChatGPT Apps connector smoke 在
WSL、代理、fake-IP DNS、split-horizon DNS 环境下失败的问题。目标是证明
`public_base_url`、Cloudflare tunnel edge、external OAuth issuer 都解析到公网
globally routable 地址，然后再重跑 preflight 和 connector smoke。

这份手册不要求读取 tunnel credentials、provider auth、proxy 配置值、浏览器状态、
token、cookie 或 raw provider response。

## 典型症状

```yaml
public_base_url_rejected:
  reason_code: PUBLIC_BASE_URL_REJECTED
  symptom: hostname resolves to non-public address
cloudflare_tunnel_broken:
  remote_http_status: 530
  cloudflare_error_code: 1033
  symptom: cloudflared cannot register usable edge connections
external_oauth_rejected:
  symptom: authorization server issuer resolves to non-public address
```

重点观察：

- `198.18.0.0/15` fake-IP DNS answers。
- `cloudflared` 日志或 status 里出现 edge dial timeout。
- unit 是否把 transport 强制成 `quic` 或 `http2`；强制协议会在对应的
  UDP/TCP 7844 路径受阻时阻止自动回退。
- `remote_https_mcp_preflight.py` 对 external-oauth authorization server 报
  non-public HTTPS URL。

## 安全边界

允许：

- 查看 DNS 解析结果。
- 查看 sanitized systemd status。
- 查看 remote preflight 的 HTTP status、reason code 和 runtime provenance。
- 写入 operator-controlled、scoped、可回滚的 `/etc/hosts` 临时 override。

不要做：

- 不读取 tunnel credential 文件内容。
- 不读取 provider auth、proxy 配置值、浏览器登录状态、token 或 cookie。
- 不把 raw provider response 写入 receipt。
- 不把临时 DNS 修正当成永久网络策略。

## 1. 检查 public MCP hostname

```bash
getent ahosts colameta-mcp.skmt617.top
```

如果返回 `198.18.x.x`、loopback、private、link-local、multicast 或其它 non-global
地址，preflight 会拒绝这个 public endpoint。

用 pinned public resolver 做对照：

```bash
curl -sS --resolve cloudflare-dns.com:443:1.1.1.1 \
  'https://cloudflare-dns.com/dns-query?name=colameta-mcp.skmt617.top&type=A' \
  -H 'accept: application/dns-json'

curl -sS --resolve dns.google:443:8.8.8.8 \
  'https://dns.google/resolve?name=colameta-mcp.skmt617.top&type=A'
```

若 DoH 返回 public A records，而本机 resolver 返回 fake-IP，优先修系统 DNS/proxy
策略；临时 workaround 可以使用 scoped `/etc/hosts` override。

## 2. 检查 Cloudflare tunnel edge DNS

Cloudflare tunnel client 会连接 SRV 指向的 edge host。先查 SRV：

```bash
curl -sS --resolve cloudflare-dns.com:443:1.1.1.1 \
  'https://cloudflare-dns.com/dns-query?name=_v2-origintunneld._tcp.argotunnel.com&type=SRV' \
  -H 'accept: application/dns-json'
```

常见目标：

```text
region1.v2.argotunnel.com
region2.v2.argotunnel.com
```

检查本机 resolver：

```bash
getent ahosts region1.v2.argotunnel.com
getent ahosts region2.v2.argotunnel.com
```

如果这些目标解析到 `198.18.x.x`，`cloudflared` 可能 active/running 但实际无法注册
edge connection，远端会表现为 Cloudflare HTTP 530 / 1033。

## 3. 检查 external OAuth issuer DNS

从 protected-resource metadata 读取 issuer host 后，只检查 hostname 解析，不读取
provider auth：

```bash
getent ahosts dev-2n3z8xing6eekyok.us.auth0.com
```

用 DoH 对照：

```bash
curl -sS --resolve cloudflare-dns.com:443:1.1.1.1 \
  'https://cloudflare-dns.com/dns-query?name=dev-2n3z8xing6eekyok.us.auth0.com&type=A' \
  -H 'accept: application/dns-json'
```

如果本机 resolver 返回 fake-IP，external-oauth authorization server validation 会把
issuer 判为 non-public。

## 4. 临时 `/etc/hosts` override

临时 override 必须先备份：

```bash
sudo cp /etc/hosts /etc/hosts.colameta-backup-$(date +%Y%m%dT%H%M%S%z)
```

只追加带 marker 的 scoped block：

```text
# BEGIN colameta public DNS override YYYY-MM-DD
<public-ip> colameta-mcp.skmt617.top
<public-ip> region1.v2.argotunnel.com
<public-ip> region2.v2.argotunnel.com
<public-ip> dev-2n3z8xing6eekyok.us.auth0.com
# END colameta public DNS override YYYY-MM-DD
```

不要把 sample IP 当作长期固定值；每次都用 pinned DoH 重新取当前 public answer。
也不要把 override 通过 `BindReadOnlyPaths=...:/etc/hosts` 固化进长期运行的
`cloudflared` unit；这会阻止 tunnel 使用完整 edge pool 进行轮换。

## 5. 重启与验证顺序

先确认 DNS 结果：

```bash
getent ahosts colameta-mcp.skmt617.top
getent ahosts region1.v2.argotunnel.com
getent ahosts region2.v2.argotunnel.com
getent ahosts dev-2n3z8xing6eekyok.us.auth0.com
```

再重启受影响的本地服务：

```bash
sudo systemctl restart cloudflared-colameta-mcp-prod.service
sudo systemctl restart colameta-mcp-remote.service
```

验证 tunnel client：

```bash
sudo systemctl status cloudflared-colameta-mcp-prod.service --no-pager
```

合格证据：

```yaml
cloudflared:
  active_state: active
  sub_state: running
  configured_protocol: auto
  registered_edge_connections: public Cloudflare IPs
```

仓库提供的 unit 使用 `--protocol auto`。`cloudflared` 会优先尝试 QUIC，并在
UDP 7844 不可用时回退到 HTTP/2/TCP 7844。不要把一次临时网络路径的成功协议
永久强制到 unit；若 `auto` 下仍无法连接，应检查 DNS 以及 TCP/UDP 7844 的出站
连通性。

若 Cloudflare 控制台显示 tunnel `离线`、`活动副本 0`，本地 origin 正常且
`http://127.0.0.1:20241/ready` 返回 `503`，在获得生产凭据刷新授权后运行：

```bash
scripts/refresh_cloudflared_tunnel_credentials.sh
```

该脚本不会接受或输出 dashboard install token，也不会安装第二个 cloudflared
service。它通过现有 Cloudflare 登录证书为精确命名 tunnel 获取新 credentials，
在同一私有配置目录保留权限为 `0600` 的旧凭据备份，原子替换后只重启
`cloudflared-colameta-mcp-prod.service`，最后检查本地 readiness 并运行公网
remote HTTPS MCP preflight。若新凭据无法生成，脚本不会停止当前服务或替换旧
凭据。新凭据只有在本地 readiness、托管 systemd unit active 检查和公网
preflight 全部通过后才会提交；在验证期间发生超时、unit inactive、preflight
失败或 `HUP`/`INT`/`TERM` 中断时，脚本会停止未验证实例、恢复备份并使用旧凭据
重启服务。若自动回滚自身失败，脚本会返回失败并保留备份供运维恢复。

## 6. 重跑 preflight / ops-check / connector smoke

```bash
.venv/bin/python scripts/remote_https_mcp_preflight.py https://colameta-mcp.skmt617.top
```

成功形态：

```yaml
ok: true
responses:
  healthz: 200
  mcp: 200
  protected_resource_metadata: 200
healthz_runtime:
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
```

再跑：

```bash
.venv/bin/colameta ops-check /home/jenn/src/colameta-dev \
  --expected-head <expected_head> \
  --json
```

最后用 ChatGPT Apps connector smoke 证明外部 connector session 可达，并把 sanitized
evidence 写入 closeout receipt。

## 7. 长期修正

临时 hosts override 只用于恢复和取证。长期应把以下 hostname 从 fake-IP DNS/proxy
策略中排除，或让 resolver 对这些 hostname 返回公网真实地址：

- public MCP hostname，例如 `colameta-mcp.skmt617.top`。
- Cloudflare tunnel edge targets，例如 `region1.v2.argotunnel.com`、
  `region2.v2.argotunnel.com`。
- external OAuth issuer host，例如 Auth0 issuer。

当 Windows 使用 Mihomo TUN 时，优先把 Cloudflare global tunnel edge 前缀追加到
应用级、可持久化的 `tun.route-exclude-address`，并把对应 `DIRECT` 规则 prepend
到订阅的 `MATCH`/代理规则之前：

```yaml
tun:
  route-exclude-address:
    - 198.41.192.0/24
    - 198.41.200.0/24

rules:
  - DOMAIN,region1.v2.argotunnel.com,DIRECT
  - DOMAIN,region2.v2.argotunnel.com,DIRECT
  - DOMAIN-SUFFIX,cftunnel.com,DIRECT
  - IP-CIDR,198.41.192.0/24,DIRECT,no-resolve
  - IP-CIDR,198.41.200.0/24,DIRECT,no-resolve
```

追加 `route-exclude-address` 时必须保留已有排除项。全局扩展配置不能直接替换
订阅的整个 `rules` 列表；使用全局扩展脚本或当前订阅的规则编辑器做前置插入。
保留临时 `/32` 作为迁移护栏，逐条撤销并验证所有当前 edge 地址后，再移除
custom hosts 绑定。

当长期 DNS/proxy 策略稳定后，撤掉 `/etc/hosts` 临时 block，再重跑同一组 preflight
和 connector smoke。
