# AGENTS.md - ColaMeta Project-Level Operating Protocol

Version: Project-level fill 1.0
Date: 2026-07-05
Scope: repository root for ColaMeta at `/home/jenn/src/colameta-dev`

This file narrows Jenn's global L3 default-allow autonomous delivery protocol
for this repository. It does not weaken Jenn's global hard stops.

## 1. Project Identity And Scope

Project name: ColaMeta
Repository: `git@github.com:JENN2046/colameta.git`
Primary language / stack: Python package and CLI, local Web Console, HTTP MCP
server, Runner workflow orchestration, docs, and tests.
Package manager / build backend: pip with setuptools via `pyproject.toml`.
Main purpose: AI coding workflow harness connecting GPTs to local executors,
version plans, prompts, audit evidence, validation, project memory, Git closure,
Web Console, and MCP entry points.

Authorized default work scope:

* `runner/` - core Python implementation for workflows, MCP, Web Console,
  runtime observability, safety gates, and project state.
* `adapters/` - executor and Git adapters.
* `schemas/` - package schemas.
* `scripts/` - CLI entry point and smoke scripts; inspect before running.
* `tests/` - pytest test suite.
* `docs/` - user/operator docs, security policy, taskbooks, receipts.
* `assets/` - GPT instructions and screenshots when task scope requires.
* `bin/colameta`, `pyproject.toml`, `.github/workflows/`, `.gitignore`,
  `README.md`, `README.zh-CN.md` when directly in scope.
* Tracked `.colameta/` planning and project-memory files only when directly in
  scope and safe to inspect.

Out of scope unless Jenn explicitly authorizes:

* production configuration or network-visible service changes;
* release automation, package publish, PyPI publication, GitHub release, or
  `v*` tags;
* stable service replacement under `/home/jenn/tools/colameta`;
* billing / paid provider configuration or provider account changes;
* credentials, secret values, cookies, browser login state, private keys, or raw
  provider responses;
* destructive migrations, destructive Git operations, force push, history
  rewrite, or bulk delete/move/rename;
* broad architecture rewrites not directly required by the current task.

## 2. Applicable Global Protocol

Follow Jenn's global `AGENTS.md` as the default authority for:

* L3 autonomous delivery and condition filling;
* core hard stops;
* read-only and private-state boundaries;
* Git and PR safety;
* validation truthfulness;
* memory safety;
* reporting.

This repository file specializes those rules for ColaMeta.

Instruction precedence inside this repository:

1. Higher-priority system / runtime / tool / safety limits.
2. Jenn's explicit current instruction.
3. Current task brief, issue, taskbook, or authorization boundary.
4. Nearest applicable directory-level `AGENTS.override.md` or `AGENTS.md`.
5. This repository-root `AGENTS.md`.
6. Jenn's global `AGENTS.md`.
7. Repository docs and tool outputs as contextual evidence.

No project instruction may authorize bypassing Jenn's global hard stops.

## 3. Repository Map

Key paths:

