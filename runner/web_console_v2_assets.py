from __future__ import annotations

import html as html_lib


def render_v2_index_page(csrf_token: str = "", web_read_token: str = "") -> str:
    csrf_attr = html_lib.escape(csrf_token, quote=True)
    web_read_auth_attr = html_lib.escape(web_read_token, quote=True)
    css = """
* { box-sizing: border-box; margin: 0; padding: 0; }
html { height: 100vh; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; font-size: 14px; line-height: 1.5; height: 100vh; overflow: hidden; }
h1 { font-size: 20px; font-weight: 600; color: #f0f6fc; margin-bottom: 4px; }
h2 { font-size: 16px; font-weight: 600; color: #f0f6fc; margin: 0 0 12px; }
h3 { font-size: 14px; font-weight: 600; color: #f0f6fc; margin: 12px 0 6px; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
.card-title { font-size: 11px; font-weight: 600; text-transform: uppercase; color: #8b949e; margin-bottom: 8px; letter-spacing: 0.5px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 500; }
.badge-info { background: #1f6feb22; color: #58a6ff; border: 1px solid #1f6feb44; }
.badge-ok { background: #23863622; color: #3fb950; border: 1px solid #23863644; }
.badge-warn { background: #d2992222; color: #d29922; border: 1px solid #d2992244; }
.badge-err { background: #da363322; color: #f85149; border: 1px solid #da363344; }
.blocker { color: #f85149; }
.warning { color: #d29922; }
.key { color: #8b949e; font-size: 12px; }
.val { color: #c9d1d9; word-break: break-word; }

#app { display: flex; flex-direction: column; height: 100%; min-height: 0; }
#content { flex: 1; min-height: 0; overflow: hidden; }

.layout-grid { display: grid; grid-template-columns: 280px 1fr 340px; gap: 16px; height: 100%; min-height: 0; align-items: stretch; }

.layout-left .compact-row { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; border-bottom: 1px solid #21262d; font-size: 13px; }
.layout-left .compact-row:last-child { border-bottom: none; }
.layout-left .section-label { font-size: 11px; font-weight: 600; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin: 10px 0 4px; }
.layout-left .compact-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; }
.layout-left .todo-item { padding: 8px 0; border-top: 1px solid #21262d; }
.layout-left .todo-item:first-child { border-top: none; padding-top: 4px; }
.layout-left .todo-id-row { display: flex; align-items: center; gap: 8px; justify-content: space-between; margin-bottom: 4px; }
.layout-left .todo-copy-btn { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 2px 8px; border-radius: 999px; font-size: 11px; cursor: pointer; flex: 0 0 auto; }
.layout-left .todo-copy-btn:hover { background: #30363d; }
.layout-left .todo-content { color: #c9d1d9; font-size: 12px; white-space: pre-wrap; word-break: break-word; }

#center-observation-stack { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 12px; overflow: hidden; }
#live-run-panel-slot { flex: 1 1 auto; min-height: 0; display: flex; }
.layout-center .summary-card { border-left: 4px solid #58a6ff; padding: 16px; }
.layout-center .summary-card.ok { border-left-color: #3fb950; }
.layout-center .summary-card.failed { border-left-color: #f85149; }
.layout-center .summary-title { font-size: 18px; font-weight: 600; margin: 0 0 4px; color: #f0f6fc; }
.layout-center .badge-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.layout-center .live-run-card { border-left-color: #4a3f33; }
.layout-center .live-run-card.idle { border-left-color: #4a3f33; }
.layout-center .live-run-card.running { border-left-color: #6fba83; }
.layout-center .live-run-card.problem { border-left-color: #d29922; }
.layout-center .live-run-card.failed { border-left-color: #d29922; }
.layout-center .live-session-row { align-items: center; }
.layout-center .live-session-value { display: inline-flex; flex-wrap: nowrap; align-items: center; gap: 8px; min-width: 0; max-width: 100%; overflow-x: auto; white-space: nowrap; }
.layout-center .live-session-id { flex: 0 0 auto; white-space: nowrap; word-break: normal; }
.layout-center .live-session-separator { color: #8b949e; flex: 0 0 auto; }
.layout-center .live-session-mode { flex: 0 0 auto; }
.layout-center .live-session-copy { background: transparent; border: none; color: #58a6ff; cursor: pointer; font: inherit; padding: 0 2px; line-height: 1; flex: 0 0 auto; }
.layout-center .live-session-copy:hover { color: #79c0ff; }
.layout-center .thin-loop-preview-card { flex: 0 0 auto; margin-bottom: 0; border-left: 4px solid #58a6ff; }
.layout-center .thin-loop-preview-card.blocked { border-left-color: #f85149; }
.layout-center .thin-loop-path { color: #c9d1d9; font-size: 12px; word-break: break-word; padding: 4px 0; }
.layout-center .thin-loop-boundary { color: #8b949e; font-size: 11px; line-height: 1.5; border-top: 1px solid #30363d; margin-top: 8px; padding-top: 8px; }

.layout-right .action-btn { display: block; width: 100%; background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 8px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; text-align: left; margin-bottom: 6px; }
.layout-right .action-btn:hover { background: #30363d; }
.layout-right .action-btn.primary { background: #1f6feb; border-color: #388bfd; color: #fff; }
.layout-right .action-btn.primary:hover { background: #388bfd; }
.layout-right .action-btn.commit { background: #238636; border-color: #3fb950; color: #fff; }
.layout-right .action-btn.commit:hover { background: #2ea043; }
.layout-right .action-btn .btn-label { font-weight: 500; }
.layout-right .action-btn .btn-reason { font-size: 11px; color: #8b949e; margin-top: 2px; }
.layout-right .action-btn .btn-meta { font-size: 10px; color: #8b949e; margin-top: 2px; display: flex; gap: 6px; flex-wrap: wrap; }
.layout-right .todo-item { padding: 8px 0; border-bottom: 1px solid #30363d55; }
.layout-right .todo-item:last-child { border-bottom: none; }
.layout-right .todo-id-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.layout-right .todo-copy-btn { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 2px 8px; border-radius: 999px; font-size: 11px; cursor: pointer; flex: 0 0 auto; }
.layout-right .todo-copy-btn:hover { background: #30363d; }
.layout-right .todo-content { color: #c9d1d9; font-size: 12px; white-space: pre-wrap; word-break: break-word; }
.layout-right .todo-content-preview { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; cursor: pointer; max-height: 54px; }
.layout-right .todo-content-preview:hover { color: #f0f6fc; }
.layout-right .todo-pager { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 10px; font-size: 12px; color: #8b949e; }
.layout-right .todo-page-btn { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 3px 9px; border-radius: 999px; font-size: 11px; cursor: pointer; }
.layout-right .todo-page-btn:hover:not(:disabled) { background: #30363d; }
.layout-right .todo-page-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.layout-left, .layout-center, .layout-right { min-height: 0; overflow: hidden; }
.layout-center, .layout-right { display: flex; flex-direction: column; }
.layout-right .action-tab-card { flex: 1; min-height: 0; margin-bottom: 0; display: flex; flex-direction: column; }
.layout-right .tab-content { flex: 1; min-height: 0; overflow-y: auto; scrollbar-width: thin; scrollbar-color: #30363d transparent; }
.layout-right .tab-content::-webkit-scrollbar { width: 6px; }
.layout-right .tab-content::-webkit-scrollbar-track { background: transparent; }
.layout-right .tab-content::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
.layout-right .tab-content::-webkit-scrollbar-thumb:hover { background: #484f58; }
.todo-detail-id { font-size: 12px; color: #8b949e; margin-bottom: 8px; }
.todo-detail-content { white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.6; }
.tab-icon { color: #8b949e; font-size: 12px; margin-right: 5px; }
.issue-count-link { background: transparent; border: none; color: #58a6ff; cursor: pointer; font: inherit; padding: 0; text-decoration: none; }
.issue-count-link:hover { text-decoration: underline; }

#loading { text-align: center; padding: 60px 20px; color: #8b949e; }
#error { display: none; background: #da363322; border: 1px solid #da363344; border-radius: 8px; padding: 16px; margin: 12px 0; }
.toolbar { display: flex; gap: 8px; align-items: flex-start; margin-bottom: 16px; }
.toolbar button { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 6px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; margin-top: 2px; }
.toolbar button:hover { background: #30363d; }
.project-switch { margin-left: auto; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.project-switch-label { color: #8b949e; font-size: 12px; }
.project-switch select { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; border-radius: 6px; padding: 6px 28px 6px 10px; max-width: 360px; font-size: 13px; }
.project-switch select:disabled { opacity: 0.7; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.58); z-index: 1000; display: none; align-items: flex-start; justify-content: center; padding: 72px 16px 24px; }
.modal-backdrop.open { display: flex; }
.modal-panel { width: min(900px, 100%); max-height: calc(100vh - 96px); overflow: auto; background: #0d1117; border: 1px solid #30363d; border-radius: 10px; box-shadow: 0 20px 60px rgba(0,0,0,0.45); scrollbar-width: thin; scrollbar-color: #30363d transparent; }
.modal-panel::-webkit-scrollbar { width: 6px; }
.modal-panel::-webkit-scrollbar-track { background: transparent; }
.modal-panel::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
.modal-panel::-webkit-scrollbar-thumb:hover { background: #484f58; }
.modal-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; border-bottom: 1px solid #21262d; }
.modal-title { font-size: 15px; font-weight: 600; color: #f0f6fc; }
.modal-body { padding: 16px; }
.version-detail-tabs { display: flex; gap: 8px; margin-bottom: 12px; border-bottom: 1px solid #21262d; }
.version-detail-tab { background: transparent; border: none; color: #8b949e; cursor: pointer; padding: 8px 2px; font-size: 13px; border-bottom: 2px solid transparent; }
.version-detail-tab.active { color: #f0f6fc; border-bottom-color: #58a6ff; }
.version-detail-path { margin-bottom: 8px; font-size: 12px; color: #8b949e; word-break: break-all; }
.version-detail-content { background:#161b22; padding:12px; border-radius:6px; font-size:13px; color:#c9d1d9; white-space:pre-wrap; word-break:break-word; max-height:60vh; overflow:auto; scrollbar-width: thin; scrollbar-color: #30363d transparent; }
.version-detail-content::-webkit-scrollbar { width: 6px; }
.version-detail-content::-webkit-scrollbar-track { background: transparent; }
.version-detail-content::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
.version-detail-content::-webkit-scrollbar-thumb:hover { background: #484f58; }
.modal-close { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 4px 10px; border-radius: 6px; cursor: pointer; }
.modal-close:hover { background: #30363d; }
.empty-state { color: #8b949e; font-size: 13px; font-style: italic; padding: 4px 0; }
.live-run-panel { border-left: 4px solid #d29922; flex: 1; min-height: 0; margin-bottom: 0; display: flex; flex-direction: column; }
.live-run-event { display: flex; gap: 8px; padding: 3px 0; font-size: 12px; }
.live-run-event .evt-ts { color: #8b949e; flex: 0 0 64px; font-family: monospace; white-space: nowrap; }
.live-run-event .evt-content { flex: 1; min-width: 0; }
.live-run-event .evt-title { color: #58a6ff; font-weight: 500; line-height: 1.6; }
.live-run-event .evt-detail { color: #c9d1d9; word-break: break-word; font-size: 11px; line-height: 1.5; }
.live-run-diagnostic { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 11px; font-weight: 500; margin: 2px; }
.live-run-diagnostic.warn { background: #d2992222; color: #d29922; border: 1px solid #d2992244; }
.live-run-diagnostic.err { background: #da363322; color: #f85149; border: 1px solid #da363344; }

.live-run-events-scroll { flex: 1; min-height: 120px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: #30363d transparent; }
.live-run-events-scroll::-webkit-scrollbar { width: 6px; }
.live-run-events-scroll::-webkit-scrollbar-track { background: transparent; }
.live-run-events-scroll::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
.live-run-events-scroll::-webkit-scrollbar-thumb:hover { background: #484f58; }

.tab-bar { display: flex; gap: 0; margin-bottom: 12px; border-bottom: 1px solid #30363d; }
.tab-btn { background: transparent; border: none; color: #8b949e; padding: 6px 14px; font-size: 13px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; text-align: left; display: flex; align-items: center; justify-content: flex-start; }
.tab-btn.active { color: #f0f6fc; border-bottom-color: #58a6ff; }
.tab-btn:hover { color: #c9d1d9; }
.layout-left { display: flex; flex-direction: column; }
.layout-left .left-tab-card { flex: 1; min-height: 0; margin-bottom: 0; display: flex; flex-direction: column; }
.layout-left .tab-content { flex: 1; min-height: 0; overflow-x: hidden; overflow-y: auto; scrollbar-width: thin; scrollbar-color: #30363d transparent; }
.layout-left .tab-content::-webkit-scrollbar { width: 6px; }
.layout-left .tab-content::-webkit-scrollbar-track { background: transparent; }
.layout-left .tab-content::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
.layout-left .tab-content::-webkit-scrollbar-thumb:hover { background: #484f58; }
.layout-left .version-item { padding: 8px 0; border-bottom: 1px solid #21262d; }
.layout-left .version-item:last-child { border-bottom: none; }
.layout-left .version-row-main { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.layout-left .version-version { font-size: 12px; font-weight: 600; color: #f0f6fc; }
.layout-left .version-title-link { display: block; width: 100%; margin-top: 4px; background: none; border: none; color: #58a6ff; font-size: 12px; text-align: left; cursor: pointer; padding: 2px 0; word-break: break-word; }
.layout-left .version-title-link:hover { color: #79c0ff; text-decoration: underline; }
@media (max-width: 1024px) {
  html, body { height: auto; overflow: visible; }
  #app { height: auto; }
  #content { flex: none; overflow: visible; }
  .layout-grid { height: auto; grid-template-columns: 1fr; }
  .layout-center { order: 1; }
  .layout-right { order: 2; }
  .layout-left { order: 3; }
}
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="colameta-csrf-token" content="{csrf_attr}">
<meta name="colameta-web-read-auth" content="{web_read_auth_attr}">
<title>ColaMeta</title>
<style>{css}</style>
</head>
<body>
<div id="app">
  <div class="toolbar">
    <div>
      <h1>ColaMeta</h1>
    </div>
    <div class="project-switch">
      <span class="project-switch-label">切换项目</span>
      <select id="project-select" aria-label="当前项目" disabled>
        <option>加载中…</option>
      </select>
      <button id="project-manage-btn" onclick="openProjectManagement()">项目管理</button>
      <button onclick="refresh()">刷新</button>
    </div>
  </div>
  <div id="loading">加载中…</div>
  <div id="error"></div>
  <div id="project-management-modal" class="modal-backdrop" onclick="closeProjectManagement(event)">
    <div class="modal-panel" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div class="modal-title">项目登记管理</div>
        <button type="button" class="modal-close" onclick="closeProjectManagement()">关闭</button>
      </div>
      <div id="project-management-modal-body" class="modal-body"></div>
    </div>
  </div>
  <div id="issue-detail-modal" class="modal-backdrop" onclick="closeIssueModal(event)">
    <div class="modal-panel" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div id="issue-detail-modal-title" class="modal-title">问题详情</div>
        <button type="button" class="modal-close" onclick="closeIssueModal()">关闭</button>
      </div>
      <div id="issue-detail-modal-body" class="modal-body"></div>
    </div>
  </div>
  <div id="todo-detail-modal" class="modal-backdrop" onclick="closeTodoModal(event)">
    <div class="modal-panel" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div id="todo-detail-modal-title" class="modal-title">TODO 详情</div>
        <button type="button" class="modal-close" onclick="closeTodoModal()">关闭</button>
      </div>
      <div id="todo-detail-modal-body" class="modal-body"></div>
    </div>
  </div>
  <div id="version-prompt-modal" class="modal-backdrop" onclick="closeVersionPromptModal(event)">
    <div class="modal-panel" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div id="version-prompt-modal-title" class="modal-title">Prompt</div>
        <button type="button" class="modal-close" onclick="closeVersionPromptModal()">关闭</button>
      </div>
      <div id="version-prompt-modal-body" class="modal-body"></div>
    </div>
  </div>
  <div id="content" style="display:none;">
    <div class="layout-grid">
      <div class="layout-left" id="layout-left"></div>
      <div class="layout-center" id="layout-center"></div>
      <div class="layout-right" id="layout-right"></div>
    </div>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);
const API = "/api/v2/status";
const csrfMeta = document.querySelector('meta[name="colameta-csrf-token"]');
const CSRF_TOKEN = csrfMeta ? (csrfMeta.getAttribute("content") || "") : "";
const webReadAuthMeta = document.querySelector('meta[name="colameta-web-read-auth"]');
const WEB_READ_AUTH = webReadAuthMeta ? (webReadAuthMeta.getAttribute("content") || "") : "";
function readHeaders() {{
  return WEB_READ_AUTH ? {{ "X-ColaMeta-Read-Auth": WEB_READ_AUTH }} : {{}};
}}
function jsonHeaders() {{
  return {{ "Content-Type": "application/json", "X-ColaMeta-CSRF": CSRF_TOKEN }};
}}
const DANGEROUS_REGISTRY_ACTIONS = new Set([
  "project_registry_unregister",
  "project_registry_prune_unavailable",
  "project_registry_prune_temporary",
]);
async function dangerousPostAction(route, payload) {{
  const previewResp = await fetch("/api/dangerous-action/preview", {{
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({{ route: route, payload: payload || {{}} }}),
    cache: "no-store",
  }});
  const preview = await previewResp.json();
  if (!preview.ok) return preview;
  const summary = preview.display_summary || {{}};
  const title = summary.title || route;
  const target = summary.target ? ("\\n目标：" + summary.target) : "";
  if (window.confirm && !window.confirm("确认执行高风险操作：" + title + target)) {{
    return {{ ok: false, error_code: "DANGEROUS_CONFIRMATION_CANCELLED", message: "操作已取消。" }};
  }}
  const body = Object.assign({{}}, payload || {{}}, {{ confirmation_id: preview.confirmation_id }});
  const resp = await fetch(route, {{
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
    cache: "no-store",
  }});
  return await resp.json();
}}
const STATUS_FETCH_TIMEOUT_MS = 12000;
const BACKGROUND_STATUS_POLL_MS = 5000;

let pollTimer = null;
let statusPollTimer = null;
let statusPollInFlight = false;
let pollCount = 0;
const POLL_MAX = 600;
let liveRunActive = false;
let pollExhausted = false;
let latestStatusData = null;
let latestStatusSignature = "";
let todoPage = 1;
let decisionPage = 1;
const TODO_PAGE_SIZE_DEFAULT = 8;
const TODO_PAGE_SIZE_MIN = 3;
const TODO_PAGE_SIZE_MAX = 20;
let adaptiveTodoPageSize = TODO_PAGE_SIZE_DEFAULT;
let adaptiveTodoPageSizeSyncing = false;
const DECISION_PAGE_SIZE = 8;

async function fetchStatus() {{
  const controller = new AbortController();
  const timer = setTimeout(function() {{ controller.abort(); }}, STATUS_FETCH_TIMEOUT_MS);
  try {{
    const resp = await fetch(API, {{ cache: "no-store", signal: controller.signal, headers: readHeaders() }});
    return await resp.json();
  }} finally {{
    clearTimeout(timer);
  }}
}}

async function refresh() {{
  $("loading").style.display = "block";
  $("error").style.display = "none";
  $("content").style.display = "none";
  try {{
    const data = await fetchStatus();
    render(data);
    startLiveRunPolling(data);
    startBackgroundStatusPolling();
  }} catch (e) {{
    showError(String(e));
  }} finally {{
    $("loading").style.display = "none";
  }}
}}

function isLiveRunRunning(lr) {{
  lr = lr || {{}};
  if (lr.available !== true) return false;
  const diagnostics = Array.isArray(lr.diagnostics) ? lr.diagnostics : [];
  if (diagnostics.includes("EXECUTOR_RUN_ORPHANED")) return false;
  if (diagnostics.includes("HEARTBEAT_ONLY_WITH_STALE_PROGRESS")) return false;
  return lr.claim_status === "RUNNING" || lr.claim_status === "running";
}}

function visibleLiveRunDiagnostics(lr, runStatus, hasLiveRun) {{
  lr = lr || {{}};
  const status = String(runStatus || "").toLowerCase();
  const diagnostics = Array.isArray(lr.diagnostics) ? lr.diagnostics : [];
  return diagnostics.filter(d => !(hasLiveRun && status === "running" && d === "RUN_CHANGED_WITHOUT_REPORT"));
}}

function statusSignature(data) {{
  data = data || {{}};
  const lr = data.live_run || {{}};
  const lastOp = data.last_operation_result || null;
  const pieces = [
    data.current_version || "",
    data.runner_status || "",
    lr.available === true ? "available" : "unavailable",
    lr.run_id || "",
    lr.claim_status || "",
    data.operation_running === true ? "op" : "",
    lastOp && lastOp.operation ? (lastOp.operation + ":" + (lastOp.status || "")) : ""
  ];
  return pieces.join("|");
}}

function scheduleBackgroundStatusPoll() {{
  if (statusPollTimer) return;
  statusPollTimer = setTimeout(async function() {{
    statusPollTimer = null;
    if (statusPollInFlight) {{
      scheduleBackgroundStatusPoll();
      return;
    }}
    statusPollInFlight = true;
    try {{
      const newData = await fetchStatus();
      const newSignature = statusSignature(newData);
      if (newSignature !== latestStatusSignature) {{
        render(newData);
        startLiveRunPolling(newData);
      }}
    }} catch (e) {{
      // Background status polling is best-effort: keep the current page visible
      // and try again later instead of surfacing noisy transient errors.
    }} finally {{
      statusPollInFlight = false;
      scheduleBackgroundStatusPoll();
    }}
  }}, BACKGROUND_STATUS_POLL_MS);
}}

function startBackgroundStatusPolling() {{
  if (!latestStatusSignature && latestStatusData) {{
    latestStatusSignature = statusSignature(latestStatusData);
  }}
  scheduleBackgroundStatusPoll();
}}

function scheduleLiveRunPollTick() {{
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = setTimeout(async function() {{
    pollCount++;
    try {{
      const newData = await fetchStatus();
      if (liveRunActive && !isLiveRunRunning(newData.live_run)) {{
        render(newData);
      }} else {{
        updateLiveRunPanel(newData.live_run, newData);
      }}
      startLiveRunPolling(newData, true);
    }} catch (e) {{
      if (liveRunActive && pollCount < POLL_MAX) {{
        pollTimer = setTimeout(function() {{ startLiveRunPolling(null, true); }}, 3000);
      }}
    }}
  }}, 3000);
}}

function startLiveRunPolling(data, fromPoll) {{
  if (fromPoll && !data) {{
    if (liveRunActive && pollCount < POLL_MAX) {{
      scheduleLiveRunPollTick();
    }} else if (liveRunActive) {{
      pollExhausted = true;
      updateLiveRunPanel((latestStatusData && latestStatusData.live_run) || {{}}, null);
    }}
    return;
  }}
  const lr = (data && data.live_run) || {{}};
  const wasActive = liveRunActive;
  liveRunActive = isLiveRunRunning(lr);
  if (liveRunActive && !wasActive) {{
    pollCount = 0;
    pollExhausted = false;
  }}
  if (liveRunActive && pollCount < POLL_MAX) {{
    scheduleLiveRunPollTick();
  }} else if (liveRunActive) {{
    pollExhausted = true;
    updateLiveRunPanel(lr, null);
  }} else if (!liveRunActive && wasActive) {{
    pollExhausted = false;
    if (pollTimer) {{ clearTimeout(pollTimer); pollTimer = null; }}
    if (fromPoll && !data) refresh();
  }}
}}

function showError(msg) {{
  const el = $("error");
  el.textContent = "错误：" + msg;
  el.style.display = "block";
}}

function esc(v) {{
  if (v == null) return "";
  return String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}}

function escAttr(v) {{
  return esc(v).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}}

async function copyTodoId(id, button) {{
  try {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      await navigator.clipboard.writeText(id);
    }} else {{
      const textarea = document.createElement("textarea");
      textarea.value = id;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }}
    const prev = button.textContent;
    button.textContent = "已复制";
    button.disabled = true;
    setTimeout(() => {{
      button.textContent = prev;
      button.disabled = false;
    }}, 1200);
  }} catch (e) {{
    button.title = "复制失败";
  }}
}}

async function copySessionId(sessionId, button) {{
  try {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      await navigator.clipboard.writeText(sessionId);
    }} else {{
      const textarea = document.createElement("textarea");
      textarea.value = sessionId;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }}
    if (button) {{
      const old = button.textContent;
      button.textContent = "[已复制]";
      setTimeout(function() {{ button.textContent = old; }}, 1200);
    }}
  }} catch (e) {{
    if (button) {{
      const old = button.textContent;
      button.textContent = "[复制失败]";
      setTimeout(function() {{ button.textContent = old; }}, 1200);
    }}
  }}
}}

function badgeClass(level) {{
  if (level === "ok" || level === "succeeded" || level === "passed" || level === true) return "badge-ok";
  if (level === "blocked" || level === "failed" || level === "error") return "badge-err";
  if (level === "warning" || level === "warn") return "badge-warn";
  return "badge-info";
}}

function riskLabel(level) {{
  const m = {{
    "info": "低", "read": "低", "warning": "中", "warn": "中",
    "write": "写入", "preview": "预览", "commit": "提交",
    "high": "高", "blocked": "阻断", "error": "错误",
  }};
  return m[level] || "未知";
}}

async function runAction(nextAction, currentData) {{
  $("loading").style.display = "block";
  $("error").style.display = "none";
  try {{
    const payload = {{
      next_action: nextAction,
      client_context: {{
        source_url: window.location.href,
        timestamp: new Date().toISOString(),
      }},
    }};
    const actionName = nextAction && nextAction.action ? String(nextAction.action).toLowerCase() : "";
    const data = DANGEROUS_REGISTRY_ACTIONS.has(actionName)
      ? await dangerousPostAction("/api/v2/action", payload)
      : await (async function() {{
          const resp = await fetch("/api/v2/action", {{
            method: "POST",
            headers: jsonHeaders(),
            body: JSON.stringify(payload),
            cache: "no-store",
          }});
          return await resp.json();
        }})();
    render(data);
  }} catch (e) {{
    showError(String(e));
  }} finally {{
    $("loading").style.display = "none";
  }}
}}

async function switchProject(projectRoot) {{
  if (!projectRoot) return;
  $("loading").style.display = "block";
  $("error").style.display = "none";
  try {{
    const data = await dangerousPostAction("/api/switch-project", {{ project_root: projectRoot }});
    if (!data.ok) {{
      showError(data.message || data.error_code || "项目切换失败");
      await refresh();
      return;
    }}
    render(data.status || data);
  }} catch (e) {{
    showError(String(e));
  }} finally {{
    $("loading").style.display = "none";
  }}
}}

function sb(v) {{ return v != null && v !== false ? esc(String(v)) : "-"; }}
function r(label, value) {{
  return `<div class="compact-row"><span class="key">${{esc(label)}}：</span><span class="val">${{sb(value)}}</span></div>`;
}}
function issueLink(label, count, kind) {{
  const n = Number(count || 0);
  if (n <= 0) return r(label, 0);
  return `<div class="compact-row"><span class="key">${{esc(label)}}：</span><button type="button" class="issue-count-link" onclick="openIssueModal('${{kind}}')">${{esc(n)}}</button></div>`;
}}

function render(data) {{
  latestStatusData = data || {{}};
  latestStatusSignature = statusSignature(latestStatusData);
  renderProjectSwitcher(data);
  renderLeftColumn(data);
  renderCenterColumn(data);
  renderRightColumn(data);
  renderProjectManagementModal(data);
  $("content").style.display = "block";
}}

function currentProjectRootForSwitcher(data) {{
  const candidates = [
    data && data.project_identity && data.project_identity.project_root,
    data && data.fact_snapshot && data.fact_snapshot.project_identity && data.fact_snapshot.project_identity.project_root,
  ];
  for (const candidate of candidates) {{
    if (candidate != null && candidate !== "") return String(candidate);
  }}
  return "";
}}

function renderProjectSwitcher(data) {{
  const select = $("project-select");
  if (!select) return;
  const registry = data.project_registry || {{}};
  const projects = Array.isArray(registry.projects) ? registry.projects : [];
  const currentRoot = currentProjectRootForSwitcher(data || {{}});
  select.innerHTML = "";
  if (!projects.length) {{
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "未登记";
    select.appendChild(opt);
    select.disabled = true;
    return;
  }}
  for (const project of projects) {{
    const root = project && project.project_root ? String(project.project_root) : "";
    if (!root) continue;
    const opt = document.createElement("option");
    opt.value = root;
    opt.textContent = (project.manifest && project.manifest.friendly_label) || project.display_name || project.project_name || root;
    opt.title = root;
    select.appendChild(opt);
  }}
  select.disabled = projects.length < 2;
  select.value = currentRoot;
  if (currentRoot && select.value !== currentRoot) {{
    const opt = document.createElement("option");
    opt.value = currentRoot;
    opt.textContent = currentRoot;
    opt.title = currentRoot;
    select.appendChild(opt);
    select.value = currentRoot;
  }}
  select.onchange = function() {{
    if (this.value) switchProject(this.value);
  }};
}}

function renderLeftColumn(data) {{
  const fs = data.fact_snapshot || {{}};
  const pi = fs.project_identity || {{}};
  const gs = fs.git_status || {{}};
  const ps = fs.plan_status || {{}};
  const lr = fs.latest_report || {{}};
  const ar = fs.active_run || {{}};
  const sessionDisplay = data.executor_session_display || {{}};
  const clean = gs.working_tree_clean === true ? "干净" : gs.working_tree_clean === false ? "有改动" : "-";
  const changedCount = (gs.changed_files || []).length;
  const untrackedCount = (gs.untracked_files || []).length;
  const planText = ps.has_plan ? "存在" : "无";
  const stateText = ps.has_state ? "存在" : "无";
  const lintOk = ps.lint_status && ps.lint_status.has_lint === false;
  const lintText = lintOk ? "通过" : ps.lint_status ? "待检查" : "-";
  const blockerCount = Array.isArray(data.blockers) && data.blockers.length ? data.blockers.length : (ps.lint_blocking_issue_count || 0);
  const warningCount = Array.isArray(data.warnings) ? data.warnings.length : 0;
  const reportText = lr.available ? "可用" : "无";
  let sessionText = sessionDisplay.text ? String(sessionDisplay.text).replace(/^执行会话：/, "") : "";
  if (!sessionText) sessionText = ar.has_session ? "已记录（状态待判定）" : "未记录";

  let h = "";
  h += `<div class="card left-tab-card">`;
  h += `<div class="tab-bar">`;
  h += `<button class="tab-btn active" data-left-tab-button="overview" onclick="switchLeftTab('overview', this)"><span class="tab-icon">◉</span>项目总览</button>`;
  h += `<button class="tab-btn" data-left-tab-button="versionplan" onclick="switchLeftTab('versionplan', this)"><span class="tab-icon">☰</span>版本计划</button>`;
  h += `</div>`;

  h += `<div class="tab-content" data-left-tab="overview">`;
  h += `<div class="compact-card" style="margin-bottom:0;">`;
  h += r("项目", pi.project_name || "-");
  h += `<div class="compact-row"><span class="key">代码：</span><span class="val">分支 ${{sb(pi.git_branch)}} ｜ 提交 ${{sb(pi.git_head_short)}}</span></div>`;
  h += `<div class="compact-row"><span class="key">版本：</span><span class="val">当前 ${{sb(fs.current_version)}} ｜ 下一 ${{sb(fs.next_version)}}</span></div>`;
  h += `<div class="compact-row"><span class="key">工作区：</span><span class="val">${{esc(clean)}} ｜ 改动文件 ${{sb(changedCount)}}</span></div>`;
  h += `<div class="compact-row"><span class="key">计划：</span><span class="val">计划文件 ${{esc(planText)}} ｜ 运行状态 ${{esc(stateText)}}</span></div>`;
  h += issueLink("阻断问题", blockerCount, "blockers");
  h += issueLink("警告", warningCount, "warnings");
  h += `<div class="compact-row"><span class="key">执行：</span><span class="val">报告 ${{esc(reportText)}} ｜ 会话 ${{esc(sessionText)}}</span></div>`;
  h += `<div style="margin-top:8px;">`;
  if (fs.next_not_started_version != null) h += r("下一未开始", fs.next_not_started_version);
  if (fs.pending_count != null) h += r("挂起版本", fs.pending_count);
  h += r("未跟踪文件", untrackedCount);
  h += r("可提交", fs.can_commit === true ? "是" : fs.can_commit === false ? "否" : "-");
  h += r("规则检查", lintText);
  if (ar.continuation_available != null) h += r("可继续", ar.continuation_available ? "是" : "否");
  if (lr.count != null) h += r("报告数", lr.count);
  if (lr.latest && lr.latest.version) h += r("最新版本", lr.latest.version);

  h += `</div>`;
  h += `</div>`;
  h += `</div>`;

  h += `<div class="tab-content" data-left-tab="versionplan" style="display:none;">`;
  h += renderVersionPlan(data);
  h += `</div>`;
  h += `</div>`;

  $("layout-left").innerHTML = h;
}}

function displayVersionName(v) {{
  const name = v.name || "";
  const desc = v.description || "";
  if (/^Version v\\d/.test(name) && desc && !/^从 prompt 文件/.test(desc) && !/^From prompt/.test(desc)) {{
    return desc;
  }}
  return name || v.version;
}}

function versionRuntimeDone(v) {{
  const status = String(v.runtime_status || "").toUpperCase();
  return status === "PASSED" || status === "FAILED" || status === "COMPLETED";
}}

function versionStatusLabel(v) {{
  if (!v.enabled) return "已禁用";
  if (versionRuntimeDone(v)) return "开发完";
  if (v.is_current) return "开发中";
  return "未开发";
}}

function versionStatusBadgeClass(v) {{
  if (!v.enabled) return "badge-err";
  if (versionRuntimeDone(v)) return "badge-ok";
  if (v.is_current) return "badge-info";
  return "badge-warn";
}}

function renderVersionPlan(data) {{
  const versions = Array.isArray(data.plan_versions) ? data.plan_versions : [];
  if (!versions.length) {{
    return `<div class="empty-state">暂无版本计划</div>`;
  }}

  const ordered = [...versions].reverse();

  let h = "";
  h += `<div class="compact-card" style="margin-bottom:0;">`;
  for (const v of ordered) {{
    const ver = esc(v.version);
    const label = esc(displayVersionName(v));
    const statusText = versionStatusLabel(v);
    const badgeCls = versionStatusBadgeClass(v);
    h += `<div class="version-item">`;
    h += `<div class="version-row-main">`;
    h += `<span class="version-version">${{ver}}</span>`;
    h += `<span class="badge ${{badgeCls}}">${{esc(statusText)}}</span>`;
    h += `</div>`;
    h += `<button class="version-title-link" data-version="${{escAttr(v.version)}}" onclick="openVersionPromptModal(this.dataset.version)">${{label}}</button>`;
    h += `</div>`;
  }}
  h += `</div>`;
  return h;
}}

function liveRunEventLabel(evt) {{
  const t = evt.event_type || evt.event || "";
  const d = evt.data || {{}};
  const provider = d.provider || evt.provider || "执行器";
  if (t === "heartbeat") {{
    if (d.lifecycle_point === "worker_started") return "Runner 工作线程已启动";
    if (d.lifecycle_point === "before_report") return "执行结束，正在整理报告";
    return "Runner 仍在等待执行器";
  }}
  if (t === "executor_preparing") return `准备启动 ${{provider}} 执行器`;
  if (t === "executor_started") return `${{provider}} 已启动，正在执行任务`;
  if (t === "executor_finished") return `${{provider}} 已返回结果`;
  if (t === "executor_failed") return `${{provider}} 执行失败`;
  if (t === "executor_tool_event" && d.stage === "provider_terminal_evidence") return "执行器服务返回错误事实";
  if (t === "executor_tool_event" && d.stage === "prompt_send_stalled") return "执行器服务等待已停滞";
  if (t === "executor_tool_event" && d.stage === "server_wait_fact") return "执行器服务状态已更新";
  if (t === "executor_tool_event" && d.stage === "prompt_send_started") return "提示词已发送到执行器服务";
  if (t === "validation_started") return "开始运行验收命令";
  if (t === "validation_finished") return d.run_status === "PASSED" ? "验收通过" : "验收未通过";
  if (t === "git_diff_changed") return `检测到 ${{d.changed_file_count || 0}} 个文件改动`;
  if (t === "report_written") return "执行报告已生成";
  if (t === "run_completed") return "任务已完成";
  if (t === "run_failed") return "任务失败";
  if (t === "run_claimed") return "执行任务已领取";
  if (t === "worker_started") return "Runner 工作线程已启动";
  return evt.message || t || "执行事件";
}}

function liveRunEventDetail(evt) {{
  const t = evt.event_type || evt.event || "";
  const d = evt.data || {{}};
  if (t === "executor_preparing") {{
    const version = d.current_version || evt.version || "-";
    const mode = d.execution_mode || evt.execution_mode || "run";
    return `版本 ${{version}} · 模式 ${{mode}}`;
  }}
  if (t === "executor_started") return "这一步可能持续几分钟；如果执行器没有流式输出，Runner 会等它结束后再显示后续结果。";
  if (t === "executor_finished") return "执行器进程已结束，Runner 正在检查改动并运行验收。";
  if (t === "executor_failed") return d.message || d.error_code || "执行器失败，但没有返回详细错误。";
  if (t === "executor_tool_event" && d.stage === "provider_terminal_evidence") return d.message || d.error_code || d.terminal_reason || "provider/server 返回 terminal error。";
  if (t === "executor_tool_event" && d.stage === "prompt_send_stalled") return d.message || d.summary || "提示词发送后长时间没有 response、message part 或业务进展。";
  if (t === "executor_tool_event" && d.stage === "server_wait_fact") {{
    const st = d.session_status && d.session_status.status ? d.session_status.status : "";
    return st ? "server status: " + st : "已读取 server event/status/message 事实。";
  }}
  if (t === "executor_tool_event" && d.stage === "prompt_send_started") return "Runner 正在等待执行器服务返回 response 或 server event/status/error 事实。";
  if (t === "validation_finished") return `验收命令 ${{d.total_commands || 0}} 个，失败 ${{d.failed_count || 0}} 个。`;
  if (t === "git_diff_changed") {{
    const bizFiles = Array.isArray(d.changed_files) ? d.changed_files.slice(0, 5) : [];
    const metaFiles = Array.isArray(d.runner_metadata_changed_files) ? d.runner_metadata_changed_files.slice(0, 3) : [];
    const bizCount = d.changed_file_count || 0;
    const metaCount = d.runner_metadata_changed_file_count || 0;
    const bizPart = bizFiles.length ? "业务(" + bizCount + ")：" + bizFiles.join(", ") + (bizCount > bizFiles.length ? " …" : "") : "";
    const metaPart = metaFiles.length ? "元数据(" + metaCount + ")：" + metaFiles.join(", ") + (metaCount > metaFiles.length ? " …" : "") : "";
    if (!bizPart && !metaPart) return "已检测到改动，详细内容见报告或 Git diff。";
    return [bizPart, metaPart].filter(Boolean).join("\\n");
  }}
  if (t === "report_written") return d.report_status ? `报告状态：${{d.report_status}}` : "报告已写入本地运行记录。";
  if (t === "run_completed") return d.classification ? `结果分类：${{d.classification}}` : "可以查看报告。";
  if (t === "run_failed") return d.message || d.error_code || d.classification || "请查看报告或日志定位原因。";
  return "";
}}

function liveRunCardStatusClass(lr, runStatus, hasLiveRun) {{
  lr = lr || {{}};
  const status = String(runStatus || "").toLowerCase();
  const blockingDiagnostics = visibleLiveRunDiagnostics(lr, runStatus, hasLiveRun);
  if (blockingDiagnostics.length > 0) return "problem";
  if (hasLiveRun && status === "running") return "running";
  if (status === "failed" || status === "error" || status === "blocked" || status === "orphaned") return "problem";
  return "idle";
}}

function normalizeExecutorCardData(lr, data) {{
  lr = lr || {{}};
  data = data || {{}};
  const fs = data.fact_snapshot || {{}};
  const latestReportBox = fs.latest_report || {{}};
  const latestReport = latestReportBox.latest || {{}};
  const hasLiveRun = lr.available === true;
  const hasLastReport = !hasLiveRun && latestReportBox.available === true && !!latestReport;
  const claim = lr.claim || {{}};
  const src = hasLiveRun ? lr : latestReport;
  return {{
    hasLiveRun: hasLiveRun,
    hasLastReport: hasLastReport,
    runId: src.run_id || "",
    previewId: src.preview_id || "",
    reportId: src.report_id || "",
    provider: claim.provider || latestReport.provider || "-",
    executorModel: lr.executor_model || latestReport.executor_model || latestReport.model || claim.model || claim.model_name || "",
    executorDisplay: lr.executor_display || (function() {{
      const p = claim.provider || latestReport.provider || "-";
      const m = lr.executor_model || latestReport.executor_model || latestReport.model || "";
      return p && m ? p + " + " + m : p;
    }})(),
    sessionId: lr.session_identity_value || lr.session_id_full || latestReport.session_id_full || "",
    sessionModeLabel: lr.session_mode_label || latestReport.session_mode_label || "新开",
    sessionLabel: lr.session_identity_label || "会话标识",
    events: hasLiveRun && Array.isArray(lr.events) ? lr.events : (Array.isArray(latestReport.events) ? latestReport.events : []),
    diagnostics: Array.isArray(lr.diagnostics) ? lr.diagnostics : [],
    claim: claim,
    latestReport: latestReport,
    latestReportChangedFiles: Array.isArray(latestReport.changed_files) ? latestReport.changed_files : null,
    businessCount: hasLiveRun ? lr.changed_file_count : (hasLastReport && Array.isArray(latestReport.changed_files) ? latestReport.changed_files.length : null),
    metadataCount: hasLiveRun ? lr.runner_metadata_changed_file_count : 0,
    reportAvailable: hasLiveRun ? lr.report_available : latestReportBox.available === true,
    changedFiles: hasLiveRun && Array.isArray(lr.changed_files) ? lr.changed_files : null,
  }};
}}

function lastMeaningfulStage(events) {{
  if (!Array.isArray(events) || !events.length) return "";
  const stageNames = [
    "run_completed", "report_written", "validation_finished",
    "git_diff_changed", "executor_finished", "executor_failed",
    "executor_started", "executor_preparing", "worker_started",
    "run_claimed"
  ];
  for (let i = events.length - 1; i >= 0; i--) {{
    const t = events[i].event_type || events[i].event || "";
    for (const stage of stageNames) {{
      if (t === stage) return stage;
    }}
  }}
  return "";
}}

function renderLiveRunPanel(lr, data) {{
  lr = lr || {{}};
  data = data || {{}};
  const fs = data.fact_snapshot || {{}};
  const ds = data.display_summary || {{}};
  const latestReportBox = fs.latest_report || {{}};
  const latestReport = latestReportBox.latest || {{}};
  const hasLiveRun = lr.available === true;
  const hasLastReport = !hasLiveRun && latestReportBox.available === true && !!latestReport;
  const opRunning = data.operation_running === true;
  const lastOp = data.last_operation_result || null;
  const lastOpFailed = lastOp && lastOp.status === "failed" && (lastOp.operation && (lastOp.operation.includes("run") || lastOp.operation.includes("fix")));
  const isStarting = opRunning && !hasLiveRun;
  const isBlocked = !opRunning && !hasLiveRun && lastOpFailed;

  let taskTitle = "当前任务";
  const currentVer = fs.current_version || "";
  const latestReportIsCurrent = hasLastReport && currentVer && latestReport.version === currentVer;
  const pendingVersions = Array.isArray(fs.pending_versions) ? fs.pending_versions : [];
  const currentPending = pendingVersions.find(v => v && v.version === currentVer) || {{}};
  const taskName = currentPending.name || currentPending.description || (ds.title && ds.title !== "操作成功" ? ds.title : "");
  if (isBlocked) {{
    taskTitle = "启动被阻断";
  }} else if (isStarting) {{
    taskTitle = "正在启动执行器…";
  }} else if (hasLastReport && latestReport.version) {{
    const reportVer = latestReport.version;
    if (latestReportIsCurrent) {{
      taskTitle = "当前版本：" + currentVer;
    }} else {{
      taskTitle = "上次结果（" + reportVer + "）";
    }}
  }} else if (currentVer && taskName && data.status !== "failed") {{
    taskTitle = "当前任务：" + currentVer + " " + taskName;
  }} else if (currentVer && data.status !== "failed") {{
    taskTitle = "当前任务：" + currentVer;
  }}

  const claim = lr.claim || {{}};
  const provider = claim.provider || latestReport.provider || "-";
  const executorModel = lr.executor_model || latestReport.executor_model || latestReport.model || latestReport.model_name || claim.model || claim.model_name || "";
  const executorDisplay = lr.executor_display || (provider && executorModel ? provider + " + " + executorModel : provider);
  const diagnostics = Array.isArray(lr.diagnostics) ? lr.diagnostics : [];
  const events = hasLiveRun && Array.isArray(lr.events) ? lr.events : (!isBlocked && Array.isArray(latestReport.events) ? latestReport.events : []);
  const orphaned = diagnostics.includes("EXECUTOR_RUN_ORPHANED");
  const progressStalled = diagnostics.includes("HEARTBEAT_ONLY_WITH_STALE_PROGRESS") || lr.progress_stalled === true;
  const runStatus = hasLiveRun ? (lr.claim_status || "unknown") : (hasLastReport ? (latestReport.status || "completed") : "empty");
  let statusText = "执行器暂无结果";
  if (isStarting) statusText = "正在启动执行器…";
  else if (isBlocked) statusText = "启动被阻断：" + (lastOp.message || "操作失败");
  else if (hasLiveRun && orphaned) statusText = "执行器已失联";
  else if (hasLiveRun && progressStalled) statusText = "执行器业务进展停滞";
  else if (hasLiveRun && (runStatus === "RUNNING" || runStatus === "running")) statusText = "执行器运行中" + (pollExhausted ? "（数据可能已过期）" : "");
  else if (hasLiveRun && (runStatus === "COMPLETED" || runStatus === "completed")) statusText = "执行器已完成";
  else if (hasLiveRun && (runStatus === "FAILED" || runStatus === "failed")) statusText = "执行器失败";
  else if (hasLastReport && latestReportIsCurrent && latestReport.status === "completed") statusText = "✅ 开发完成，成功生成报告";
  else if (hasLastReport && latestReportIsCurrent && latestReport.status === "failed") statusText = "☑️ 开发完成，报告生成失败";
  else if (hasLastReport && latestReport.status === "completed") statusText = "上次报告已完成";
  else if (hasLastReport && latestReport.status === "failed") statusText = "上次报告失败";
  else if (hasLastReport) statusText = "上次报告：" + latestReport.status;

  let cardStatusClass = liveRunCardStatusClass(lr, runStatus, hasLiveRun);
  if (isBlocked) cardStatusClass = "problem";
  else if (isStarting) cardStatusClass = "running";
  let h = `<div class="card summary-card live-run-card live-run-panel ${{cardStatusClass}}">`;
  h += `<div class="card-title">${{esc(taskTitle)}}</div>`;
  h += `<div class="summary-title">${{esc(statusText)}}</div>`;
  const visibleDiagnostics = visibleLiveRunDiagnostics(lr, runStatus, hasLiveRun);
  if (visibleDiagnostics.length) {{
    for (const d of visibleDiagnostics) {{
      const cls = d.includes("ORPHANED") ? "err" : "warn";
      h += `<span class="live-run-diagnostic ${{cls}}">${{esc(d)}}</span>`;
    }}
  }}
  h += r("执行器", executorDisplay);
  if (isBlocked) {{
    const blockers = Array.isArray(lastOp.blockers) ? lastOp.blockers : [];
    const warnings = Array.isArray(lastOp.warnings) ? lastOp.warnings : [];
    if (blockers.length || warnings.length) {{
      h += `<div style="border-top:1px solid #f85149;margin:8px 0 8px 0;"></div>`;
      h += `<div class="key" style="color:#f85149;margin-bottom:4px;">阻断详情</div>`;
      for (const blk of blockers) {{
        h += `<div style="font-size:12px;color:#f85149;padding:2px 0;">• ${{esc(typeof blk === 'string' ? blk : (blk.message || blk.reason || JSON.stringify(blk)))}}</div>`;
      }}
      for (const w of warnings) {{
        h += `<div style="font-size:12px;color:#d29922;padding:2px 0;">⚠ ${{esc(typeof w === 'string' ? w : (w.message || w.reason || JSON.stringify(w)))}}</div>`;
      }}
    }}
    if (lastOp.message && !blockers.length) {{
      h += `<div class="key" style="color:#f85149;margin-bottom:4px;">阻断原因</div>`;
      h += `<div style="font-size:12px;color:#f85149;padding:2px 0;">${{esc(lastOp.message)}}</div>`;
    }}
    h += `<div style="border-top:1px solid #30363d;margin:8px 0 8px 0;"></div>`;
    h += `<div style="font-size:11px;color:#8b949e;padding:4px 0;">上次运行记录可参考下方历史信息</div>`;
  }} else {{
    h += r("运行 ID", hasLiveRun ? lr.run_id : (latestReport.run_id || "-"));
    h += r("Preview ID", lr.preview_id || latestReport.preview_id || "-");
    h += r("报告 ID", lr.report_id || latestReport.report_id || "-");
  }}

  const stageLabel = lastMeaningfulStage(events);
  if (stageLabel) h += r("最后阶段", stageLabel);

  if (!isBlocked) {{
    const sessionModeLabel = lr.session_mode_label || latestReport.session_mode_label || (lr.session_mode === "resume" ? "续接" : "新开");
    const sessionLabel = lr.session_identity_label || "会话标识";
    const sessionId = lr.session_identity_value || lr.session_id_full || latestReport.session_id_full || "";
    h += `<div class="compact-row live-session-row"><span class="key">${{esc(sessionLabel)}}：</span><span class="val live-session-value">`;
    if (sessionId) {{
      h += `<span class="live-session-id">${{esc(sessionId)}}</span>`;
      h += `<span class="live-session-separator">｜</span>`;
      h += `<span class="live-session-mode">${{esc(sessionModeLabel)}}</span>`;
      h += `<button type="button" class="live-session-copy" title="复制会话标识" aria-label="复制会话标识" onclick="copySessionId('${{escAttr(sessionId)}}', this)">⧉</button>`;
    }} else {{
      h += `<span class="live-session-id">无</span><span class="live-session-separator">｜</span><span class="live-session-mode">${{esc(sessionModeLabel)}}</span>`;
    }}
    h += `</span></div>`;
  }}

  const latestReportChangedFiles = !isBlocked && Array.isArray(latestReport.changed_files) ? latestReport.changed_files : null;
  const businessCount = hasLiveRun ? lr.changed_file_count : (hasLastReport && latestReportChangedFiles ? latestReportChangedFiles.length : null);
  const metadataCount = hasLiveRun ? lr.runner_metadata_changed_file_count : 0;
  const reportAvailable = hasLiveRun ? lr.report_available : latestReportBox.available === true;
  if (!isBlocked) {{
    let heartbeatText = "-";
    if (lr.heartbeat) {{
      const age = lr.heartbeat.age_seconds != null ? Math.round(lr.heartbeat.age_seconds) + "s" : "-";
      const stale = lr.heartbeat.stale ? "（已过期）" : "";
      heartbeatText = age + stale;
    }}
    let progressText = "-";
    const mp = lr.last_meaningful_progress || {{}};
    if (mp && mp.available) {{
      const age = mp.age_seconds != null ? Math.round(mp.age_seconds) + "s" : "-";
      const stale = mp.stale ? "（已过期）" : "";
      progressText = age + stale;
    }}
    h += `<div class="compact-row" style="display:flex;flex-wrap:wrap;gap:2px 0;font-size:13px;padding:4px 0;border-bottom:1px solid #21262d;">`;
    h += `<span class="key">业务改动：</span><span class="val">${{sb(businessCount)}}</span>`;
    h += `<span style="margin:0 4px;color:#8b949e;">｜</span>`;
    h += `<span class="key">Runner 元数据：</span><span class="val">${{sb(metadataCount)}}</span>`;
    h += `<span style="margin:0 4px;color:#8b949e;">｜</span>`;
    h += `<span class="key">报告可用：</span><span class="val">${{reportAvailable ? "是" : "否"}}</span>`;
    h += `<span style="margin:0 4px;color:#8b949e;">｜</span>`;
    h += `<span class="key">心跳：</span><span class="val">${{esc(heartbeatText)}}</span>`;
    h += `<span style="margin:0 4px;color:#8b949e;">｜</span>`;
    h += `<span class="key">业务进展：</span><span class="val">${{esc(progressText)}}</span>`;
    h += `</div>`;

    if (hasLiveRun && businessCount > 0 && Array.isArray(lr.changed_files)) {{
      const preview = lr.changed_files.slice(0, 8).join(", ");
      h += `<div style="font-size:11px;color:#8b949e;padding:6px 0 4px 0;word-break:break-all;">改动文件：${{esc(preview)}}${{businessCount > 8 ? " …" : ""}}</div>`;
    }} else if (hasLastReport && latestReportChangedFiles) {{
      const preview = latestReportChangedFiles.slice(0, 8).join(", ");
      const changedFilesLabel = latestReportIsCurrent ? "当前版本" : "上次结果";
      h += `<div style="font-size:11px;color:#8b949e;padding:6px 0 4px 0;word-break:break-all;">改动文件（${{changedFilesLabel}}）：${{esc(preview)}}${{businessCount > 8 ? " …" : ""}}</div>`;
    }} else if (hasLastReport) {{
      const changedFilesMissingText = latestReportIsCurrent ? "当前版本未提供文件列表" : "上次结果未提供文件列表";
      h += `<div style="font-size:11px;color:#8b949e;padding:6px 0 4px 0;word-break:break-all;">改动文件：${{changedFilesMissingText}}</div>`;
    }} else {{
      h += `<div style="font-size:11px;color:#8b949e;padding:6px 0 4px 0;word-break:break-all;">改动文件：无</div>`;
    }}
    if (metadataCount > 0 && Array.isArray(lr.runner_metadata_changed_files)) {{
      const metadataPreview = lr.runner_metadata_changed_files.slice(0, 5).join(", ");
      h += `<div style="font-size:11px;color:#8b949e;padding:2px 0 4px 0;word-break:break-all;">Runner 元数据：${{esc(metadataPreview)}}${{metadataCount > 5 ? " …" : ""}}</div>`;
    }}

    h += `<div style="border-top:1px solid #30363d;margin:8px 0 8px 0;"></div>`;
    h += `<div class="key" style="margin-bottom:4px;">最近事件</div>`;
    h += `<div class="live-run-events-scroll">`;
    if (events.length) {{
      h += renderLiveRunEvents(events.slice(-10));
    }} else {{
      h += `<div class="empty-state">暂无执行器事件</div>`;
    }}
    h += `</div>`;
  }}

  if (!isBlocked && latestReport && latestReport.token_usage) {{
    const tu = latestReport.token_usage;
    if (tu.available === true) {{
      const totalIn = tu.prompt_input_tokens != null ? Number(tu.prompt_input_tokens).toLocaleString() : "-";
      const freshIn = tu.fresh_input_tokens != null ? Number(tu.fresh_input_tokens).toLocaleString() : "-";
      const cacheRead = tu.cache_read_tokens != null ? Number(tu.cache_read_tokens).toLocaleString() : "-";
      const fo = tu.output_tokens != null ? Number(tu.output_tokens).toLocaleString() : "-";
      const fr = tu.reasoning_output_tokens != null ? Number(tu.reasoning_output_tokens).toLocaleString() : "0";
      const ft = tu.total_tokens != null ? Number(tu.total_tokens).toLocaleString() : "-";
      let fh = tu.cache_hit_rate_percent || "-";
      if (fh === "-" && totalIn !== "-" && Number(totalIn.replace(/,/g, "")) > 0) {{
        fh = "数据不足";
      }}
      h += `<div style="border-top:1px solid #30363d;margin:8px 0 8px 0;"></div>`;
      h += `<div class="compact-row" style="font-size:13px;padding:4px 0;">`;
      h += '<span class="key">Token：</span><span class="val">' + totalIn + ' 总输入 / ' + freshIn + ' 新 / ' + cacheRead + ' 缓存 / ' + fo + ' 输出 / ' + fr + ' 推理 / ' + fh + ' 命中 / ' + ft + ' 合计</span>';
      h += `</div>`;
      if (Array.isArray(tu.warnings) && tu.warnings.length) {{
        h += '<div style="font-size:11px;color:#d29922;padding:2px 0 4px 0;">Token 数据可能存在偏差</div>';
      }}
    }} else {{
      let unavailableText = "Token usage unavailable";
      let labelParts = [];
      if (tu.source) labelParts.push(esc(String(tu.source)));
      if (tu.provider) labelParts.push(esc(String(tu.provider)));
      if (labelParts.length) unavailableText += " (" + labelParts.join(", ") + ")";
      h += `<div style="border-top:1px solid #30363d;margin:8px 0 8px 0;"></div>`;
      h += `<div class="compact-row" style="font-size:13px;padding:4px 0;">`;
      h += '<span class="key">Token：</span><span class="val">' + unavailableText + '</span>';
      h += `</div>`;
      if (Array.isArray(tu.warnings) && tu.warnings.length) {{
        const tokenWarnings = tu.warnings.map(w => esc(String(w))).join(", ");
        h += '<div style="font-size:11px;color:#d29922;padding:2px 0 4px 0;">' + tokenWarnings + '</div>';
      }}
    }}
  }}

  h += `</div>`;
  return h;
}}

function renderThinGovernedLoopPreview(data) {{
  data = data || {{}};
  const preview = data.thin_governed_loop_preview || {{}};
  const result = preview.result || {{}};
  const thinLoop = result.thin_loop || {{}};
  const summary = result.summary || {{}};
  const status = thinLoop.thin_loop_status || summary.thin_loop_status || preview.status || "unknown";
  const passed = status === "thin_governed_loop_passed" || result.ok === true;
  const blocked = status === "thin_governed_loop_failed_closed" || preview.ok === false;
  const cardClass = blocked && !passed ? "blocked" : "";
  const badgeCls = passed ? "badge-ok" : (blocked ? "badge-err" : "badge-warn");
  const statusLabel = passed ? "链路可用" : (blocked ? "链路阻断" : "状态未知");
  const statusText = passed ? "薄治理闭环观察可用" : (blocked ? "薄治理闭环观察已阻断" : "薄治理闭环观察不可用");
  const blockers = Array.isArray(thinLoop.blockers) ? thinLoop.blockers : (Array.isArray(preview.blockers) ? preview.blockers : []);
  const pathLabels = {{
    "external_taskbook_import": "导入任务书",
    "execution_envelope": "执行 Envelope",
    "local_execution_receipt": "本地 Receipt",
    "reviewer_handoff_package": "Reviewer Handoff",
    "review_feedback_intake": "Feedback Intake",
  }};
  const rawPath = Array.isArray(thinLoop.thin_loop_path) && thinLoop.thin_loop_path.length
    ? thinLoop.thin_loop_path
    : ["external_taskbook_import", "execution_envelope", "local_execution_receipt", "reviewer_handoff_package", "review_feedback_intake"];
  const path = rawPath.map(item => pathLabels[item] || item).join(" -> ");
  const requestedAction = result.requested_commander_action || summary.requested_commander_action || thinLoop.requested_commander_action || "-";
  const requestedActionLabels = {{
    "ask_whether_to_prepare_rework_or_gate_return": "请 Commander 决定：返工准备，还是回到状态门",
    "ask_whether_to_return_for_clarification": "请 Commander 补充澄清",
    "none": "暂无人工动作",
  }};
  const requestedActionText = requestedActionLabels[requestedAction] || requestedAction;
  const inputMode = result.input_mode || "-";
  const inputModeLabels = {{
    "provided": "真实输入",
    "example": "样例自检",
    "template": "输入契约",
    "draft": "输入草稿",
  }};
  const inputModeText = inputModeLabels[inputMode] || inputMode;
  let h = `<div class="card summary-card thin-loop-preview-card ${{cardClass}}">`;
  h += `<div class="card-title">Stage 3-6 薄治理闭环观察</div>`;
  h += `<div class="summary-title">${{esc(statusText)}}</div>`;
  h += `<div class="badge-row">`;
  h += `<span class="badge ${{badgeCls}}">${{esc(statusLabel)}}</span>`;
  h += `<span class="badge badge-info">只读观察</span>`;
  h += `<span class="badge badge-info">${{esc(inputModeText)}}</span>`;
  h += `</div>`;
  h += `<div class="thin-loop-path">${{esc(path)}}</div>`;
  h += r("阻断数", blockers.length);
  h += r("Commander 下一步", requestedActionText);
  h += `<div class="thin-loop-boundary">只读预览，不授权执行器、ReviewDecision、GateEvent、Delivery State、commit 或 push。</div>`;
  h += `</div>`;
  return h;
}}

function collapseConsecutiveEvents(events) {{
  if (!events || !events.length) return [];
  const result = [];
  let current = null;
  for (const evt of events) {{
    const label = liveRunEventLabel(evt);
    const detail = liveRunEventDetail(evt);
    const ts = evt.timestamp || evt.ts || "";
    const tsStr = ts ? ts.slice(11, 19) : "";
    const groupKey = label + "\\n" + detail;
    if (current && current.groupKey === groupKey) {{
      current.count++;
      current.ts = tsStr;
    }} else {{
      if (current) result.push(current);
      current = {{ groupKey: groupKey, label: label, detail: detail, ts: tsStr, count: 1 }};
    }}
  }}
  if (current) result.push(current);
  return result;
}}

function renderLiveRunEvents(events) {{
  const collapsed = collapseConsecutiveEvents(events);
  let h = "";
  for (const evt of collapsed) {{
    const titleSuffix = evt.count > 1 ? "（X" + evt.count + "）" : "";
    const detailLines = evt.detail ? evt.detail.split("\\n") : [];
    h += `<div class="live-run-event">`;
    h += `<span class="evt-ts">${{esc(evt.ts)}}</span>`;
    h += `<div class="evt-content">`;
    h += `<div class="evt-title">${{esc(evt.label)}}${{titleSuffix}}</div>`;
    for (let i = 0; i < detailLines.length; i++) {{
      h += `<div class="evt-detail">${{esc(detailLines[i])}}</div>`;
    }}
    h += `</div></div>`;
  }}
  return h;
}}

function updateLiveRunPanel(liveRun, statusData) {{
  if (statusData && typeof statusData === "object") {{
    latestStatusData = statusData;
    renderCenterColumn(statusData);
    return;
  }}
  const slot = $("live-run-panel-slot");
  if (slot) slot.innerHTML = renderLiveRunPanel(liveRun, latestStatusData || {{}});
}}

function renderCenterColumn(data) {{
  data = data || {{}};
  const liveRun = data.live_run || {{}};
  let h = `<div id="center-observation-stack">`;
  h += `<div id="live-run-panel-slot">${{renderLiveRunPanel(liveRun, data)}}</div>`;
  h += renderThinGovernedLoopPreview(data);
  h += `</div>`;
  $("layout-center").innerHTML = h;
}}

function registryAction(actionName, params) {{
  $("loading").style.display = "block";
  $("error").style.display = "none";
  const payload = {{
    next_action: {{
      action: actionName,
      params: params || {{}},
      label: "项目管理操作",
    }},
    client_context: {{
      source_url: window.location.href,
      timestamp: new Date().toISOString(),
    }},
  }};
  dangerousPostAction("/api/v2/action", payload)
    .then(function(data) {{
      render(data);
      $("loading").style.display = "none";
    }})
    .catch(function(e) {{
      showError(String(e));
      $("loading").style.display = "none";
    }});
}}

let projectIdentityPreviewId = "";
let projectIdentityEditor = null;

function clearProjectIdentityPreview() {{
  projectIdentityPreviewId = "";
  const applyBtn = $("project-identity-apply");
  if (applyBtn) applyBtn.disabled = true;
}}

function openProjectIdentityEditor(button) {{
  clearProjectIdentityPreview();
  projectIdentityEditor = {{
    project_id: button.dataset.projectId || "",
    project_name: button.dataset.projectName || "",
    display_name: button.dataset.displayName || button.dataset.projectName || "",
    project_root: button.dataset.projectRoot || "",
  }};
  renderProjectManagementModal(latestStatusData || {{}});
}}

function updateProjectIdentityDraft(field, value) {{
  if (!projectIdentityEditor) return;
  projectIdentityEditor[field] = value;
  clearProjectIdentityPreview();
}}

function cancelProjectIdentityEdit() {{
  clearProjectIdentityPreview();
  projectIdentityEditor = null;
  renderProjectManagementModal(latestStatusData || {{}});
}}

function previewProjectIdentity() {{
  const projectId = $("project-identity-id");
  const projectName = $("project-identity-name");
  const displayName = $("project-identity-display");
  const projectRoot = $("project-identity-root");
  const result = $("project-identity-result");
  projectIdentityPreviewId = "";
  fetch("/api/project-identity/preview", {{
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({{
      project_id: projectId ? projectId.value : "",
      new_project_name: projectName ? projectName.value : "",
      new_display_name: displayName ? displayName.value : "",
      new_project_root: projectRoot ? projectRoot.value : "",
    }}),
    cache: "no-store",
  }})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      if (result) {{
        const blockers = Array.isArray(data.blockers) ? data.blockers : [];
        const changes = Array.isArray(data.changes) ? data.changes : [];
        result.textContent = data.ok
          ? "预览完成，将修改：" + changes.map(function(item) {{ return item.target; }}).join("、")
          : "预览阻断：" + blockers.join("；");
      }}
      projectIdentityPreviewId = data.ok ? (data.preview_id || "") : "";
      const applyBtn = $("project-identity-apply");
      if (applyBtn) applyBtn.disabled = !projectIdentityPreviewId;
    }})
    .catch(function(e) {{ if (result) result.textContent = String(e); }});
}}

function applyProjectIdentity() {{
  const result = $("project-identity-result");
  if (!projectIdentityPreviewId) {{
    if (result) result.textContent = "请先生成有效预览。";
    return;
  }}
  dangerousPostAction("/api/project-identity/apply", {{ preview_id: projectIdentityPreviewId }})
    .then(function(data) {{
      if (result) result.textContent = data.message || (data.ok ? "迁移完成，请刷新页面。" : "迁移失败。");
      if (data.ok) {{
        clearProjectIdentityPreview();
        projectIdentityEditor = null;
        refresh();
      }} else {{
        clearProjectIdentityPreview();
      }}
    }})
    .catch(function(e) {{ if (result) result.textContent = String(e); }});
}}

function openProjectManagement() {{
  const modal = $("project-management-modal");
  if (modal) modal.classList.add("open");
}}

function closeProjectManagement(event) {{
  if (event && event.target && event.currentTarget && event.target !== event.currentTarget) return;
  const modal = $("project-management-modal");
  if (modal) modal.classList.remove("open");
}}

function openIssueModal(kind) {{
  const data = latestStatusData || {{}};
  const items = kind === "warnings" ? (data.warnings || []) : (data.blockers || []);
  const title = kind === "warnings" ? "警告详情" : "阻断问题详情";
  const titleEl = $("issue-detail-modal-title");
  const body = $("issue-detail-modal-body");
  if (titleEl) titleEl.textContent = title;
  if (body) {{
    if (Array.isArray(items) && items.length) {{
      body.innerHTML = items.map(function(item) {{ return `<div style="padding:8px 0;border-bottom:1px solid #30363d55;">${{esc(item)}}</div>`; }}).join("");
    }} else {{
      body.innerHTML = `<div class="empty-state">暂无${{kind === "warnings" ? "警告" : "阻断问题"}}</div>`;
    }}
  }}
  const modal = $("issue-detail-modal");
  if (modal) modal.classList.add("open");
}}

function closeIssueModal(event) {{
  if (event && event.target && event.currentTarget && event.target !== event.currentTarget) return;
  const modal = $("issue-detail-modal");
  if (modal) modal.classList.remove("open");
}}

function openTodoModal(todoId, content) {{
  const titleEl = $("todo-detail-modal-title");
  const body = $("todo-detail-modal-body");
  if (titleEl) titleEl.textContent = todoId ? "TODO 详情：" + todoId : "TODO 详情";
  if (body) {{
    body.innerHTML = `<div class="todo-detail-id">${{esc(todoId || "-")}}</div><div class="todo-detail-content">${{esc(content || "")}}</div>`;
  }}
  const modal = $("todo-detail-modal");
  if (modal) modal.classList.add("open");
}}

function closeTodoModal(event) {{
  if (event && event.target && event.currentTarget && event.target !== event.currentTarget) return;
  const modal = $("todo-detail-modal");
  if (modal) modal.classList.remove("open");
}}

let versionDetailModalData = null;

function versionDetailTitle(data, version) {{
  const ver = (data && data.version) || version || "";
  const name = data && data.version_name ? String(data.version_name).trim() : "";
  return name ? ver + ": " + name : ver;
}}

function renderVersionDetailModalBody(data, activeTab) {{
  activeTab = activeTab === "report" ? "report" : "prompt";
  const promptActive = activeTab === "prompt" ? " active" : "";
  const reportActive = activeTab === "report" ? " active" : "";
  let h = "";
  h += `<div class="version-detail-tabs">`;
  h += `<button type="button" class="version-detail-tab${{promptActive}}" onclick="showVersionDetailTab('prompt')">prompt</button>`;
  h += `<button type="button" class="version-detail-tab${{reportActive}}" onclick="showVersionDetailTab('report')">report</button>`;
  h += `</div>`;
  if (activeTab === "report") {{
    const report = data && data.report && typeof data.report === "object" ? data.report : {{}};
    if (report.available) {{
      h += `<div class="version-detail-path">报告地址：${{esc(report.report_file || "-")}}</div>`;
      h += `<pre class="version-detail-content">${{esc(report.content || "")}}</pre>`;
      if (report.truncated) {{
        h += `<div style="margin-top:8px;font-size:12px;color:#d29922;">提示：报告内容已截断。</div>`;
      }}
    }} else {{
      h += `<div class="version-detail-path">报告地址：-</div>`;
      h += `<div class="empty-state">${{esc(report.message || "该版本暂无执行器报告。")}}</div>`;
    }}
    return h;
  }}
  h += `<div class="version-detail-path">prompt 文件：${{esc(data.prompt_file || "-")}}</div>`;
  h += `<pre class="version-detail-content">${{esc(data.content || "")}}</pre>`;
  if (data.truncated) {{
    h += `<div style="margin-top:8px;font-size:12px;color:#d29922;">提示：内容已截断，仅显示前 ${{data.char_count}} 字符。</div>`;
  }}
  return h;
}}

function showVersionDetailTab(tab) {{
  const body = $("version-prompt-modal-body");
  if (!body || !versionDetailModalData) return;
  body.innerHTML = renderVersionDetailModalBody(versionDetailModalData, tab);
}}

function openVersionPromptModal(version) {{
  const titleEl = $("version-prompt-modal-title");
  const body = $("version-prompt-modal-body");
  versionDetailModalData = null;
  if (titleEl) titleEl.textContent = version;
  if (body) body.innerHTML = `<div class="empty-state">加载中…</div>`;
  const modal = $("version-prompt-modal");
  if (modal) modal.classList.add("open");

  fetch("/api/version-prompt?version=" + encodeURIComponent(version), {{ headers: readHeaders() }})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      if (!body) return;
      if (data.ok) {{
        versionDetailModalData = data;
        if (titleEl) titleEl.textContent = versionDetailTitle(data, version);
        body.innerHTML = renderVersionDetailModalBody(data, "prompt");
      }} else {{
        body.innerHTML = `<div style="color:#f85149;">错误：${{esc(data.message || "获取版本详情失败")}}</div>`;
      }}
    }})
    .catch(function(e) {{ if (body) body.innerHTML = `<div style="color:#f85149;">错误：${{esc(String(e))}}</div>`; }});
}}

function closeVersionPromptModal(event) {{
  if (event && event.target && event.currentTarget && event.target !== event.currentTarget) return;
  const modal = $("version-prompt-modal");
  if (modal) modal.classList.remove("open");
}}

function openDecisionModal(decisionId, title, decision, reason, relatedVersions, status) {{
  const titleEl = $("todo-detail-modal-title");
  const body = $("todo-detail-modal-body");
  if (titleEl) titleEl.textContent = decisionId ? "DECISION 详情：" + decisionId : "DECISION 详情";
  if (body) {{
    const versions = relatedVersions ? relatedVersions : "-";
    body.innerHTML = `<div class="todo-detail-id">${{esc(decisionId || "-")}} ｜ ${{esc(status || "-")}} ｜ 版本：${{esc(versions)}}</div><div class="todo-detail-content"><strong>${{esc(title || "")}}</strong>\n\n决策：${{esc(decision || "")}}\n\n原因：${{esc(reason || "")}}</div>`;
  }}
  const modal = $("todo-detail-modal");
  if (modal) modal.classList.add("open");
}}

function showRightTab(tabName) {{
  const card = $("layout-right") && $("layout-right").querySelector(".card");
  if (card) {{
    card.querySelectorAll(".tab-btn").forEach(function(b) {{ b.classList.remove("active"); }});
    const tabBtn = card.querySelector('[data-tab-button="' + tabName + '"]');
    if (tabBtn) tabBtn.classList.add("active");
    card.querySelectorAll(".tab-content").forEach(function(tc) {{ tc.style.display = "none"; }});
    const tabContent = card.querySelector('[data-tab="' + tabName + '"]');
    if (tabContent) tabContent.style.display = "block";
  }}
}}

function switchLeftTab(tabName, btn) {{
  const card = btn.closest(".card");
  card.querySelectorAll(".tab-btn").forEach(function(b) {{ b.classList.remove("active"); }});
  btn.classList.add("active");
  card.querySelectorAll('[data-left-tab]').forEach(function(tc) {{ tc.style.display = "none"; }});
  const content = card.querySelector('[data-left-tab="' + tabName + '"]');
  if (content) content.style.display = "block";
}}

function clampTodoPageSize(size) {{
  return Math.max(TODO_PAGE_SIZE_MIN, Math.min(TODO_PAGE_SIZE_MAX, size));
}}

function estimateTodoPageSize() {{
  const right = $("layout-right");
  if (!right) return adaptiveTodoPageSize;
  const tabContent = right.querySelector('[data-tab="todolist"]');
  if (!tabContent) return adaptiveTodoPageSize;
  const items = Array.from(tabContent.querySelectorAll(".todo-item"));
  if (!items.length) return adaptiveTodoPageSize;
  const pager = tabContent.querySelector(".todo-pager");
  const available = tabContent.clientHeight - (pager ? pager.offsetHeight : 0) - 8;
  if (available <= 0) return adaptiveTodoPageSize;
  const sample = items[0].offsetHeight || 1;
  if (sample <= 0) return adaptiveTodoPageSize;
  return clampTodoPageSize(Math.floor(available / sample));
}}

function syncAdaptiveTodoPageSize() {{
  if (adaptiveTodoPageSizeSyncing) return;
  const data = latestStatusData || {{}};
  const todo = data.todolist || {{}};
  const items = Array.isArray(todo.items) ? todo.items : [];
  if (!items.length) return;
  const nextPageSize = estimateTodoPageSize();
  if (nextPageSize === adaptiveTodoPageSize) return;
  adaptiveTodoPageSize = nextPageSize;
  const maxPage = Math.max(1, Math.ceil(items.length / adaptiveTodoPageSize));
  todoPage = Math.min(maxPage, Math.max(1, todoPage));
  adaptiveTodoPageSizeSyncing = true;
  renderRightColumn(data);
  showRightTab("todolist");
  adaptiveTodoPageSizeSyncing = false;
}}

function changeTodoPage(delta) {{
  const data = latestStatusData || {{}};
  const todo = data.todolist || {{}};
  const items = Array.isArray(todo.items) ? todo.items : [];
  const maxPage = Math.max(1, Math.ceil(items.length / adaptiveTodoPageSize));
  todoPage = Math.min(maxPage, Math.max(1, todoPage + delta));
  renderRightColumn(data);
  showRightTab("todolist");
}}

function changeDecisionPage(delta) {{
  const data = latestStatusData || {{}};
  const decisionResult = data.decisions || {{}};
  const decisions = Array.isArray(decisionResult.decisions) ? decisionResult.decisions : [];
  const maxPage = Math.max(1, Math.ceil(decisions.length / DECISION_PAGE_SIZE));
  decisionPage = Math.min(maxPage, Math.max(1, decisionPage + delta));
  renderRightColumn(data);
  showRightTab("decision");
}}

function renderProjectManagementModal(data) {{
  const body = $("project-management-modal-body");
  if (body) body.innerHTML = renderProjectManagement(data);
}}

function renderProjectManagement(data) {{
  const registry = data.project_registry || {{}};
  const projects = Array.isArray(registry.projects) ? registry.projects : [];
  const currentRoot = currentProjectRootForSwitcher(data || {{}});
  let h = "";
  h += `<div class="card"><div class="card-title">项目登记管理</div>`;
  h += `<div style="font-size:11px;color:#8b949e;margin-bottom:8px;">这里管理项目登记元数据。移出/清理只修改登记记录，不会删除磁盘文件；应用迁移会按预览修改 registry / plan / state / settings。当前项目会标注“当前”，/mnt/... 会标注为 Windows 挂载路径。</div>`;

  if (projects.length === 0) {{
    h += `<div class="empty-state">无登记项目</div>`;
  }} else {{
    for (const p of projects) {{
      const root = p.project_root || "";
      const projectId = p.project_id || "";
      const available = p.available === true;
      const isTemp = p.is_temp === true;
      const isCurrent = currentRoot && root === currentRoot;
      const isWindowsMount = typeof root === "string" && root.startsWith("/mnt/");
      const isEditing = !!projectIdentityEditor && projectIdentityEditor.project_id === projectId;
      h += `<div style="padding:6px 0;border-top:1px solid #21262d;font-size:12px;">`;
      h += `<div style="display:flex;justify-content:space-between;align-items:flex-start;">`;
      h += `<div style="flex:1;min-width:0;">`;
      h += `<div style="display:flex;gap:4px;align-items:center;flex-wrap:wrap;">`;
      const pLabel = (p.manifest && p.manifest.friendly_label) || p.display_name || p.project_name || root;
      h += `<span style="font-weight:500;">${{esc(pLabel)}}</span>`;
      h += `</div>`;
      h += `<div style="color:#8b949e;font-size:11px;word-break:break-all;margin-top:2px;">${{esc(root)}}</div>`;
      h += `<div style="margin-top:3px;display:flex;gap:4px;">`;
      if (isCurrent) h += `<span class="badge badge-info">当前</span>`;
      h += `<span class="badge ${{available ? "badge-ok" : "badge-err"}}">${{available ? "可用" : "不可用"}}</span>`;
      if (isWindowsMount) h += `<span class="badge badge-warn">Windows 挂载路径</span>`;
      if (isTemp) h += `<span class="badge badge-warn">临时</span>`;
      h += `</div>`;
      h += `</div>`;
      h += `<div style="display:flex;gap:6px;flex:0 0 auto;margin-left:8px;">`;
      h += `<button class="action-btn" title="编辑登记元数据，不修改磁盘文件。" style="width:auto;padding:3px 10px;font-size:11px;margin:0;" data-project-id="${{escAttr(projectId)}}" data-project-name="${{escAttr(p.project_name || "")}}" data-display-name="${{escAttr(p.display_name || p.project_name || "")}}" data-project-root="${{escAttr(root)}}" onclick="openProjectIdentityEditor(this)">编辑登记</button>`;
      h += `<button class="action-btn" title="仅移出登记记录，不删除磁盘文件。" style="width:auto;padding:3px 10px;font-size:11px;margin:0;flex:0 0 auto;" onclick="registryAction('project_registry_unregister',{{project_root:'${{escAttr(root)}}'}})">移出登记</button>`;
      h += `</div>`;
      h += `</div>`;
      if (isEditing) {{
        const editor = projectIdentityEditor || {{}};
        h += `<div class="card" style="margin:8px 0 2px 0;background:#0d1117;">`;
        h += `<div class="card-title">编辑项目登记：${{esc(pLabel)}}</div>`;
        h += `<div style="font-size:11px;color:#8b949e;margin-bottom:8px;word-break:break-all;">project_id=${{esc(projectId)}}</div>`;
        h += `<input id="project-identity-id" type="hidden" value="${{escAttr(projectId)}}">`;
        h += `<div style="display:grid;gap:8px;">`;
        h += `<label style="font-size:11px;color:#8b949e;">项目名称<input id="project-identity-name" value="${{escAttr(editor.project_name || "")}}" oninput="updateProjectIdentityDraft('project_name',this.value)" style="display:block;width:100%;box-sizing:border-box;margin-top:3px;"></label>`;
        h += `<label style="font-size:11px;color:#8b949e;">显示名称<input id="project-identity-display" value="${{escAttr(editor.display_name || "")}}" oninput="updateProjectIdentityDraft('display_name',this.value)" style="display:block;width:100%;box-sizing:border-box;margin-top:3px;"></label>`;
        h += `<label style="font-size:11px;color:#8b949e;">项目路径<input id="project-identity-root" value="${{escAttr(editor.project_root || "")}}" oninput="updateProjectIdentityDraft('project_root',this.value)" style="display:block;width:100%;box-sizing:border-box;margin-top:3px;"></label>`;
        h += `<div style="display:flex;gap:6px;flex-wrap:wrap;"><button class="action-btn" style="width:auto;" onclick="previewProjectIdentity()">预览迁移</button><button id="project-identity-apply" class="action-btn" style="width:auto;" onclick="applyProjectIdentity()" disabled>应用迁移</button><button class="action-btn" style="width:auto;" onclick="cancelProjectIdentityEdit()">取消</button></div>`;
        h += `<div id="project-identity-result" style="font-size:11px;color:#8b949e;white-space:pre-wrap;"></div>`;
        h += `<div style="font-size:11px;color:#8b949e;">应用成功后请刷新页面；项目路径变化时请重启或重新选择项目。</div>`;
        h += `</div></div>`;
      }}
      h += `</div>`;
    }}
  }}

  h += `<div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;">`;
  h += `<button class="action-btn" style="width:auto;padding:4px 12px;font-size:12px;" onclick="registryAction('project_registry_prune_unavailable',{{}})">清理不可用登记</button>`;
  h += `<button class="action-btn" style="width:auto;padding:4px 12px;font-size:12px;" onclick="registryAction('project_registry_prune_temporary',{{}})">清理临时登记</button>`;
  h += `</div>`;
  h += `</div>`;
  return h;
}}

function renderRightColumn(data) {{
  let h = "";

  // Tabbed card: TODOLIST + DECISION + MEMORY
  h += `<div class="card action-tab-card">`;
  h += `<div class="tab-bar">`;
  h += `<button class="tab-btn active" data-tab-button="todolist" onclick="switchActionTab('todolist', this)"><span class="tab-icon">☰</span>TODOLIST</button>`;
  h += `<button class="tab-btn" data-tab-button="decision" onclick="switchActionTab('decision', this)"><span class="tab-icon">◆</span>DECISION</button>`;
  h += `<button class="tab-btn" data-tab-button="memory" onclick="switchActionTab('memory', this)"><span class="tab-icon">◎</span>MEMORY</button>`;
  h += `</div>`;

  // TODOLIST tab
  h += `<div class="tab-content" data-tab="todolist">`;
  const todo = data.todolist || {{}};
  if (todo.ok === false) {{
    h += `<div class="empty-state">${{esc(todo.error_code || "读取失败")}}</div>`;
  }} else {{
    const items = Array.isArray(todo.items) ? todo.items : [];
    if (!items.length) {{
      h += `<div class="empty-state">暂无备忘录</div>`;
    }} else {{
      const todoPageSize = adaptiveTodoPageSize;
      const maxPage = Math.max(1, Math.ceil(items.length / todoPageSize));
      if (todoPage > maxPage) todoPage = maxPage;
      if (todoPage < 1) todoPage = 1;
      const start = (todoPage - 1) * todoPageSize;
      const pageItems = items.slice(start, start + todoPageSize);
      for (const item of pageItems) {{
        const todoId = item && item.id != null ? String(item.id) : "";
        const todoContent = item && item.content != null ? String(item.content) : "";
        h += `<div class="todo-item">`;
        h += `<div class="todo-id-row">`;
        h += `<div class="key">ID ${{esc(todoId)}}</div>`;
        h += `<button type="button" class="todo-copy-btn" data-copy-todo-id="${{escAttr(todoId)}}">复制</button>`;
        h += `</div>`;
        h += `<div class="todo-content todo-content-preview" role="button" tabindex="0" title="点击查看完整内容" data-todo-id="${{escAttr(todoId)}}" data-todo-content="${{escAttr(todoContent)}}">${{esc(todoContent)}}</div>`;
        h += `</div>`;
      }}
      h += `<div class="todo-pager">`;
      h += `<button type="button" class="todo-page-btn" onclick="changeTodoPage(-1)" ${{todoPage <= 1 ? "disabled" : ""}}>上一页</button>`;
      h += `<span>${{start + 1}}-${{Math.min(start + pageItems.length, items.length)}} / ${{items.length}} ｜ 第 ${{todoPage}} / ${{maxPage}} 页</span>`;
      h += `<button type="button" class="todo-page-btn" onclick="changeTodoPage(1)" ${{todoPage >= maxPage ? "disabled" : ""}}>下一页</button>`;
      h += `</div>`;
    }}
  }}
  h += `</div>`;

  // DECISION tab
  h += `<div class="tab-content" data-tab="decision" style="display:none;">`;
  const decisionResult = data.decisions || {{}};
  if (decisionResult.ok === false) {{
    h += `<div class="empty-state">${{esc(decisionResult.error_code || "读取失败")}}</div>`;
  }} else {{
    const decisions = Array.isArray(decisionResult.decisions) ? decisionResult.decisions : [];
    if (!decisions.length) {{
      h += `<div class="empty-state">暂无决策记录</div>`;
    }} else {{
      const maxDecisionPage = Math.max(1, Math.ceil(decisions.length / DECISION_PAGE_SIZE));
      if (decisionPage > maxDecisionPage) decisionPage = maxDecisionPage;
      if (decisionPage < 1) decisionPage = 1;
      const decisionStart = (decisionPage - 1) * DECISION_PAGE_SIZE;
      const pageDecisions = decisions.slice(decisionStart, decisionStart + DECISION_PAGE_SIZE);
      for (const item of pageDecisions) {{
        const decisionId = item && item.id != null ? String(item.id) : "";
        const decisionTitle = item && item.title != null ? String(item.title) : "";
        const decisionText = item && item.decision != null ? String(item.decision) : "";
        const reasonText = item && item.reason != null ? String(item.reason) : "";
        const statusText = item && item.status != null ? String(item.status) : "";
        const relatedVersions = Array.isArray(item && item.related_versions) ? item.related_versions.join(", ") : "";
        const previewText = [decisionTitle, decisionText, reasonText].filter(Boolean).join("\\n");
        h += `<div class="todo-item">`;
        h += `<div class="todo-id-row">`;
        h += `<div class="key">ID ${{esc(decisionId)}} ｜ ${{esc(statusText || "-")}}</div>`;
        h += `</div>`;
        h += `<div class="todo-content todo-content-preview" role="button" tabindex="0" title="点击查看完整内容" data-decision-id="${{escAttr(decisionId)}}" data-decision-title="${{escAttr(decisionTitle)}}" data-decision-text="${{escAttr(decisionText)}}" data-decision-reason="${{escAttr(reasonText)}}" data-decision-related-versions="${{escAttr(relatedVersions)}}" data-decision-status="${{escAttr(statusText)}}">${{esc(previewText)}}</div>`;
        h += `</div>`;
      }}
      h += `<div class="todo-pager">`;
      h += `<button type="button" class="todo-page-btn" onclick="changeDecisionPage(-1)" ${{decisionPage <= 1 ? "disabled" : ""}}>上一页</button>`;
      h += `<span>${{decisionStart + 1}}-${{Math.min(decisionStart + pageDecisions.length, decisions.length)}} / ${{decisions.length}} ｜ 第 ${{decisionPage}} / ${{maxDecisionPage}} 页</span>`;
      h += `<button type="button" class="todo-page-btn" onclick="changeDecisionPage(1)" ${{decisionPage >= maxDecisionPage ? "disabled" : ""}}>下一页</button>`;
      h += `</div>`;
    }}
  }}
  h += `</div>`;

  // MEMORY tab
  h += `<div class="tab-content" data-tab="memory" style="display:none;">`;
  const memoryResult = data.memory || {{}};
  if (memoryResult.ok === false) {{
    h += `<div class="empty-state">${{esc(memoryResult.error_code || "读取失败")}}</div>`;
  }} else {{
    const memoryContent = memoryResult.content != null ? String(memoryResult.content) : "";
    if (!memoryContent.trim()) {{
      h += `<div class="empty-state">暂无记忆</div>`;
    }} else {{
      h += `<div class="todo-item">`;
      h += `<div class="key">${{esc(memoryResult.path || "memory.md")}}</div>`;
      h += `<div class="todo-content" style="white-space:pre-wrap;max-height:360px;overflow:auto;">${{esc(memoryContent)}}</div>`;
      h += `</div>`;
    }}
  }}
  h += `</div>`;
  h += `</div>`;


  $("layout-right").innerHTML = h;
  syncAdaptiveTodoPageSize();

  $("layout-right").querySelectorAll("[data-copy-todo-id]").forEach(function(btn) {{
    btn.addEventListener("click", function() {{
      const todoId = this.getAttribute("data-copy-todo-id") || "";
      copyTodoId(todoId, this);
    }});
  }});
  $("layout-right").querySelectorAll("[data-todo-content]").forEach(function(el) {{
    const open = function() {{
      openTodoModal(el.getAttribute("data-todo-id") || "", el.getAttribute("data-todo-content") || "");
    }};
    el.addEventListener("click", open);
    el.addEventListener("keydown", function(evt) {{
      if (evt.key === "Enter" || evt.key === " ") {{
        evt.preventDefault();
        open();
      }}
    }});
  }});
  $("layout-right").querySelectorAll("[data-decision-id]").forEach(function(el) {{
    const open = function() {{
      openDecisionModal(
        el.getAttribute("data-decision-id") || "",
        el.getAttribute("data-decision-title") || "",
        el.getAttribute("data-decision-text") || "",
        el.getAttribute("data-decision-reason") || "",
        el.getAttribute("data-decision-related-versions") || "",
        el.getAttribute("data-decision-status") || ""
      );
    }};
    el.addEventListener("click", open);
    el.addEventListener("keydown", function(evt) {{
      if (evt.key === "Enter" || evt.key === " ") {{
        evt.preventDefault();
        open();
      }}
    }});
  }});
}}

function switchActionTab(tabName, btn) {{
  const card = btn.closest(".card");
  card.querySelectorAll(".tab-btn").forEach(function(b) {{ b.classList.remove("active"); }});
  btn.classList.add("active");
  card.querySelectorAll(".tab-content").forEach(function(tc) {{ tc.style.display = "none"; }});
  var content = card.querySelector('[data-tab="' + tabName + '"]');
  if (content) content.style.display = "block";
  if (tabName === "todolist") syncAdaptiveTodoPageSize();
}}

window.addEventListener("resize", function() {{
  adaptiveTodoPageSize = TODO_PAGE_SIZE_DEFAULT;
  syncAdaptiveTodoPageSize();
}});

refresh();
</script>
</body>
</html>"""
    return html
