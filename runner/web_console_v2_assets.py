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
.layout-center .service-capability-card { flex: 0 0 auto; margin-bottom: 0; border-left: 4px solid #58a6ff; }
.layout-center .service-capability-card.blocked { border-left-color: #f85149; }
.layout-center .service-capability-card.warn { border-left-color: #d29922; }
.layout-center .service-profile-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.layout-center .service-profile-pill { display: inline-flex; align-items: center; gap: 4px; padding: 2px 7px; border: 1px solid #30363d; border-radius: 999px; color: #c9d1d9; font-size: 11px; background: #0d1117; }
.layout-center .service-copy-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.layout-center .service-copy-btn { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 4px 9px; border-radius: 6px; font-size: 11px; cursor: pointer; }
.layout-center .service-copy-btn:hover { background: #30363d; }
.operator-inbox-list { display: grid; gap: 7px; margin-top: 8px; }
.operator-inbox-item { border: 1px solid #30363d; border-radius: 6px; padding: 8px; background: #0d1117; }
.operator-inbox-item.target-highlight { border-color: #58a6ff; box-shadow: 0 0 0 1px #58a6ff44; }
.operator-inbox-head { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
.operator-inbox-title { font-size: 12px; color: #f0f6fc; font-weight: 600; word-break: break-word; }
.operator-inbox-summary { color: #8b949e; font-size: 11px; line-height: 1.5; margin-bottom: 8px; }
.operator-inbox-meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
.operator-inbox-meta span { border: 1px solid #30363d; border-radius: 999px; padding: 1px 6px; color: #8b949e; font-size: 10px; }
.operator-inbox-why { color: #8b949e; font-size: 11px; margin-top: 5px; line-height: 1.4; }
.operator-inbox-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 7px; }
.operator-inbox-btn { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 3px 9px; border-radius: 6px; font-size: 11px; cursor: pointer; }
.operator-inbox-btn:hover:not(:disabled) { background: #30363d; }
.operator-inbox-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.operator-inbox-action-status { color: #8b949e; font-size: 11px; margin-top: 6px; min-height: 16px; }
.operator-inbox-action-status.running { color: #d29922; }
.operator-inbox-action-status.completed { color: #3fb950; }
.operator-inbox-action-status.failed { color: #f85149; }
.operator-inbox-action-meta { color: #8b949e; font-size: 10px; margin-top: 2px; }
.operator-inbox-run-impact { border-top: 1px solid #30363d55; margin-top: 8px; padding-top: 8px; color: #8b949e; font-size: 11px; line-height: 1.45; }
.operator-inbox-run-impact.running { color: #d29922; }
.operator-inbox-run-impact.completed { color: #3fb950; }
.operator-inbox-run-impact.failed { color: #f85149; }
.operator-inbox-run-impact .impact-meta { color: #8b949e; font-size: 10px; margin-top: 2px; }
.operator-inbox-run-impact .impact-actions { margin-top: 6px; }
.operator-inbox-run-trail { border-top: 1px solid #30363d55; margin: 8px 0 10px; padding-top: 8px; }
.operator-inbox-run-trail-title { color: #8b949e; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px; }
.operator-inbox-run-trail-list { display: grid; gap: 5px; }
.operator-inbox-run-trail-item { color: #8b949e; font-size: 11px; line-height: 1.4; }
.operator-inbox-run-trail-item.running { color: #d29922; }
.operator-inbox-run-trail-item.completed { color: #3fb950; }
.operator-inbox-run-trail-item.failed { color: #f85149; }
.modal-sync-status { color: #8b949e; font-size: 11px; line-height: 1.4; margin-bottom: 10px; min-height: 16px; }
.registry-action-status { color: #8b949e; font-size: 11px; line-height: 1.4; margin: 8px 0 10px; min-height: 16px; }
.registry-action-status.running { color: #d29922; }
.registry-action-status.completed { color: #3fb950; }
.registry-action-status.failed { color: #f85149; }
.registry-action-trail { border-top: 1px solid #30363d55; margin: 8px 0 10px; padding-top: 8px; }
.registry-action-trail-title { color: #8b949e; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px; }
.registry-action-trail-list { display: grid; gap: 5px; }
.registry-action-trail-item { color: #8b949e; font-size: 11px; line-height: 1.4; }
.registry-action-trail-item.running { color: #d29922; }
.registry-action-trail-item.completed { color: #3fb950; }
.registry-action-trail-item.failed { color: #f85149; }
.local-trail-boundary { color: #8b949e; font-size: 10px; line-height: 1.4; margin-bottom: 6px; }
.local-trail-clear { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 2px 8px; border-radius: 999px; font-size: 10px; cursor: pointer; margin-bottom: 6px; }
.local-trail-clear:hover:not(:disabled) { background: #30363d; }
.local-trail-clear:disabled { opacity: 0.45; cursor: not-allowed; }
.local-trail-feedback { color: #3fb950; font-size: 10px; line-height: 1.4; margin-bottom: 6px; min-height: 14px; }
.product-followup-queue { border-top: 1px solid #30363d55; margin-top: 8px; padding-top: 8px; display: grid; gap: 6px; }
.product-followup-title { color: #8b949e; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
.product-followup-item { display: grid; gap: 3px; padding: 6px 0; border-top: 1px solid #21262d; }
.product-followup-item:first-of-type { border-top: none; padding-top: 0; }
.product-followup-head { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.product-followup-label { color: #c9d1d9; font-size: 12px; font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.product-followup-meta { color: #8b949e; font-size: 10px; line-height: 1.4; word-break: break-word; }
.product-followup-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.layout-center .service-boundary { color: #8b949e; font-size: 11px; line-height: 1.5; border-top: 1px solid #30363d; margin-top: 8px; padding-top: 8px; }

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
#loading[aria-hidden="true"] { display: none; }
#error { display: none; background: #da363322; border: 1px solid #da363344; border-radius: 8px; padding: 16px; margin: 12px 0; }
.toolbar { display: flex; gap: 8px; align-items: flex-start; margin-bottom: 16px; }
.toolbar button { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 6px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; margin-top: 2px; }
.toolbar button:hover { background: #30363d; }
.project-switch { margin-left: auto; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.project-switch-label { color: #8b949e; font-size: 12px; }
.refresh-status { flex-basis: 100%; text-align: right; color: #8b949e; font-size: 11px; min-height: 16px; }
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
.tab-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 18px; height: 16px; margin-left: 6px; padding: 0 5px; border-radius: 999px; border: 1px solid #30363d; color: #8b949e; background: #0d1117; font-size: 10px; line-height: 1; }
.tab-badge.info { color: #58a6ff; border-color: #1f6feb88; background: #1f6feb22; }
.tab-badge.warn { color: #d29922; border-color: #d2992288; background: #d2992222; }
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
      <select id="project-select" aria-label="当前项目" aria-busy="false" disabled>
        <option>加载中…</option>
      </select>
      <button id="project-manage-btn" onclick="openProjectManagement()">项目管理</button>
      <button id="refresh-btn" type="button" aria-busy="false" aria-disabled="false" onclick="refresh()">刷新</button>
      <div id="refresh-status" class="refresh-status" role="status" aria-live="polite">尚未刷新 ｜ 后台轮询未启动</div>
    </div>
  </div>
  <div id="loading" role="status" aria-live="polite" aria-busy="false" aria-hidden="true">加载中…</div>
  <div id="error" role="alert" aria-live="assertive" aria-hidden="true"></div>
  <div id="project-management-modal" class="modal-backdrop" onclick="closeProjectManagement(event)">
    <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="project-management-modal-title" tabindex="-1" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div id="project-management-modal-title" class="modal-title">项目登记管理</div>
        <button type="button" class="modal-close" aria-label="关闭项目登记管理" onclick="closeProjectManagement()">关闭</button>
      </div>
      <div id="project-management-modal-body" class="modal-body"></div>
    </div>
  </div>
  <div id="issue-detail-modal" class="modal-backdrop" onclick="closeIssueModal(event)">
    <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="issue-detail-modal-title" tabindex="-1" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div id="issue-detail-modal-title" class="modal-title">问题详情</div>
        <button type="button" class="modal-close" aria-label="关闭问题详情" onclick="closeIssueModal()">关闭</button>
      </div>
      <div id="issue-detail-modal-body" class="modal-body"></div>
    </div>
  </div>
  <div id="todo-detail-modal" class="modal-backdrop" onclick="closeTodoModal(event)">
    <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="todo-detail-modal-title" tabindex="-1" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div id="todo-detail-modal-title" class="modal-title">TODO 详情</div>
        <button type="button" class="modal-close" aria-label="关闭 TODO 详情" onclick="closeTodoModal()">关闭</button>
      </div>
      <div id="todo-detail-modal-body" class="modal-body"></div>
    </div>
  </div>
  <div id="version-prompt-modal" class="modal-backdrop" onclick="closeVersionPromptModal(event)">
    <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="version-prompt-modal-title" tabindex="-1" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div id="version-prompt-modal-title" class="modal-title">Prompt</div>
        <button type="button" class="modal-close" aria-label="关闭 Prompt" onclick="closeVersionPromptModal()">关闭</button>
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
const REGISTRY_ACTION_META = {{
  project_registry_unregister: {{
    label: "移出项目登记",
    description: "仅移出登记记录，不删除磁盘文件。需要危险操作确认。",
    target_param: "project_root",
  }},
  project_registry_prune_unavailable: {{
    label: "清理不可用项目登记",
    description: "移出当前不可用的登记记录，不删除磁盘文件。需要危险操作确认。",
  }},
  project_registry_prune_temporary: {{
    label: "清理临时项目登记",
    description: "移出临时登记记录，不删除磁盘文件。需要危险操作确认。",
  }},
}};
function registryActionMeta(actionName, params) {{
  params = params || {{}};
  const meta = REGISTRY_ACTION_META[actionName] || {{}};
  const targetParam = meta.target_param || "";
  const target = targetParam && params[targetParam] ? String(params[targetParam]) : "";
  return Object.assign({{}}, meta, {{
    action: actionName,
    target: target,
  }});
}}
function registryActionButtonLabel(actionName, params) {{
  const meta = registryActionMeta(actionName, params);
  const target = meta.target ? " 目标：" + meta.target : "";
  return (meta.label || "项目管理操作") + "：" + (meta.description || "项目管理操作需要确认。") + target;
}}
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
let refreshInFlight = false;
let projectSwitchInFlight = false;
let lastStatusRefreshText = "尚未刷新";
let backgroundPollStatusText = "后台轮询未启动";
let pollCount = 0;
const POLL_MAX = 600;
let liveRunActive = false;
let pollExhausted = false;
let latestStatusData = null;
let latestStatusSignature = "";
let todoPage = 1;
let decisionPage = 1;
const LEFT_TAB_DEFAULT = "overview";
const LEFT_TAB_NAMES = ["overview", "versionplan"];
let activeLeftTab = LEFT_TAB_DEFAULT;
const RIGHT_TAB_DEFAULT = "todolist";
const RIGHT_TAB_NAMES = ["todolist", "operator-inbox", "decision", "memory"];
let activeRightTab = RIGHT_TAB_DEFAULT;
let operatorInboxRunFeedback = null;
let operatorInboxRunTrail = [];
let operatorInboxRunTrailFeedback = "";
const OPERATOR_INBOX_RUN_TRAIL_LIMIT = 5;
const LOCAL_TRAIL_BOUNDARY_TEXT = "仅本会话显示；只保存操作摘要，不保存 payload 或 arguments。";
const TODO_PAGE_SIZE_DEFAULT = 8;
const TODO_PAGE_SIZE_MIN = 3;
const TODO_PAGE_SIZE_MAX = 20;
let adaptiveTodoPageSize = TODO_PAGE_SIZE_DEFAULT;
let adaptiveTodoPageSizeSyncing = false;
const DECISION_PAGE_SIZE = 8;
let activeModalId = "";
let modalReturnFocus = null;
const MODAL_FOCUS_SELECTOR = "a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])";

function modalFocusableElements(modal) {{
  if (!modal) return [];
  return Array.from(modal.querySelectorAll(MODAL_FOCUS_SELECTOR)).filter(function(el) {{
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }});
}}

function focusModal(modal) {{
  if (!modal) return;
  const focusable = modalFocusableElements(modal);
  const closeButton = focusable.find(function(el) {{ return el.classList && el.classList.contains("modal-close"); }});
  const panel = modal.querySelector(".modal-panel");
  const target = closeButton || focusable[0] || panel || modal;
  if (target && typeof target.focus === "function") target.focus();
}}

function trapModalFocus(event) {{
  if (event.key !== "Tab" || !activeModalId) return;
  const modal = $(activeModalId);
  if (!modal || !modal.classList.contains("open")) return;
  const focusable = modalFocusableElements(modal);
  if (!focusable.length) {{
    event.preventDefault();
    focusModal(modal);
    return;
  }}
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const current = document.activeElement;
  if (event.shiftKey && current === first) {{
    event.preventDefault();
    last.focus();
  }} else if (!event.shiftKey && current === last) {{
    event.preventDefault();
    first.focus();
  }} else if (!modal.contains(current)) {{
    event.preventDefault();
    first.focus();
  }}
}}

function openModal(modalId) {{
  const modal = $(modalId);
  if (!modal) return;
  const active = document.activeElement;
  modalReturnFocus = active && typeof active.focus === "function" ? active : null;
  activeModalId = modalId;
  modal.classList.add("open");
  window.setTimeout(function() {{ focusModal(modal); }}, 0);
}}

function closeModal(modalId, event) {{
  if (event && event.target && event.currentTarget && event.target !== event.currentTarget) return;
  const modal = $(modalId);
  if (modal) modal.classList.remove("open");
  if (activeModalId === modalId) activeModalId = "";
  const returnFocus = modalReturnFocus;
  modalReturnFocus = null;
  if (returnFocus && typeof returnFocus.focus === "function" && document.contains(returnFocus)) {{
    returnFocus.focus();
  }}
}}

function closeActiveModal() {{
  if (!activeModalId) return;
  closeModal(activeModalId);
}}

document.addEventListener("keydown", function(event) {{
  if (event.key === "Escape" && activeModalId) {{
    event.preventDefault();
    closeActiveModal();
    return;
  }}
  trapModalFocus(event);
}});

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
  if (refreshInFlight) return;
  refreshInFlight = true;
  setRefreshButtonBusy(true);
  setGlobalLoading(true, "正在刷新状态...");
  clearGlobalError();
  setRefreshStatus(null, "正在手动刷新...");
  $("content").style.display = "none";
  try {{
    const data = await fetchStatus();
    setRefreshStatus("手动", "后台轮询启动中");
    render(data);
    startLiveRunPolling(data);
    startBackgroundStatusPolling();
  }} catch (e) {{
    showError(String(e));
  }} finally {{
    setGlobalLoading(false);
    setRefreshButtonBusy(false);
    refreshInFlight = false;
  }}
}}

function setRefreshButtonBusy(isBusy) {{
  const btn = $("refresh-btn");
  if (!btn) return;
  btn.disabled = isBusy;
  btn.textContent = isBusy ? "刷新中..." : "刷新";
  btn.setAttribute("aria-busy", isBusy ? "true" : "false");
  btn.setAttribute("aria-disabled", isBusy ? "true" : "false");
}}

function refreshTimestamp() {{
  return new Date().toLocaleTimeString([], {{ hour: "2-digit", minute: "2-digit", second: "2-digit" }});
}}

function renderRefreshStatus() {{
  const el = $("refresh-status");
  if (!el) return;
  el.textContent = lastStatusRefreshText + " ｜ " + backgroundPollStatusText;
}}

function projectManagementSyncStatusText() {{
  return "项目登记数据：" + lastStatusRefreshText + " ｜ " + backgroundPollStatusText;
}}

function setRefreshStatus(source, pollStatus) {{
  if (source) {{
    lastStatusRefreshText = "最后刷新 " + refreshTimestamp() + "（" + source + "）";
  }}
  if (pollStatus) backgroundPollStatusText = pollStatus;
  renderRefreshStatus();
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
      setRefreshStatus(null, "后台轮询检查中...");
      const newData = await fetchStatus();
      const newSignature = statusSignature(newData);
      setRefreshStatus("后台", newSignature !== latestStatusSignature ? "后台轮询已更新页面" : "后台轮询正常，无变化");
      if (newSignature !== latestStatusSignature) {{
        render(newData);
        startLiveRunPolling(newData);
      }}
    }} catch (e) {{
      // Background status polling is best-effort: keep the current page visible
      // and try again later instead of surfacing noisy transient errors.
      setRefreshStatus(null, "后台轮询暂时失败，将重试");
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
  setRefreshStatus(null, "后台轮询每 5 秒");
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
  if (!el) return;
  el.textContent = "错误：" + msg;
  el.style.display = "block";
  el.setAttribute("aria-hidden", "false");
}}

function clearGlobalError() {{
  const el = $("error");
  if (!el) return;
  el.textContent = "";
  el.style.display = "none";
  el.setAttribute("aria-hidden", "true");
}}

function setGlobalLoading(isLoading, message) {{
  const el = $("loading");
  if (!el) return;
  if (message) el.textContent = message;
  el.style.display = isLoading ? "block" : "none";
  el.setAttribute("aria-busy", isLoading ? "true" : "false");
  el.setAttribute("aria-hidden", isLoading ? "false" : "true");
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

async function copyTextToClipboard(text, button) {{
  try {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      await navigator.clipboard.writeText(text);
    }} else {{
      const textarea = document.createElement("textarea");
      textarea.value = text;
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
      button.textContent = "已复制";
      button.disabled = true;
      setTimeout(function() {{
        button.textContent = old;
        button.disabled = false;
      }}, 1200);
    }}
  }} catch (e) {{
    if (button) {{
      const old = button.textContent;
      button.textContent = "复制失败";
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
  setGlobalLoading(true, "正在执行操作...");
  clearGlobalError();
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
    return data;
  }} catch (e) {{
    showError(String(e));
    return {{ ok: false, error_code: "ACTION_FAILED", message: String(e) }};
  }} finally {{
    setGlobalLoading(false);
  }}
}}

async function switchProject(projectRoot) {{
  if (!projectRoot) return;
  if (projectSwitchInFlight) return;
  projectSwitchInFlight = true;
  setProjectSwitchBusy(true);
  setGlobalLoading(true, "正在切换项目...");
  clearGlobalError();
  setRefreshStatus(null, "正在切换项目...");
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
    setGlobalLoading(false);
    setProjectSwitchBusy(false);
    projectSwitchInFlight = false;
  }}
}}

function setProjectSwitchBusy(isBusy) {{
  const select = $("project-select");
  if (!select) return;
  select.disabled = isBusy || select.options.length < 2;
  select.setAttribute("aria-busy", isBusy ? "true" : "false");
  select.setAttribute("aria-disabled", select.disabled ? "true" : "false");
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
  clearStaleOperatorInboxFeedback(latestStatusData);
  renderRefreshStatus();
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
    select.setAttribute("aria-disabled", "true");
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
  select.disabled = projectSwitchInFlight || projects.length < 2;
  select.setAttribute("aria-busy", projectSwitchInFlight ? "true" : "false");
  select.setAttribute("aria-disabled", select.disabled ? "true" : "false");
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
  activeLeftTab = normalizeLeftTab(activeLeftTab);
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
  h += `<div class="tab-bar" role="tablist" aria-label="Project workspace">`;
  h += `<button type="button" id="left-tab-overview" role="tab" aria-selected="${{leftTabAriaSelected("overview")}}" aria-controls="left-panel-overview" aria-label="项目总览" class="tab-btn${{leftTabActiveClass("overview")}}" data-left-tab-button="overview" onclick="switchLeftTab('overview', this)" onkeydown="handleLeftTabKeydown(event, 'overview')"><span class="tab-icon">◉</span>项目总览</button>`;
  h += `<button type="button" id="left-tab-versionplan" role="tab" aria-selected="${{leftTabAriaSelected("versionplan")}}" aria-controls="left-panel-versionplan" aria-label="版本计划" class="tab-btn${{leftTabActiveClass("versionplan")}}" data-left-tab-button="versionplan" onclick="switchLeftTab('versionplan', this)" onkeydown="handleLeftTabKeydown(event, 'versionplan')"><span class="tab-icon">☰</span>版本计划</button>`;
  h += `</div>`;

  h += `<div id="left-panel-overview" class="tab-content" role="tabpanel" aria-labelledby="left-tab-overview" aria-hidden="${{leftTabAriaHidden("overview")}}" tabindex="0" data-left-tab="overview"${{leftTabDisplayStyle("overview")}}>`;
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

  h += `<div id="left-panel-versionplan" class="tab-content" role="tabpanel" aria-labelledby="left-tab-versionplan" aria-hidden="${{leftTabAriaHidden("versionplan")}}" tabindex="0" data-left-tab="versionplan"${{leftTabDisplayStyle("versionplan")}}>`;
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

function renderProductFollowupQueue(completion) {{
  completion = completion || {{}};
  const queue = completion.followup_queue && typeof completion.followup_queue === "object" ? completion.followup_queue : {{}};
  const items = Array.isArray(queue.items) ? queue.items : [];
  let h = `<div class="product-followup-queue" aria-label="Product closeout follow-up queue">`;
  h += `<div class="product-followup-title">Product follow-up queue</div>`;
  if (!items.length) {{
    h += `<div class="product-followup-meta">暂无 closeout follow-up 项。</div>`;
  }} else {{
    for (const item of items.slice(0, 3)) {{
      const primary = item.primary_action && typeof item.primary_action === "object" ? item.primary_action : {{}};
      const label = item.label || primary.label || item.item_id || "Follow-up";
      const status = item.status || queue.status || "-";
      const scope = item.required_scope || primary.required_scope || "-";
      const gate = item.gate_level || primary.gate_level || "-";
      const tool = item.primary_tool || primary.tool || "";
      const position = item.position === 0 || item.position ? String(item.position) : "-";
      const followupItemId = item.item_id ? String(item.item_id) : "";
      h += `<div class="product-followup-item">`;
      h += `<div class="product-followup-head"><div class="product-followup-label">${{esc(position)}}. ${{esc(label)}}</div><span class="badge ${{scope === "mcp:read" ? "badge-ok" : "badge-warn"}}">${{esc(scope)}}</span></div>`;
      h += `<div class="product-followup-meta">${{esc(status)}} ｜ ${{esc(gate)}} ｜ ${{esc(tool || "manual")}}</div>`;
      h += `<div class="product-followup-actions">`;
      h += `<button type="button" class="operator-inbox-btn" data-open-product-followup="${{escAttr(followupItemId)}}" aria-label="${{escAttr("在 INBOX 中查看：" + label)}}" title="${{escAttr("在 INBOX 中查看：" + label)}}">Open INBOX</button>`;
      if (tool) {{
        const payload = JSON.stringify({{ tool: tool, arguments: primary.arguments || {{}} }}, null, 2);
        const copyLabel = "复制 Product follow-up 调用：" + label;
        h += `<button type="button" class="operator-inbox-btn operator-inbox-copy" data-copy-operator-inbox="${{escAttr(payload)}}" aria-label="${{escAttr(copyLabel)}}" title="${{escAttr(copyLabel)}}">Copy follow-up</button>`;
      }}
      h += `</div>`;
      h += `</div>`;
    }}
    if (items.length > 3) {{
      h += `<div class="product-followup-meta">还有 ${{items.length - 3}} 个 follow-up 项，请在右侧 INBOX 查看。</div>`;
    }}
  }}
  h += `<div class="product-followup-meta">队列只读；Copy 不执行操作，Run 入口仍受 INBOX scope gate 控制。</div>`;
  h += `</div>`;
  return h;
}}

function openProductFollowupInInbox(itemId) {{
  itemId = String(itemId || "");
  if (!$("layout-right") || !$("layout-right").querySelector('[data-tab="operator-inbox"]')) {{
    if (latestStatusData) renderRightColumn(latestStatusData);
  }}
  showRightTab("operator-inbox");
  const root = $("layout-right");
  if (!root) return;
  root.querySelectorAll(".operator-inbox-item.target-highlight").forEach(function(el) {{
    el.classList.remove("target-highlight");
  }});
  let target = null;
  if (itemId) {{
    root.querySelectorAll("[data-operator-inbox-followup-item-id]").forEach(function(el) {{
      if (!target && el.getAttribute("data-operator-inbox-followup-item-id") === itemId) target = el;
    }});
  }}
  if (!target) target = root.querySelector('[data-tab="operator-inbox"]');
  if (target) {{
    if (target.classList && target.classList.contains("operator-inbox-item")) target.classList.add("target-highlight");
    target.scrollIntoView({{ block: "nearest", behavior: "smooth" }});
    if (typeof target.focus === "function") target.focus({{ preventScroll: true }});
  }}
}}

function openPendingRefreshInInbox() {{
  if (!$("layout-right") || !$("layout-right").querySelector('[data-tab="operator-inbox"]')) {{
    if (latestStatusData) renderRightColumn(latestStatusData);
  }}
  showRightTab("operator-inbox");
  const root = $("layout-right");
  if (!root) return;
  root.querySelectorAll(".operator-inbox-item.target-highlight").forEach(function(el) {{
    el.classList.remove("target-highlight");
  }});
  const target = root.querySelector('[data-operator-inbox-component="pending_refresh"]') || root.querySelector('[data-tab="operator-inbox"]');
  if (target) {{
    if (target.classList && target.classList.contains("operator-inbox-item")) target.classList.add("target-highlight");
    target.scrollIntoView({{ block: "nearest", behavior: "smooth" }});
    if (typeof target.focus === "function") target.focus({{ preventScroll: true }});
  }}
}}

function renderOperatorInboxRunImpact(completion, operatorTrail) {{
  if (!operatorInboxRunFeedback) return "";
  completion = completion || {{}};
  operatorTrail = operatorTrail || {{}};
  const progress = completion.progress_state || {{}};
  const pendingRefresh = progress.pending_refresh_count === 0 || progress.pending_refresh_count
    ? progress.pending_refresh_count
    : operatorTrail.pending_refresh_count === 0 || operatorTrail.pending_refresh_count
    ? operatorTrail.pending_refresh_count
    : 0;
  const state = operatorInboxRunFeedback.state || "idle";
  const label = operatorInboxRunFeedback.label || operatorInboxRunFeedback.actionKey || "operator inbox 项";
  const component = operatorInboxRunFeedback.component || "";
  const progressLabel = progress.label || progress.status || completion.status || "-";
  let guidance = "Product closeout 状态以刷新后的服务数据为准。";
  if (state === "running") {{
    guidance = "Run 正在执行；Product closeout 将在结果返回后刷新。";
  }} else if (state === "failed") {{
    guidance = "Run 未完成；Product closeout 未被推进，请查看 INBOX 项或复制调用手动处理。";
  }} else if (pendingRefresh > 0) {{
    guidance = "Run 已返回；Product closeout 仍有 " + pendingRefresh + " 个 pending refresh，请优先运行或复制刷新项。";
  }} else if (state === "completed" && component === "pending_refresh") {{
    guidance = "刷新已收口；Product closeout 当前为 current。";
  }} else if (state === "completed") {{
    guidance = "Run 已返回；Product closeout 当前未报告 pending refresh。";
  }}
  let h = `<div class="operator-inbox-run-impact ${{escAttr(state)}}" role="status" aria-live="polite">`;
  h += `刚才 INBOX Run：${{esc(label)}} ｜ ${{esc(operatorInboxRunFeedback.message || state)}}`;
  h += `<div class="impact-meta">${{esc(operatorInboxRunFeedback.timestamp || "-")}} ｜ closeout ${{esc(progressLabel)}} ｜ ${{esc(guidance)}}</div>`;
  if (pendingRefresh > 0) {{
    h += `<div class="impact-actions"><button type="button" class="operator-inbox-btn" data-open-pending-refresh="true" aria-label="在 INBOX 中查看 pending refresh">Open refresh</button></div>`;
  }}
  h += `</div>`;
  return h;
}}

function renderServiceCapabilityCard(data) {{
  data = data || {{}};
  const svc = data.web_commander_service || {{}};
  if (!svc.ok) return "";
  const service = svc.service || {{}};
  const runtime = svc.runtime || {{}};
  const connector = svc.connector || {{}};
  const apps = svc.apps_connector_closeout || data.apps_connector_closeout || {{}};
  const completion = svc.product_console_completion || data.product_console_completion || {{}};
  const completionOverview = svc.product_completion_overview || data.product_completion_overview || completion.product_completion_overview || {{}};
  const operatorTrail = svc.operator_session_trail || data.operator_session_trail || completion.operator_session_trail || {{}};
  const operatorInbox = svc.operator_inbox || data.operator_inbox || {{}};
  const toolRefresh = svc.apps_connector_tool_refresh || data.apps_connector_tool_refresh || {{}};
  const cadence = svc.stable_replacement_cadence || data.stable_replacement_cadence || {{}};
  const profiles = Array.isArray(svc.profiles) ? svc.profiles : [];
  const calls = Array.isArray(svc.copyable_mcp_calls) ? svc.copyable_mcp_calls : [];
  const localStatus = connector.local_service_status || "-";
  const externalStatus = connector.external_connector_status || "-";
  const closeoutStatus = connector.operator_closeout_status || "-";
  const closeoutDecision = connector.operator_closeout_decision || "-";
  const webState = service.web_state || "-";
  const mcpState = service.mcp_state || "-";
  const localHealthy = localStatus === "healthy" || (webState === "healthy" && mcpState === "healthy");
  const externalHealthy = externalStatus === "healthy";
  const cardClass = !localHealthy ? "blocked" : (!externalHealthy ? "warn" : "");
  const title = localHealthy ? "Web/MCP 本地服务可用" : "Web/MCP 本地服务异常";
  const head = runtime.project_checkout_head || "";
  const headShort = head ? String(head).slice(0, 12) : "-";
  const reloadText = runtime.reload_needed_for_verification === true ? "需要验证重载" : runtime.reload_needed_for_verification === false ? "无需重载" : "-";
  const staleText = runtime.runtime_loaded_code_stale === true ? "stale" : runtime.runtime_loaded_code_stale === false ? "fresh" : "unknown";
  const localBadge = localHealthy ? "badge-ok" : "badge-err";
  const externalBadge = externalHealthy ? "badge-ok" : (externalStatus === "unverified" ? "badge-warn" : "badge-err");
  const preferredTool = apps.preferred_smoke_tool && apps.preferred_smoke_tool.tool ? apps.preferred_smoke_tool.tool : "-";
  const metadataStatus = toolRefresh.status || "-";
  const expectedTool = toolRefresh.expected_tool || preferredTool;
  const cadenceText = (cadence.status || "-") + " ｜ " + (cadence.recommended_cadence || "-");
  const batch = cadence.dev_batch_summary || {{}};
  const batchCount = batch.commit_count_since_stable;
  const batchCountText = (batchCount === 0 || batchCount) ? String(batchCount) + " commits" : "-";
  const batchText = batchCountText + " ｜ " + (batch.batch_size || "-") + " ｜ " + (batch.promotion_posture || "-");
  const completionAction = completion.safe_next_action || {{}};
  const completionProgress = completion.progress_state || {{}};
  const completionNext = [completionAction.action, completionAction.tool || completionAction.runbook, completionAction.authority].filter(Boolean).join(" ｜ ") || "-";
  const completionGapCount = completion.gap_count === 0 || completion.gap_count ? String(completion.gap_count) : "-";
  const completionProgressText = completionProgress.label || completionProgress.status || "-";
  const completionStep = completionProgress.next_step || completionNext;
  const overviewReady = completionOverview.ready_category_count === 0 || completionOverview.ready_category_count ? completionOverview.ready_category_count : "-";
  const overviewTotal = completionOverview.total_category_count === 0 || completionOverview.total_category_count ? completionOverview.total_category_count : "-";
  const completionText = (completionOverview.status || completion.status || "-") + " ｜ " + overviewReady + "/" + overviewTotal + " ｜ " + completionProgressText + " ｜ " + (completionOverview.next_step || completionStep);
  const completionCategories = Array.isArray(completionOverview.categories) ? completionOverview.categories : [];
  const completionCategoryText = completionCategories.length
    ? completionCategories.slice(0, 5).map((category) => {{
      const label = category.label || category.category_id || "-";
      const state = category.severity || category.status || "-";
      const gapCount = Array.isArray(category.gap_codes) ? category.gap_codes.length : 0;
      const tool = category.primary_tool || (category.primary_action && category.primary_action.tool) || "";
      return label + " " + state + " " + (gapCount ? "gaps " + gapCount : "ready") + (tool ? " " + tool : "");
    }}).join(" ｜ ")
    : "-";
  const trailEventCount = Array.isArray(operatorTrail.recent_events) ? operatorTrail.recent_events.length : 0;
  const trailRefreshCount = operatorTrail.pending_refresh_count === 0 || operatorTrail.pending_refresh_count ? operatorTrail.pending_refresh_count : "-";
  const trailRecoveryCount = operatorTrail.recovery_action_count === 0 || operatorTrail.recovery_action_count ? operatorTrail.recovery_action_count : Array.isArray(operatorTrail.recovery_actions) ? operatorTrail.recovery_actions.length : "-";
  const trailNext = operatorTrail.next_item && (operatorTrail.next_item.label || operatorTrail.next_item.item_id) ? operatorTrail.next_item.label || operatorTrail.next_item.item_id : "-";
  const operatorTrailText = (operatorTrail.status || "-") + " ｜ refresh " + trailRefreshCount + " ｜ recovery " + trailRecoveryCount + " ｜ events " + trailEventCount + " ｜ next " + trailNext;
  const inboxText = (operatorInbox.status || "-") + " ｜ total " + (operatorInbox.total_count === 0 || operatorInbox.total_count ? operatorInbox.total_count : "-") + " ｜ read " + (operatorInbox.read_only_count === 0 || operatorInbox.read_only_count ? operatorInbox.read_only_count : "-") + " ｜ gated " + (operatorInbox.gated_count === 0 || operatorInbox.gated_count ? operatorInbox.gated_count : "-");

  let h = `<div class="card summary-card service-capability-card ${{cardClass}}">`;
  h += `<div class="card-title">Web Commander 服务能力入口</div>`;
  h += `<div class="summary-title">${{esc(title)}}</div>`;
  h += `<div class="badge-row">`;
  h += `<span class="badge ${{localBadge}}">local ${{esc(localStatus)}}</span>`;
  h += `<span class="badge ${{webState === "healthy" ? "badge-ok" : "badge-warn"}}">Web ${{esc(webState)}}</span>`;
  h += `<span class="badge ${{mcpState === "healthy" ? "badge-ok" : "badge-warn"}}">MCP ${{esc(mcpState)}}</span>`;
  h += `<span class="badge ${{externalBadge}}">external ${{esc(externalStatus)}}</span>`;
  h += `<span class="badge badge-info">read-only</span>`;
  h += `</div>`;
  h += r("PID", service.pid || "-");
  h += r("Web", service.web_url || "-");
  h += r("MCP", service.mcp_url || "-");
  h += r("Checkout", headShort);
  h += r("Runtime", staleText + " ｜ " + reloadText);
  h += r("Connector closeout", closeoutStatus + " ｜ " + closeoutDecision);
  h += r("Apps smoke", (apps.status || "-") + " ｜ " + preferredTool);
  h += r("Product closeout", completionText);
  h += renderOperatorInboxRunImpact(completion, operatorTrail);
  h += r("Product categories", completionCategoryText);
  h += r("Operator trail", operatorTrailText);
  h += r("Operator inbox", inboxText);
  h += r("Apps metadata", metadataStatus + " ｜ " + expectedTool);
  h += r("Stable cadence", cadenceText);
  h += r("Dev batch", batchText);
  h += renderProductFollowupQueue(completion);

  if (profiles.length) {{
    h += `<div class="service-profile-row">`;
    for (const profile of profiles) {{
      const g = profile.polling_guidance || {{}};
      const label = profile.display_name || profile.profile_id || "-";
      const timing = (g.next_poll_after_seconds || "-") + "s x " + (g.max_poll_attempts || "-");
      h += `<span class="service-profile-pill" title="${{escAttr(g.policy || "")}}">${{esc(label)}} · ${{esc(timing)}}</span>`;
    }}
    h += `</div>`;
  }}

  if (calls.length) {{
    h += `<div class="service-copy-row">`;
    for (const call of calls.slice(0, 8)) {{
      const payload = JSON.stringify({{ name: call.tool || "", arguments: call.arguments || {{}} }}, null, 2);
      const callLabel = call.label || call.tool || "复制调用";
      const copyLabel = "复制 MCP 调用：" + callLabel;
      h += `<button type="button" class="service-copy-btn" data-copy-mcp-call="${{escAttr(payload)}}" aria-label="${{escAttr(copyLabel)}}" title="${{escAttr(copyLabel)}}">${{esc(callLabel)}}</button>`;
    }}
    h += `</div>`;
  }}
  h += `<div class="service-boundary">网页只展示服务事实和复制 MCP 调用，不授权 executor run、commit、push、stable replacement、ReviewDecision、GateEvent 或 Delivery accepted。</div>`;
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
  h += renderServiceCapabilityCard(data);
  h += renderThinGovernedLoopPreview(data);
  h += `</div>`;
  $("layout-center").innerHTML = h;
  $("layout-center").querySelectorAll("[data-copy-mcp-call]").forEach(function(btn) {{
    btn.addEventListener("click", function() {{
      copyTextToClipboard(this.getAttribute("data-copy-mcp-call") || "", this);
    }});
  }});
  $("layout-center").querySelectorAll("[data-open-product-followup]").forEach(function(btn) {{
    btn.addEventListener("click", function() {{
      openProductFollowupInInbox(this.getAttribute("data-open-product-followup") || "");
    }});
  }});
  $("layout-center").querySelectorAll("[data-open-pending-refresh]").forEach(function(btn) {{
    btn.addEventListener("click", function() {{
      openPendingRefreshInInbox();
    }});
  }});
  bindOperatorInboxActions($("layout-center"));
}}

function bindOperatorInboxActions(root) {{
  if (!root) return;
  root.querySelectorAll("[data-copy-operator-inbox]").forEach(function(btn) {{
    btn.addEventListener("click", function() {{
      copyTextToClipboard(this.getAttribute("data-copy-operator-inbox") || "", this);
    }});
  }});
  root.querySelectorAll("[data-run-operator-inbox]").forEach(function(btn) {{
    btn.addEventListener("click", async function() {{
      if (this.disabled) return;
      try {{
        const action = JSON.parse(this.getAttribute("data-run-operator-inbox") || "{{}}");
        const actionKey = this.getAttribute("data-operator-inbox-action-key") || operatorInboxActionKeyFromAction(action);
        const actionLabel = this.getAttribute("data-operator-inbox-action-label") || actionKey;
        const actionComponent = this.getAttribute("data-operator-inbox-component") || action.component || "";
        setOperatorInboxRunFeedback(actionKey, "running", "正在运行 operator inbox 项...", null, actionLabel, actionComponent);
        const data = await runAction(action, latestStatusData || {{}});
        if (data && data.ok === false) {{
          setOperatorInboxRunFeedback(actionKey, "failed", data.message || data.error_code || "运行失败。", data, actionLabel, actionComponent);
        }} else {{
          setOperatorInboxRunFeedback(actionKey, "completed", "运行完成，状态已刷新。", data, actionLabel, actionComponent);
        }}
      }} catch (e) {{
        const actionKey = this.getAttribute("data-operator-inbox-action-key") || "";
        const actionLabel = this.getAttribute("data-operator-inbox-action-label") || actionKey;
        const actionComponent = this.getAttribute("data-operator-inbox-component") || "";
        if (actionKey) setOperatorInboxRunFeedback(actionKey, "failed", String(e), null, actionLabel, actionComponent);
        showError(String(e));
      }}
    }});
  }});
}}

function operatorInboxActionKey(item) {{
  item = item || {{}};
  return String(item.item_id || item.tool || item.label || "operator_inbox_item");
}}

function operatorInboxActionKeyFromAction(action) {{
  action = action || {{}};
  return String(action.action || action.tool || "operator_inbox_item");
}}

function operatorInboxFeedbackFor(actionKey) {{
  if (!operatorInboxRunFeedback || operatorInboxRunFeedback.actionKey !== actionKey) return null;
  return operatorInboxRunFeedback;
}}

function operatorInboxSignature(data) {{
  const inbox = operatorInboxFromData(data || {{}});
  const items = Array.isArray(inbox.items) ? inbox.items : [];
  return items.map(function(item) {{
    item = item || {{}};
    return [
      operatorInboxActionKey(item),
      item.can_run_now === true ? "run" : "gate",
      item.required_scope || "",
      item.gate_level || "",
      item.tool || "",
    ].join(":");
  }}).join("|");
}}

function clearStaleOperatorInboxFeedback(data) {{
  if (!operatorInboxRunFeedback || operatorInboxRunFeedback.state === "running") return;
  const currentSignature = operatorInboxSignature(data || {{}});
  if (operatorInboxRunFeedback.inboxSignature && operatorInboxRunFeedback.inboxSignature !== currentSignature) {{
    operatorInboxRunFeedback = null;
  }}
}}

function operatorInboxFeedbackTimestamp() {{
  return new Date().toLocaleTimeString([], {{ hour: "2-digit", minute: "2-digit", second: "2-digit" }});
}}

function pushOperatorInboxRunTrail(actionKey, state, message, actionLabel) {{
  operatorInboxRunTrailFeedback = "";
  operatorInboxRunTrail.unshift({{
    actionKey: actionKey || "operator_inbox_item",
    label: actionLabel || actionKey || "operator inbox 项",
    state: state || "idle",
    message: String(message || ""),
    timestamp: operatorInboxFeedbackTimestamp(),
  }});
  operatorInboxRunTrail = operatorInboxRunTrail.slice(0, OPERATOR_INBOX_RUN_TRAIL_LIMIT);
}}

function setOperatorInboxRunFeedback(actionKey, state, message, data, actionLabel, actionComponent) {{
  const timestamp = operatorInboxFeedbackTimestamp();
  operatorInboxRunFeedback = {{
    actionKey: actionKey,
    label: actionLabel || actionKey || "operator inbox 项",
    component: actionComponent || "",
    state: state,
    message: message,
    source: "来自刚才的 Run 操作",
    timestamp: timestamp,
    inboxSignature: operatorInboxSignature(data || latestStatusData || {{}}),
  }};
  pushOperatorInboxRunTrail(actionKey, state, message, actionLabel);
  if (latestStatusData) {{
    renderCenterColumn(latestStatusData);
    renderRightColumn(latestStatusData);
    showRightTab("operator-inbox");
  }}
}}

function clearOperatorInboxRunTrail() {{
  operatorInboxRunTrail = [];
  operatorInboxRunTrailFeedback = "已清空本会话 operator inbox Run 记录；未触发后端请求。";
  if (latestStatusData) {{
    renderRightColumn(latestStatusData);
    showRightTab("operator-inbox");
  }}
}}

let registryActionInFlight = false;
let registryActionStatusState = "idle";
let registryActionStatusMessage = "项目管理操作就绪。";
let registryActionTrail = [];
let registryActionTrailFeedback = "";
const REGISTRY_ACTION_TRAIL_LIMIT = 5;

function setRegistryActionStatus(state, message) {{
  registryActionStatusState = state || "idle";
  registryActionStatusMessage = String(message || "");
  const el = $("registry-action-status");
  if (el) {{
    el.textContent = registryActionStatusMessage;
    el.className = "registry-action-status " + registryActionStatusState;
  }}
}}

function pushRegistryActionTrail(state, actionMeta, message) {{
  actionMeta = actionMeta || {{}};
  registryActionTrailFeedback = "";
  registryActionTrail.unshift({{
    state: state || "idle",
    label: actionMeta.label || "项目管理操作",
    target: actionMeta.target || "",
    message: String(message || ""),
    timestamp: operatorInboxFeedbackTimestamp(),
  }});
  registryActionTrail = registryActionTrail.slice(0, REGISTRY_ACTION_TRAIL_LIMIT);
}}

function clearRegistryActionTrail() {{
  registryActionTrail = [];
  registryActionTrailFeedback = "已清空本会话项目管理操作记录；未触发后端请求。";
  renderProjectManagementModal(latestStatusData || {{}});
}}

function registryAction(actionName, params) {{
  if (registryActionInFlight) return;
  registryActionInFlight = true;
  setGlobalLoading(true, "正在执行项目管理操作...");
  clearGlobalError();
  const actionMeta = registryActionMeta(actionName, params || {{}});
  const runningMessage = "正在执行项目管理操作：" + (actionMeta.label || actionName);
  setRegistryActionStatus("running", runningMessage);
  pushRegistryActionTrail("running", actionMeta, runningMessage);
  renderProjectManagementModal(latestStatusData || {{}});
  const payload = {{
    next_action: {{
      action: actionName,
      params: params || {{}},
      label: actionMeta.label || "项目管理操作",
      target: actionMeta.target || "",
      reason: actionMeta.description || "",
    }},
    client_context: {{
      source_url: window.location.href,
      timestamp: new Date().toISOString(),
    }},
  }};
  dangerousPostAction("/api/v2/action", payload)
    .then(function(data) {{
      registryActionInFlight = false;
      const failed = data && data.ok === false;
      const message = data && (data.message || data.error_code)
        ? String(data.message || data.error_code)
        : "项目管理操作完成，状态已刷新。";
      const trailMessage = failed ? ("项目管理操作失败：" + message) : message;
      setRegistryActionStatus(failed ? "failed" : "completed", trailMessage);
      pushRegistryActionTrail(failed ? "failed" : "completed", actionMeta, trailMessage);
      render(data);
      if (failed) showError(message);
      setGlobalLoading(false);
    }})
    .catch(function(e) {{
      registryActionInFlight = false;
      const failedMessage = "项目管理操作失败：" + String(e);
      setRegistryActionStatus("failed", failedMessage);
      pushRegistryActionTrail("failed", actionMeta, failedMessage);
      renderProjectManagementModal(latestStatusData || {{}});
      showError(String(e));
      setGlobalLoading(false);
    }});
}}

let projectIdentityPreviewId = "";
let projectIdentityEditor = null;
let projectIdentityStatusMessage = "请先预览迁移，预览通过后才能应用。";

function setProjectIdentityControls(state, message) {{
  const previewBtn = $("project-identity-preview");
  const applyBtn = $("project-identity-apply");
  const result = $("project-identity-result");
  const busy = state === "previewing" || state === "applying";
  if (previewBtn) {{
    previewBtn.disabled = busy;
    previewBtn.textContent = state === "previewing" ? "预览中..." : "预览迁移";
    previewBtn.setAttribute("aria-busy", state === "previewing" ? "true" : "false");
  }}
  if (applyBtn) {{
    const canApply = !!projectIdentityPreviewId && !busy;
    applyBtn.disabled = !canApply;
    applyBtn.textContent = state === "applying" ? "应用中..." : "应用迁移";
    applyBtn.setAttribute("aria-busy", state === "applying" ? "true" : "false");
    applyBtn.setAttribute("aria-disabled", canApply ? "false" : "true");
  }}
  if (message != null) {{
    projectIdentityStatusMessage = String(message);
    if (result) result.textContent = projectIdentityStatusMessage;
  }}
}}

function clearProjectIdentityPreview(message) {{
  projectIdentityPreviewId = "";
  setProjectIdentityControls("idle", message || "请先预览迁移，预览通过后才能应用。");
}}

function openProjectIdentityEditor(button) {{
  clearProjectIdentityPreview("请先预览迁移，预览通过后才能应用。");
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
  clearProjectIdentityPreview("草稿已修改，请重新预览迁移。");
}}

function cancelProjectIdentityEdit() {{
  clearProjectIdentityPreview("请先预览迁移，预览通过后才能应用。");
  projectIdentityEditor = null;
  renderProjectManagementModal(latestStatusData || {{}});
}}

function previewProjectIdentity() {{
  const projectId = $("project-identity-id");
  const projectName = $("project-identity-name");
  const displayName = $("project-identity-display");
  const projectRoot = $("project-identity-root");
  projectIdentityPreviewId = "";
  setProjectIdentityControls("previewing", "正在生成迁移预览...");
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
      projectIdentityPreviewId = data.ok ? (data.preview_id || "") : "";
      const blockers = Array.isArray(data.blockers) ? data.blockers : [];
      const changes = Array.isArray(data.changes) ? data.changes : [];
      const message = data.ok && projectIdentityPreviewId
        ? "预览完成，将修改：" + changes.map(function(item) {{ return item.target; }}).join("、")
        : "预览阻断：" + (blockers.length ? blockers.join("；") : "未返回有效预览 ID。");
      setProjectIdentityControls("idle", message);
    }})
    .catch(function(e) {{
      projectIdentityPreviewId = "";
      setProjectIdentityControls("idle", "预览失败：" + String(e));
    }});
}}

function applyProjectIdentity() {{
  if (!projectIdentityPreviewId) {{
    setProjectIdentityControls("idle", "请先生成有效预览。");
    return;
  }}
  setProjectIdentityControls("applying", "正在应用迁移...");
  dangerousPostAction("/api/project-identity/apply", {{ preview_id: projectIdentityPreviewId }})
    .then(function(data) {{
      const message = data.message || (data.ok ? "迁移完成，请刷新页面。" : "迁移失败。");
      if (data.ok) {{
        clearProjectIdentityPreview(message);
        projectIdentityEditor = null;
        refresh();
      }} else {{
        clearProjectIdentityPreview(message);
      }}
    }})
    .catch(function(e) {{
      clearProjectIdentityPreview("迁移失败：" + String(e));
    }});
}}

function openProjectManagement() {{
  renderProjectManagementModal(latestStatusData || {{}});
  openModal("project-management-modal");
}}

function closeProjectManagement(event) {{
  closeModal("project-management-modal", event);
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
  openModal("issue-detail-modal");
}}

function closeIssueModal(event) {{
  closeModal("issue-detail-modal", event);
}}

function openTodoModal(todoId, content) {{
  const titleEl = $("todo-detail-modal-title");
  const body = $("todo-detail-modal-body");
  if (titleEl) titleEl.textContent = todoId ? "TODO 详情：" + todoId : "TODO 详情";
  if (body) {{
    body.innerHTML = `<div class="todo-detail-id">${{esc(todoId || "-")}}</div><div class="todo-detail-content">${{esc(content || "")}}</div>`;
  }}
  openModal("todo-detail-modal");
}}

function closeTodoModal(event) {{
  closeModal("todo-detail-modal", event);
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
  openModal("version-prompt-modal");

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
  closeModal("version-prompt-modal", event);
}}

function openDecisionModal(decisionId, title, decision, reason, relatedVersions, status) {{
  const titleEl = $("todo-detail-modal-title");
  const body = $("todo-detail-modal-body");
  if (titleEl) titleEl.textContent = decisionId ? "DECISION 详情：" + decisionId : "DECISION 详情";
  if (body) {{
    const versions = relatedVersions ? relatedVersions : "-";
    body.innerHTML = `<div class="todo-detail-id">${{esc(decisionId || "-")}} ｜ ${{esc(status || "-")}} ｜ 版本：${{esc(versions)}}</div><div class="todo-detail-content"><strong>${{esc(title || "")}}</strong>\n\n决策：${{esc(decision || "")}}\n\n原因：${{esc(reason || "")}}</div>`;
  }}
  openModal("todo-detail-modal");
}}

function showRightTab(tabName) {{
  tabName = normalizeRightTab(tabName);
  activeRightTab = tabName;
  const card = $("layout-right") && $("layout-right").querySelector(".card");
  if (card) {{
    card.querySelectorAll(".tab-btn").forEach(function(b) {{
      b.classList.remove("active");
      b.setAttribute("aria-selected", "false");
    }});
    const tabBtn = card.querySelector('[data-tab-button="' + tabName + '"]');
    if (tabBtn) {{
      tabBtn.classList.add("active");
      tabBtn.setAttribute("aria-selected", "true");
    }}
    card.querySelectorAll(".tab-content").forEach(function(tc) {{
      tc.style.display = "none";
      tc.setAttribute("aria-hidden", "true");
    }});
    const tabContent = card.querySelector('[data-tab="' + tabName + '"]');
    if (tabContent) {{
      tabContent.style.display = "block";
      tabContent.setAttribute("aria-hidden", "false");
    }}
  }}
}}

function showLeftTab(tabName) {{
  tabName = normalizeLeftTab(tabName);
  activeLeftTab = tabName;
  const card = $("layout-left") && $("layout-left").querySelector(".card");
  if (card) {{
    card.querySelectorAll(".tab-btn").forEach(function(b) {{
      b.classList.remove("active");
      b.setAttribute("aria-selected", "false");
    }});
    const tabBtn = card.querySelector('[data-left-tab-button="' + tabName + '"]');
    if (tabBtn) {{
      tabBtn.classList.add("active");
      tabBtn.setAttribute("aria-selected", "true");
    }}
    card.querySelectorAll('[data-left-tab]').forEach(function(tc) {{
      tc.style.display = "none";
      tc.setAttribute("aria-hidden", "true");
    }});
    const tabContent = card.querySelector('[data-left-tab="' + tabName + '"]');
    if (tabContent) {{
      tabContent.style.display = "block";
      tabContent.setAttribute("aria-hidden", "false");
    }}
  }}
}}

function normalizeLeftTab(tabName) {{
  return LEFT_TAB_NAMES.includes(tabName) ? tabName : LEFT_TAB_DEFAULT;
}}

function leftTabActiveClass(tabName) {{
  return normalizeLeftTab(activeLeftTab) === tabName ? " active" : "";
}}

function leftTabDisplayStyle(tabName) {{
  return normalizeLeftTab(activeLeftTab) === tabName ? "" : ` style="display:none;"`;
}}

function leftTabAriaSelected(tabName) {{
  return normalizeLeftTab(activeLeftTab) === tabName ? "true" : "false";
}}

function leftTabAriaHidden(tabName) {{
  return normalizeLeftTab(activeLeftTab) === tabName ? "false" : "true";
}}

function normalizeRightTab(tabName) {{
  return RIGHT_TAB_NAMES.includes(tabName) ? tabName : RIGHT_TAB_DEFAULT;
}}

function rightTabActiveClass(tabName) {{
  return normalizeRightTab(activeRightTab) === tabName ? " active" : "";
}}

function rightTabDisplayStyle(tabName) {{
  return normalizeRightTab(activeRightTab) === tabName ? "" : ` style="display:none;"`;
}}

function rightTabAriaSelected(tabName) {{
  return normalizeRightTab(activeRightTab) === tabName ? "true" : "false";
}}

function rightTabAriaHidden(tabName) {{
  return normalizeRightTab(activeRightTab) === tabName ? "false" : "true";
}}

function rightTabCountBadge(count, activeClass) {{
  const numeric = Number(count || 0);
  const safeCount = Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
  const badgeClass = safeCount > 0 ? activeClass : "tab-badge";
  const badgeText = safeCount > 99 ? "99+" : String(safeCount);
  return `<span class="${{escAttr(badgeClass)}}">${{esc(badgeText)}}</span>`;
}}

function handleRightTabKeydown(event, tabName) {{
  const key = event.key;
  if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(key)) return;
  event.preventDefault();
  const current = normalizeRightTab(tabName || activeRightTab);
  let index = RIGHT_TAB_NAMES.indexOf(current);
  if (index < 0) index = 0;
  if (key === "ArrowRight") index = (index + 1) % RIGHT_TAB_NAMES.length;
  else if (key === "ArrowLeft") index = (index - 1 + RIGHT_TAB_NAMES.length) % RIGHT_TAB_NAMES.length;
  else if (key === "Home") index = 0;
  else if (key === "End") index = RIGHT_TAB_NAMES.length - 1;
  const nextTab = RIGHT_TAB_NAMES[index];
  showRightTab(nextTab);
  const nextButton = $("layout-right") && $("layout-right").querySelector('[data-tab-button="' + nextTab + '"]');
  if (nextButton) nextButton.focus();
  if (nextTab === "todolist") syncAdaptiveTodoPageSize();
}}

function handleLeftTabKeydown(event, tabName) {{
  const key = event.key;
  if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(key)) return;
  event.preventDefault();
  const current = normalizeLeftTab(tabName || activeLeftTab);
  let index = LEFT_TAB_NAMES.indexOf(current);
  if (index < 0) index = 0;
  if (key === "ArrowRight") index = (index + 1) % LEFT_TAB_NAMES.length;
  else if (key === "ArrowLeft") index = (index - 1 + LEFT_TAB_NAMES.length) % LEFT_TAB_NAMES.length;
  else if (key === "Home") index = 0;
  else if (key === "End") index = LEFT_TAB_NAMES.length - 1;
  const nextTab = LEFT_TAB_NAMES[index];
  showLeftTab(nextTab);
  const nextButton = $("layout-left") && $("layout-left").querySelector('[data-left-tab-button="' + nextTab + '"]');
  if (nextButton) nextButton.focus();
}}

function switchLeftTab(tabName, btn) {{
  showLeftTab(tabName);
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
  if (normalizeRightTab(activeRightTab) !== "todolist") return;
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
  adaptiveTodoPageSizeSyncing = false;
}}

function changeTodoPage(delta) {{
  activeRightTab = "todolist";
  const data = latestStatusData || {{}};
  const todo = data.todolist || {{}};
  const items = Array.isArray(todo.items) ? todo.items : [];
  const maxPage = Math.max(1, Math.ceil(items.length / adaptiveTodoPageSize));
  todoPage = Math.min(maxPage, Math.max(1, todoPage + delta));
  renderRightColumn(data);
  showRightTab("todolist");
}}

function changeDecisionPage(delta) {{
  activeRightTab = "decision";
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

function renderRegistryActionTrail() {{
  let h = `<div class="registry-action-trail" aria-label="最近项目管理操作">`;
  h += `<div class="registry-action-trail-title">最近项目管理操作</div>`;
  h += `<div class="local-trail-boundary">${{esc(LOCAL_TRAIL_BOUNDARY_TEXT)}}</div>`;
  h += `<button type="button" class="local-trail-clear" aria-label="清空最近项目管理操作记录" aria-disabled="${{registryActionTrail.length ? "false" : "true"}}" onclick="clearRegistryActionTrail()"${{registryActionTrail.length ? "" : " disabled"}}>清空本会话记录</button>`;
  h += `<div class="local-trail-feedback" role="status" aria-live="polite">${{esc(registryActionTrailFeedback)}}</div>`;
  if (!registryActionTrail.length) {{
    h += `<div class="registry-action-trail-item">暂无最近操作。</div>`;
  }} else {{
    h += `<div class="registry-action-trail-list">`;
    for (const item of registryActionTrail) {{
      const target = item.target ? " ｜ 目标：" + item.target : "";
      h += `<div class="registry-action-trail-item ${{escAttr(item.state || "")}}">${{esc(item.timestamp || "-")}} ｜ ${{esc(item.label || "项目管理操作")}}${{esc(target)}} ｜ ${{esc(item.message || "")}}</div>`;
    }}
    h += `</div>`;
  }}
  h += `</div>`;
  return h;
}}

function renderProjectManagement(data) {{
  const registry = data.project_registry || {{}};
  const projects = Array.isArray(registry.projects) ? registry.projects : [];
  const currentRoot = currentProjectRootForSwitcher(data || {{}});
  const registryBusyAttr = registryActionInFlight ? " disabled" : "";
  const registryBusyAria = registryActionInFlight ? "true" : "false";
  let h = "";
  h += `<div class="card"><div class="card-title">项目登记管理</div>`;
  h += `<div class="modal-sync-status" role="status" aria-live="polite">${{esc(projectManagementSyncStatusText())}}</div>`;
  h += `<div style="font-size:11px;color:#8b949e;margin-bottom:8px;">这里管理项目登记元数据。移出/清理只修改登记记录，不会删除磁盘文件；应用迁移会按预览修改 registry / plan / state / settings。当前项目会标注“当前”，/mnt/... 会标注为 Windows 挂载路径。</div>`;
  h += `<div id="registry-action-status" class="registry-action-status ${{escAttr(registryActionStatusState)}}" role="status" aria-live="polite">${{esc(registryActionStatusMessage)}}</div>`;
  h += renderRegistryActionTrail();

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
      const unregisterParams = {{ project_root: root }};
      const unregisterLabel = registryActionButtonLabel("project_registry_unregister", unregisterParams);
      h += `<button class="action-btn" title="${{escAttr(unregisterLabel)}}" aria-label="${{escAttr(unregisterLabel)}}" aria-busy="${{registryBusyAria}}" aria-disabled="${{registryBusyAria}}" style="width:auto;padding:3px 10px;font-size:11px;margin:0;flex:0 0 auto;" onclick="registryAction('project_registry_unregister',{{project_root:'${{escAttr(root)}}'}})"${{registryBusyAttr}}>移出登记</button>`;
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
        const applyDisabled = projectIdentityPreviewId ? "" : " disabled";
        const applyAriaDisabled = projectIdentityPreviewId ? "false" : "true";
        h += `<div style="display:flex;gap:6px;flex-wrap:wrap;"><button id="project-identity-preview" class="action-btn" style="width:auto;" aria-busy="false" onclick="previewProjectIdentity()">预览迁移</button><button id="project-identity-apply" class="action-btn" style="width:auto;" aria-busy="false" aria-disabled="${{applyAriaDisabled}}" onclick="applyProjectIdentity()"${{applyDisabled}}>应用迁移</button><button class="action-btn" style="width:auto;" onclick="cancelProjectIdentityEdit()">取消</button></div>`;
        h += `<div id="project-identity-result" role="status" aria-live="polite" style="font-size:11px;color:#8b949e;white-space:pre-wrap;">${{esc(projectIdentityStatusMessage)}}</div>`;
        h += `<div style="font-size:11px;color:#8b949e;">应用成功后请刷新页面；项目路径变化时请重启或重新选择项目。</div>`;
        h += `</div></div>`;
      }}
      h += `</div>`;
    }}
  }}

  h += `<div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;">`;
  const pruneUnavailableLabel = registryActionButtonLabel("project_registry_prune_unavailable", {{}});
  const pruneTemporaryLabel = registryActionButtonLabel("project_registry_prune_temporary", {{}});
  h += `<button class="action-btn" title="${{escAttr(pruneUnavailableLabel)}}" aria-label="${{escAttr(pruneUnavailableLabel)}}" aria-busy="${{registryBusyAria}}" aria-disabled="${{registryBusyAria}}" style="width:auto;padding:4px 12px;font-size:12px;" onclick="registryAction('project_registry_prune_unavailable',{{}})"${{registryBusyAttr}}>清理不可用登记</button>`;
  h += `<button class="action-btn" title="${{escAttr(pruneTemporaryLabel)}}" aria-label="${{escAttr(pruneTemporaryLabel)}}" aria-busy="${{registryBusyAria}}" aria-disabled="${{registryBusyAria}}" style="width:auto;padding:4px 12px;font-size:12px;" onclick="registryAction('project_registry_prune_temporary',{{}})"${{registryBusyAttr}}>清理临时登记</button>`;
  h += `</div>`;
  h += `</div>`;
  return h;
}}

function renderOperatorInboxItem(item) {{
  item = item || {{}};
  const itemLabel = item.label || item.tool || item.item_id || "Inbox item";
  const actionKey = operatorInboxActionKey(item);
  const feedback = operatorInboxFeedbackFor(actionKey);
  const followupItemId = item.copy_payload && item.copy_payload.item_id ? String(item.copy_payload.item_id) : "";
  const itemComponent = item.component ? String(item.component) : "";
  const payload = JSON.stringify(item.copy_payload || {{ tool: item.tool || "", arguments: item.arguments || {{}} }}, null, 2);
  const nextAction = JSON.stringify({{
    action: item.item_id || item.tool || "operator_inbox_item",
    tool: item.tool || "",
    arguments: item.arguments || {{}},
    required_scope: item.required_scope || "mcp:read",
    gate_level: item.gate_level || "read_only",
    component: itemComponent,
  }});
  const canRun = item.can_run_now === true && item.required_scope === "mcp:read" && item.tool;
  const isRunning = feedback && feedback.state === "running";
  const copyLabel = "复制 operator inbox 调用：" + itemLabel;
  const runLabel = isRunning
    ? "正在运行只读 operator inbox 项：" + itemLabel
    : canRun
    ? "运行只读 operator inbox 项：" + itemLabel
    : "需要更高权限，不能在 Web Console 直接运行：" + itemLabel;
  let h = `<div class="operator-inbox-item" tabindex="-1" data-operator-inbox-key="${{escAttr(actionKey)}}" data-operator-inbox-followup-item-id="${{escAttr(followupItemId)}}" data-operator-inbox-component="${{escAttr(itemComponent)}}">`;
  h += `<div class="operator-inbox-head"><div class="operator-inbox-title">${{esc(itemLabel)}}</div><span class="badge ${{canRun ? "badge-ok" : "badge-warn"}}">${{esc(item.required_scope || "-")}}</span></div>`;
  h += `<div class="operator-inbox-meta"><span>${{esc(item.source || "-")}}</span><span>${{esc(item.component || "-")}}</span><span>${{esc(item.tool || "-")}}</span><span>${{esc(item.gate_level || "-")}}</span></div>`;
  h += `<div class="operator-inbox-why">${{esc(item.why || "Review this operator inbox item.")}}</div>`;
  h += `<div class="operator-inbox-actions">`;
  h += `<button type="button" class="operator-inbox-btn operator-inbox-copy" data-copy-operator-inbox="${{escAttr(payload)}}" aria-label="${{escAttr(copyLabel)}}" title="${{escAttr(copyLabel)}}">Copy</button>`;
  h += `<button type="button" class="operator-inbox-btn operator-inbox-run" data-run-operator-inbox="${{escAttr(nextAction)}}" data-operator-inbox-action-key="${{escAttr(actionKey)}}" data-operator-inbox-action-label="${{escAttr(itemLabel)}}" data-operator-inbox-component="${{escAttr(itemComponent)}}" aria-label="${{escAttr(runLabel)}}" title="${{escAttr(runLabel)}}" aria-busy="${{isRunning ? "true" : "false"}}" aria-disabled="${{canRun && !isRunning ? "false" : "true"}}" ${{canRun && !isRunning ? "" : "disabled"}}>${{isRunning ? "Running" : (canRun ? "Run" : "Gate")}}</button>`;
  h += `</div>`;
  if (feedback) {{
    h += `<div class="operator-inbox-action-status ${{escAttr(feedback.state || "")}}" role="status" aria-live="polite">${{esc(feedback.message || "")}}</div>`;
    h += `<div class="operator-inbox-action-meta">${{esc(feedback.source || "来自刚才的 Run 操作")}} ｜ ${{esc(feedback.timestamp || "")}}</div>`;
  }}
  h += `</div>`;
  return h;
}}

function operatorInboxFromData(data) {{
  data = data || {{}};
  const svc = data.web_commander_service || {{}};
  return svc.operator_inbox || data.operator_inbox || {{}};
}}

function operatorInboxCountSummary(inbox) {{
  inbox = inbox || {{}};
  const items = Array.isArray(inbox.items) ? inbox.items : [];
  const total = inbox.total_count === 0 || inbox.total_count ? inbox.total_count : items.length;
  const readOnly = inbox.read_only_count === 0 || inbox.read_only_count ? inbox.read_only_count : "-";
  const gated = inbox.gated_count === 0 || inbox.gated_count ? inbox.gated_count : "-";
  return {{ items: items, total: total, readOnly: readOnly, gated: gated }};
}}

function operatorInboxNumericCount(value, fallback) {{
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}}

function renderOperatorInboxRunTrail() {{
  let h = `<div class="operator-inbox-run-trail" aria-label="最近 operator inbox Run">`;
  h += `<div class="operator-inbox-run-trail-title">最近 Run</div>`;
  h += `<div class="local-trail-boundary">${{esc(LOCAL_TRAIL_BOUNDARY_TEXT)}}</div>`;
  h += `<button type="button" class="local-trail-clear" aria-label="清空最近 operator inbox Run 记录" aria-disabled="${{operatorInboxRunTrail.length ? "false" : "true"}}" onclick="clearOperatorInboxRunTrail()"${{operatorInboxRunTrail.length ? "" : " disabled"}}>清空本会话记录</button>`;
  h += `<div class="local-trail-feedback" role="status" aria-live="polite">${{esc(operatorInboxRunTrailFeedback)}}</div>`;
  if (!operatorInboxRunTrail.length) {{
    h += `<div class="operator-inbox-run-trail-item">暂无最近 Run。</div>`;
  }} else {{
    h += `<div class="operator-inbox-run-trail-list">`;
    for (const item of operatorInboxRunTrail) {{
      h += `<div class="operator-inbox-run-trail-item ${{escAttr(item.state || "")}}">${{esc(item.timestamp || "-")}} ｜ ${{esc(item.label || item.actionKey || "operator inbox 项")}} ｜ ${{esc(item.message || "")}}</div>`;
    }}
    h += `</div>`;
  }}
  h += `</div>`;
  return h;
}}

function renderOperatorInboxPanel(data) {{
  data = data || {{}};
  const inbox = operatorInboxFromData(data);
  const counts = operatorInboxCountSummary(inbox);
  const items = counts.items;
  const sources = [];
  for (const item of items) {{
    const source = item && item.source ? String(item.source) : "-";
    if (!sources.includes(source)) sources.push(source);
  }}

  let h = `<div class="operator-inbox-summary">`;
  h += `${{esc(inbox.status || "-")}} ｜ total ${{esc(counts.total)}} ｜ read ${{esc(counts.readOnly)}} ｜ gated ${{esc(counts.gated)}}`;
  if (inbox.authority_boundary) h += `<br>${{esc(inbox.authority_boundary)}}`;
  h += `</div>`;
  if (sources.length) {{
    h += `<div class="operator-inbox-meta">`;
    for (const source of sources.sort()) {{
      const count = items.filter((item) => (item && item.source ? String(item.source) : "-") === source).length;
      h += `<span>${{esc(source)}} ${{count}}</span>`;
    }}
    h += `</div>`;
  }}
  h += renderOperatorInboxRunTrail();
  if (!items.length) {{
    h += `<div class="empty-state">暂无 operator inbox 项</div>`;
  }} else {{
    h += `<div class="operator-inbox-list">`;
    for (const item of items) {{
      h += renderOperatorInboxItem(item);
    }}
    h += `</div>`;
  }}
  return h;
}}

function renderRightColumn(data) {{
  let h = "";
  activeRightTab = normalizeRightTab(activeRightTab);
  clearStaleOperatorInboxFeedback(data || {{}});
  const todoForBadge = (data || {{}}).todolist || {{}};
  const todoItemsForBadge = Array.isArray(todoForBadge.items) ? todoForBadge.items : [];
  const todoCount = todoForBadge.ok === false ? 0 : todoItemsForBadge.length;
  const todoTabTitle = todoForBadge.ok === false
    ? "TODOLIST: unavailable"
    : "TODOLIST: " + todoCount + " item" + (todoCount === 1 ? "" : "s");
  const decisionForBadge = (data || {{}}).decisions || {{}};
  const decisionsForBadge = Array.isArray(decisionForBadge.decisions) ? decisionForBadge.decisions : [];
  const decisionCount = decisionForBadge.ok === false ? 0 : decisionsForBadge.length;
  const decisionTabTitle = decisionForBadge.ok === false
    ? "DECISION: unavailable"
    : "DECISION: " + decisionCount + " record" + (decisionCount === 1 ? "" : "s");
  const inbox = operatorInboxFromData(data || {{}});
  const inboxCounts = operatorInboxCountSummary(inbox);
  const inboxTotalNumber = operatorInboxNumericCount(inboxCounts.total, inboxCounts.items.length);
  const inboxGatedNumber = operatorInboxNumericCount(inboxCounts.gated, 0);
  const inboxBadgeClass = inboxGatedNumber > 0 ? "tab-badge warn" : (inboxTotalNumber > 0 ? "tab-badge info" : "tab-badge");
  const inboxTabTitle = "Operator inbox: " + inboxCounts.total + " total, " + inboxCounts.readOnly + " read-only, " + inboxCounts.gated + " gated";

  // Tabbed card: TODOLIST + INBOX + DECISION + MEMORY
  h += `<div class="card action-tab-card">`;
  h += `<div class="tab-bar" role="tablist" aria-label="Operator workspace">`;
  h += `<button type="button" id="right-tab-todolist" role="tab" aria-selected="${{rightTabAriaSelected("todolist")}}" aria-controls="right-panel-todolist" aria-label="${{escAttr(todoTabTitle)}}" class="tab-btn${{rightTabActiveClass("todolist")}}" data-tab-button="todolist" title="${{escAttr(todoTabTitle)}}" onclick="switchActionTab('todolist', this)" onkeydown="handleRightTabKeydown(event, 'todolist')"><span class="tab-icon">☰</span>TODOLIST${{rightTabCountBadge(todoCount, "tab-badge info")}}</button>`;
  h += `<button type="button" id="right-tab-operator-inbox" role="tab" aria-selected="${{rightTabAriaSelected("operator-inbox")}}" aria-controls="right-panel-operator-inbox" aria-label="${{escAttr(inboxTabTitle)}}" class="tab-btn${{rightTabActiveClass("operator-inbox")}}" data-tab-button="operator-inbox" title="${{escAttr(inboxTabTitle)}}" onclick="switchActionTab('operator-inbox', this)" onkeydown="handleRightTabKeydown(event, 'operator-inbox')"><span class="tab-icon">▣</span>INBOX${{rightTabCountBadge(inboxTotalNumber, inboxBadgeClass)}}</button>`;
  h += `<button type="button" id="right-tab-decision" role="tab" aria-selected="${{rightTabAriaSelected("decision")}}" aria-controls="right-panel-decision" aria-label="${{escAttr(decisionTabTitle)}}" class="tab-btn${{rightTabActiveClass("decision")}}" data-tab-button="decision" title="${{escAttr(decisionTabTitle)}}" onclick="switchActionTab('decision', this)" onkeydown="handleRightTabKeydown(event, 'decision')"><span class="tab-icon">◆</span>DECISION${{rightTabCountBadge(decisionCount, "tab-badge info")}}</button>`;
  h += `<button type="button" id="right-tab-memory" role="tab" aria-selected="${{rightTabAriaSelected("memory")}}" aria-controls="right-panel-memory" aria-label="MEMORY" class="tab-btn${{rightTabActiveClass("memory")}}" data-tab-button="memory" onclick="switchActionTab('memory', this)" onkeydown="handleRightTabKeydown(event, 'memory')"><span class="tab-icon">◎</span>MEMORY</button>`;
  h += `</div>`;

  // TODOLIST tab
  h += `<div id="right-panel-todolist" class="tab-content" role="tabpanel" aria-labelledby="right-tab-todolist" aria-hidden="${{rightTabAriaHidden("todolist")}}" tabindex="0" data-tab="todolist"${{rightTabDisplayStyle("todolist")}}>`;
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
        const todoCopyLabel = "复制 TODO ID " + (todoId || "-");
        h += `<div class="todo-item">`;
        h += `<div class="todo-id-row">`;
        h += `<div class="key">ID ${{esc(todoId)}}</div>`;
        h += `<button type="button" class="todo-copy-btn" data-copy-todo-id="${{escAttr(todoId)}}" aria-label="${{escAttr(todoCopyLabel)}}" title="${{escAttr(todoCopyLabel)}}">复制</button>`;
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

  // INBOX tab
  h += `<div id="right-panel-operator-inbox" class="tab-content" role="tabpanel" aria-labelledby="right-tab-operator-inbox" aria-hidden="${{rightTabAriaHidden("operator-inbox")}}" tabindex="0" data-tab="operator-inbox"${{rightTabDisplayStyle("operator-inbox")}}>`;
  h += renderOperatorInboxPanel(data);
  h += `</div>`;

  // DECISION tab
  h += `<div id="right-panel-decision" class="tab-content" role="tabpanel" aria-labelledby="right-tab-decision" aria-hidden="${{rightTabAriaHidden("decision")}}" tabindex="0" data-tab="decision"${{rightTabDisplayStyle("decision")}}>`;
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
  h += `<div id="right-panel-memory" class="tab-content" role="tabpanel" aria-labelledby="right-tab-memory" aria-hidden="${{rightTabAriaHidden("memory")}}" tabindex="0" data-tab="memory"${{rightTabDisplayStyle("memory")}}>`;
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
  bindOperatorInboxActions($("layout-right"));
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
  tabName = normalizeRightTab(tabName);
  showRightTab(tabName);
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