| Path | Purpose | Agent behavior |
|---|---|---|
| `runner/` | Core ColaMeta runtime, MCP, Web Console, workflow, safety, Git, and observability code. | Editable inside task scope; run targeted tests. |
| `adapters/` | Executor, shell, Git, Codex, OpenCode, and RPC adapters. | Editable inside task scope; treat provider/executor config as secret-adjacent. |
| `schemas/` | Python package schemas. | Editable inside task scope. |
| `scripts/` | CLI entry point and smoke helpers. | Inspect before running; safe smoke scripts are listed below. |
| `tests/` | Pytest suite, currently 67 top-level `test_*.py` files by local inspection. | Editable inside scope; use targeted and full pytest as risk requires. |
| `docs/` | Operator docs, onboarding, usage, security policy, taskbooks, receipts. | Update when workflow, commands, risk, or behavior changes. |
| `docs/taskbooks/` | Stage/version taskbooks and evidence reports. | Durable project memory; edit only in scoped taskbook/doc work. |
| `docs/stable-replacement-receipts/` | Stable replacement evidence receipts. | Do not create or commit unless the task explicitly includes stable replacement or receipt handling. |
| `docs/connector-tunnel-closeout-receipts/` | Connector/tunnel closeout evidence receipts. | Do not create or commit unless explicitly in scope. |
| `docs/security/secret-allowlist-policy.md` | Path/name-level secret triage policy. | Read-only reference unless secret policy task is scoped. |
| `assets/gpts/` | GPT instruction assets. | Edit only when task is GPT asset/instruction work. |
| `assets/screenshots/` | Documentation screenshots. | Treat as docs assets; update only when needed. |
| `bin/colameta` | Packaged executable helper. | Inspect before changing; validate CLI behavior. |
| `pyproject.toml` | Python package metadata, console script, optional test deps. | Changes can affect package/install/CI; run package smoke. |
| `.github/workflows/ci.yml` | CI test workflow. | CI changes require careful review. |
| `.github/workflows/publish.yml` | Tag-triggered PyPI publish workflow. | Release/publish surface; do not trigger or weaken without explicit authorization. |
| `.colameta/plan.json`, `.colameta/memory.md`, `.colameta/decisions.json`, `.colameta/todolist.json`, `.colameta/prompts/`, `.colameta/taskbooks/` | Tracked ColaMeta project memory and planning artifacts. | Editable only when task scope targets project memory/plans/prompts/taskbooks. |
| `.colameta/runtime/`, `.colameta/logs/`, `.colameta/reports/`, `.colameta/audits/`, `.colameta/plan-patches/`, `.colameta/tmp/`, `.colameta/local/`, `.colameta/executor-sessions/` | Local runtime state ignored by `.gitignore`. | Do not read contents unless a scoped diagnostic needs it and no secret/private-state boundary is crossed. Do not commit. |
| `.venv/`, `build/`, `dist/`, `*.egg-info/`, `.pytest_cache/`, `__pycache__/` | Local environment/build/cache outputs. | Do not commit; recreate as needed. |

This file is now the repository-root project protocol. During the initial fill,
no pre-existing repository-root `AGENTS.md` or `AGENTS.override.md` was found.

## 4. Setup And Local Commands

Allowed setup commands:

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[test]"
```

Use lockfile-respecting commands when lockfiles exist. No lockfile was found in
this repository during calibration. Do not run setup commands that require
secrets, production credentials, live provider routing, production databases,
irreversible external writes, or real-world notifications.

Common local CLI commands from repository evidence:

```bash
.venv/bin/colameta help
.venv/bin/colameta --version
.venv/bin/colameta status /home/jenn/src/colameta-dev
.venv/bin/colameta status /home/jenn/src/colameta-dev --json
```

Service commands are local-development only unless Jenn explicitly authorizes a
stable service operation:

```bash
.venv/bin/colameta start [managed|source-only] [project_path] [options]
.venv/bin/colameta serve <project_path> [options]
.venv/bin/colameta stop [project_path]
.venv/bin/colameta restart [project_path] [options]
```

Do not bind MCP/Web to external interfaces or pass real Web read tokens unless
Jenn explicitly scopes that operation. README documents that network-visible Web
requires `--web-host 0.0.0.0`, `--allow-external-web`, and
`--web-read-token <token>`; treat that as secret-adjacent and high risk.

Primary validation commands:

```bash
.venv/bin/python -m compileall adapters runner schemas scripts tests
.venv/bin/python -m pytest -q
.venv/bin/python scripts/self_hosting_smoke.py
git diff --check
```

Other safe targeted validation commands:

```bash
.venv/bin/python -m pytest tests/test_mcp_runtime_observability.py -q
.venv/bin/python -m pytest tests/test_web_console_security.py -q
.venv/bin/python scripts/agent_consumer_smoke.py --project-root /home/jenn/src/colameta-dev --project-name colameta-self-dev
```

Recommended validation ladder:

1. Smallest relevant targeted pytest module or test node.
2. Affected subsystem tests, such as MCP/Web/CLI/runtime tests.
3. `compileall` for touched Python packages.
4. `scripts/self_hosting_smoke.py` when packaging, CLI, imports, or startup are
   affected.
5. Full `.venv/bin/python -m pytest -q` when shared behavior, safety gates, MCP,
   Web Console, CLI, or release/package surfaces are touched.
6. `git diff --check` before commit.

Known slow or broad commands:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/self_hosting_smoke.py
.venv/bin/python -m pip install -e ".[test]"
```

Commands blocked unless Jenn explicitly authorizes:

```bash
git tag
git push --tags
git push --force
python -m build
python -m twine upload
gh release create
systemctl --user restart colameta-stable.service
systemctl --user stop colameta-stable.service
systemd-run --user --unit=colameta-stable.service ...
git -C /home/jenn/tools/colameta checkout <commit>
/home/jenn/tools/colameta/.venv/bin/python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
colameta start ... --web-host 0.0.0.0 ...
colameta serve ... --mcp-host 0.0.0.0 ...
```

The blocked list is not exhaustive; Jenn's global hard stops still apply.

## 5. Branch, Remote, And Delivery Policy

Current calibrated Git facts:

```text
current branch: main
remote origin fetch: git@github.com:JENN2046/colameta.git
remote origin push: git@github.com:JENN2046/colameta.git
```

Default task branch pattern:

```text
codex/<short-topic>
```

Protected or high-risk branches:

* `main`
* `master`
* `production`
* `release`
* Any branch used by Jenn as a stable or release branch.
* UNKNOWN — treat as blocked until verified: GitHub branch protection settings
  are not visible from local repository files.

Currently verified delivery remote:

```text
origin, verified locally as git@github.com:JENN2046/colameta.git; re-check git remote -v before every push.
```

Remote safety notes:

* A remote named `origin` is not automatically safe; inspect `git remote -v`
  before push.
* Do not push to `upstream`.
* Do not force push.
* Do not push tags.
* Do not push branches known to trigger release, deployment, production
  mutation, billing, paid external provider calls, customer-facing effects, or
  real-world notifications.
* Direct push to `main` triggers CI tests by repository workflow. It does not
  trigger publish by file evidence, but `main` is still a shared primary branch.
  Prefer a task branch and PR unless Jenn explicitly authorizes direct `main`
  delivery or the current task already established that route.
* Feature branch push to `origin` is lower risk by workflow evidence because
  `ci.yml` runs on PRs and on pushes to `main` only. Still avoid push if branch
  purpose, remote, or protection is unclear.

Normal delivery surfaces:

* local commit;
* safe task branch;
* existing PR or repository PR system;
* `PROJECT_MASTER_TASKBOOK.md`;
* `FREEZE_CANDIDATE_REVIEW_PACKET.md`;
* `docs/taskbooks/`;
* `docs/stable-replacement-receipts/` when stable replacement was explicitly
  authorized and completed;
* `docs/connector-tunnel-closeout-receipts/` when connector closeout receipt is
  explicitly in scope;
* tracked `.colameta/` planning files when current task targets ColaMeta project
  memory or plan state.

Do not create external trackers, cloud resources, SaaS records, customer-facing
posts, messages, or notifications unless Jenn explicitly authorizes them.

## 6. CI, Deployment, And Release Risk

CI behavior:

```text
.github/workflows/ci.yml runs on push to main and on pull_request.
It installs the package with test dependencies, compiles adapters/runner/schemas/scripts/tests,
runs pytest, runs scripts/self_hosting_smoke.py, and checks whitespace.
permissions: contents: read.
```

Deployment and publish triggers:

```text
.github/workflows/publish.yml runs on push tags matching v*.
It builds the package and publishes to PyPI using pypa/gh-action-pypi-publish with id-token: write.
No workflow_dispatch trigger was found during calibration.
No Dockerfile or production deployment workflow was found during calibration.
```

Release policy:

* Agents may not create or push tags.
* Agents may not publish packages.
* Agents may not deploy.
* Agents may not run production migrations.
* Agents may not modify release automation unless Jenn explicitly scopes the
  task and no hard stop is triggered.
* Any action that could trigger `publish.yml` is a hard stop without explicit
  current authorization.

If push or PR update may trigger deployment or publish, report `BLOCK` for that
delivery step.

## 7. Secrets And Private State Map

Secret-adjacent paths and patterns in or near this repository:

* `.env`
* `.env.*`
* `*.pem`
* `*.key`
* `*.p12`
* `*.pfx`
* `*.cookie`
* `*.cookies`
* `*.session`
* `*.token`
* `*.secret`
* `*.credentials`
* `*.sqlite`
* `*.sqlite3`
* `*.db`
* directories named `secrets/`, `credentials/`, `private/`, `tokens/`,
  `sessions/`, `localstate/`, `.localstate/`, or `state-private/`
* `.venv/`
* `.colameta/runtime/`
* `.colameta/logs/`
* `.colameta/reports/`
* `.colameta/audits/`
* `.colameta/plan-patches/`
* `.colameta/tmp/`
* `.colameta/local/`
* `.colameta/executor-session.json`
* `.colameta/executor-sessions/`
* `.colameta/settings.json`
* `.colameta/runner-settings.json`

Rules:

* Do not open or read secret/private-state contents.
* Do not print, summarize, validate, transform, commit, store, or transmit
  secret values.
* Agents may inspect file names, paths, git status, and whether
  secret-adjacent files are tracked.
* Use `.env.example`, config schemas, docs, mocks, or redacted error messages
  instead of real secret values.
* Source/test files with words like `token`, `auth`, `oauth`, `session`,
  `config`, `settings`, or `env` can be normal code, but allowlist status is
  not proof that contents are secret-free.

Secret scanning command:

```text
UNKNOWN — treat as blocked until verified.
```

Safe path/name-level triage reference:

```bash
find . -maxdepth 4 \( -name '.env' -o -name '.env.*' -o -iname '*secret*' -o -iname '*token*' -o -iname '*credential*' -o -iname '*.pem' -o -iname '*.key' -o -iname 'state-private' \) -print
```

Content-aware secret scanning or remediation requires a scoped task and redacted
reporting. Follow `docs/security/secret-allowlist-policy.md`.

## 8. Documentation And Project Memory

Documentation paths:

* `README.md`
* `README.zh-CN.md`
* `docs/USAGE.md`
* `docs/USAGE.zh-CN.md`
* `docs/ONBOARDING.md`
* `docs/ONBOARDING.zh-CN.md`
* `docs/web-gpt-service-entrypoint.zh-CN.md`
* `docs/runtime-loaded-code-verification.md`
* `docs/runtime-version-status-decision-contract.md`
* `docs/connector-runtime-health-observability.md`
* `docs/security/secret-allowlist-policy.md`
* `docs/taskbooks/`

Update docs when commands, APIs, configuration, tests, directory structure,
workflow, behavior, safety boundaries, or architecture change inside task scope.

Approved project memory paths:

* `PROJECT_MASTER_TASKBOOK.md`
* `PROJECT_MASTER_TASKBOOK.zh-CN.md`
* `FREEZE_CANDIDATE_REVIEW_PACKET.md`
* `FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md`
* `docs/taskbooks/`
* `docs/stable-replacement-receipts/`
* `docs/connector-tunnel-closeout-receipts/`
* `.colameta/plan.json`
* `.colameta/plan.zh-CN.md`
* `.colameta/memory.md`
* `.colameta/decisions.json`
* `.colameta/todolist.json`
* `.colameta/prompts/`
* `.colameta/taskbooks/`

Project memory should be durable, useful for future agents, evidence-grounded
or clearly marked as assumption, and safe to retain.

Do not write personal long-term user memory from project work unless Jenn
explicitly asks.

Do not write secrets, credentials, tokens, cookies, `.env` values, private keys,
verification codes, production credentials, ignored local runtime state,
low-value logs, short-lived noise, or unverified guesses as facts.

## 9. Read-Only / Audit-Only Behavior

When Jenn asks for read-only review, audit-only work, no file changes, or no
writes:

* inspect only non-sensitive repository reality;
* do not edit files;
* do not create generated artifacts;
* do not update docs, reports, task notes, issues, PRs, or memory;
* do not commit;
* do not push;
* report findings in the allowed response surface.

For "review" requests, default to code-review posture: findings first, ordered
by severity, with file/line evidence where possible. Do not fix unless Jenn
asks for fixes or implementation.

## 10. Testing And Validation Policy

For code changes, run the smallest relevant deterministic validation set first.

Change-type validation expectations:

| Change type | Required validation |
|---|---|
| Unit-level bugfix | Targeted pytest module/test plus related regression test. |
| MCP behavior change | Targeted MCP tests, relevant smoke packet tests, and full pytest when shared contracts change. |
| Web Console change | Web Console tests, security tests, and static HTML/JS review; browser/manual check when visual behavior matters. |
| CLI change | CLI tests, `scripts/self_hosting_smoke.py`, and command-specific dry-run/status checks. |
| Runtime observability/service change | Runtime observability tests, service status tests, and safe local health/smoke when applicable. |
| Git/commit/push/stable cadence change | Git safety tests, runtime observability tests, and explicit negative-path tests where practical. |
| Config/package metadata change | `compileall`, package install/build smoke, and CI-related tests. |
| Docs-only change | Static review, path/link sanity where possible, and `git diff --check`. |
| Memory/security/boundary change | Negative-path tests or dry-runs where practical; inspect against hard stops. |

If broad validation fails, fix failures caused by the current change or directly
related to the task. Treat failures as unrelated only with evidence.

Do not report `PASS` for a required validation gate that failed.

Safe markdown lint:

```text
UNKNOWN — treat as blocked until verified.
```

No repository markdown-lint command or markdown-lint dependency was found during
calibration. For docs-only work, run static review and `git diff --check`; run
additional safe checks only when discovered from repo evidence.

## 11. Incidental Findings

Handle incidental findings this way:

* hard-stop finding: report `BLOCK`;
* directly related to task or validation credibility: fix within smallest
  effective scope;
* unrelated but useful: record as a follow-up only in an approved project memory
  surface when allowed by the current task;
* unrelated architecture concern: do not fix during current task unless Jenn
  explicitly expands scope;
* secret or credible secret-like value: stop content handling, redact any
  mention, and ask Jenn for direction.

## 12. Subagents And Review

Use subagents when parallel work, independent review, or domain separation adds
clear value.

Suggested split for complex tasks:

* Commander: scope, risks, hard stops, decomposition.
* Worker A: implementation.
* Worker B: tests.
* Worker C: docs / project memory.
* Reviewer: safety, validation, scope, secret handling.
* Integrator: final consistency, validation, commit, safe push, PR update,
  report.

Subagent output is not final truth. The integrator remains responsible for final
delivery.

For this repository, reviewer agents should especially check:

* secret/private-state boundaries;
* MCP/Web read-only versus preview/apply/write boundaries;
* Git, commit, push, tag, publish, and stable replacement boundaries;
* `.colameta` tracked memory versus ignored local runtime state;
* test coverage for safety-gate changes.

## 13. Reporting Template

Every task must end with:

```text
Result:
Scope:
Changed files:
Validation:
Evidence:
Git delivery:
Delivery surface:
Memory:
Risks:
Incidental findings:
Next step:
```

Allowed result states: `PASS`, `PARTIAL`, `BLOCK`, `FAIL`, `FINDINGS_ONLY`,
`NO_CHANGES`.

For commit / push / PR / issue / task note / memory write, include enough detail
to audit the delivery.

For `BLOCK`, include blocked reason, hard stop, evidence, safe actions
completed, unsafe action not performed, and options for Jenn.

## 14. Project Fill-In Checklist

Current fill status:

* Project name: filled from README and `pyproject.toml`.
* Stack: filled from README, `pyproject.toml`, source layout, and workflow files.
* Editable source/test/docs paths: filled from repository tree.
* Package manager: filled from `pyproject.toml`; pip/setuptools.
* Setup commands: filled from `pyproject.toml` and README.
* Validation commands: filled from CI workflow and smoke scripts.
* Protected branches: `main` treated as high-risk shared branch; remote branch
  protection is `UNKNOWN — treat as blocked until verified.`
* Currently verified delivery remote: filled from `git remote -v`; agents must
  re-check before every push.
* CI behavior on feature branches: filled from `.github/workflows/ci.yml`.
* Deployment triggers: no deployment workflow found; network-visible local
  service flags are high risk.
* Release triggers: filled from `.github/workflows/publish.yml`; `v*` tags
  publish to PyPI.
* Secret-adjacent paths: filled from `.gitignore`, security policy, and safe
  path/name inspection.
* Docs paths: filled from repository docs.
* Project memory paths: filled from tracked taskbooks, receipts, and `.colameta`
  planning files.
* Blocked scripts/actions: filled from CI/publish/stable service risk evidence.
* Reporting conventions: filled from template and global protocol.

Unresolved:

* GitHub branch protection settings: UNKNOWN — treat as blocked until verified.
* Safe markdown lint command: UNKNOWN — treat as blocked until verified.
* Content-aware secret scanner command: UNKNOWN — treat as blocked until
  verified.

## 15. Local Calibration Evidence

This fill was based on safe inspection of:

* `README.md`
* `pyproject.toml`
* `.gitignore`
* `.github/workflows/ci.yml`
* `.github/workflows/publish.yml`
* `docs/USAGE.md`
* `docs/USAGE.zh-CN.md`
* `docs/security/secret-allowlist-policy.md`
* source/test/docs/scripts directory listings
* `git status`
* `git branch --show-current`
* `git remote -v`

Sensitive files, `.env` contents, credentials, tokens, cookies, browser login
state, private keys, and ignored local runtime state contents were not read.
