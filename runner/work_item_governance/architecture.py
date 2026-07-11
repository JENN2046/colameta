from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Iterable


CORE_FORBIDDEN_IMPORT_PREFIXES = (
    "adapters",
    "runner.cloud_agent_client",
    "runner.codex_executor",
    "runner.mcp_",
    "runner.mcp_server",
    "runner.mcp_external_oauth",
    "runner.mcp_oauth",
    "runner.opencode_executor",
    "runner.pi_executor",
    "runner.product_",
    "runner.production_ops",
    "runner.release_submission_readiness",
    "runner.stable_promotion",
    "runner.web_console",
)

SIDE_CONTEXT_MANIFEST: dict[str, tuple[str, ...]] = {
    "commander": ("commander_decision_request.py", "commander_projections.py"),
    "service_operations": (
        "mcp_external_oauth.py",
        "mcp_oauth.py",
        "production_ops.py",
        "runtime_observability.py",
        "service_lifecycle_store.py",
    ),
    "app_productization": (
        "app_submission_work_items.py",
        "product_console.py",
        "product_readiness.py",
        "release_submission_readiness.py",
    ),
    "stable_promotion": (
        "stable_promotion_evidence.py",
        "stable_promotion_readiness.py",
        "stable_promotion_work_item.py",
    ),
}

SIDE_CONTEXT_DISCOVERY_PATTERNS = (
    "*connector*.py",
    "*tunnel*.py",
    "*oauth*.py",
    "app_submission*.py",
    "commander_*.py",
    "product_*.py",
    "production_ops*.py",
    "release_submission*.py",
    "runtime_observability*.py",
    "service_lifecycle*.py",
    "stable_promotion*.py",
)

SIDE_CONTEXT_FORBIDDEN_IMPORT_PREFIXES = (
    "runner.work_item_governance.repository",
    "runner.work_item_governance.service",
)
WORK_ITEM_CORE_PACKAGE = "runner.work_item_governance"


def check_work_item_architecture(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    violations: list[dict[str, str]] = []
    core_root = root / "runner" / "work_item_governance"
    for path in sorted(core_root.rglob("*.py")):
        for imported in _imports(path):
            if imported.startswith(CORE_FORBIDDEN_IMPORT_PREFIXES):
                violations.append(
                    {"rule": "core_forbidden_dependency", "path": str(path.relative_to(root)), "import": imported}
                )

    side_context_paths = list(_side_context_files(root / "runner"))
    for path in side_context_paths:
        for imported in _imports(path):
            if (
                imported == WORK_ITEM_CORE_PACKAGE
                or imported.startswith(SIDE_CONTEXT_FORBIDDEN_IMPORT_PREFIXES)
            ):
                violations.append(
                    {"rule": "side_context_repository_dependency", "path": str(path.relative_to(root)), "import": imported}
                )
                break
        try:
            source = path.read_text(encoding="utf-8").lower()
        except OSError:
            source = ""
        for marker in (".colameta/ledger", "work-items.sqlite3", "insert into work_items", "update work_items"):
            if marker in source:
                violations.append(
                    {"rule": "side_context_direct_ledger_access", "path": str(path.relative_to(root)), "import": marker}
                )

    for path in (
        root / "runner" / "mcp_server.py",
        root / "runner" / "web_console.py",
        root / "scripts" / "runner_cli.py",
    ):
        if not path.is_file():
            continue
        for imported in _imports(path):
            if (
                imported == WORK_ITEM_CORE_PACKAGE
                or imported.startswith(SIDE_CONTEXT_FORBIDDEN_IMPORT_PREFIXES)
            ):
                violations.append(
                    {"rule": "transport_bypasses_application_command", "path": str(path.relative_to(root)), "import": imported}
                )
    return {
        "ok": not violations,
        "schema_version": "work_item_architecture_check.v1",
        "violations": violations,
        "checked_core_files": len(list(core_root.rglob("*.py"))),
        "checked_side_context_files": len(side_context_paths),
    }


def _side_context_files(runner_root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    explicit_names = sorted({name for names in SIDE_CONTEXT_MANIFEST.values() for name in names})
    for name in explicit_names:
        path = runner_root / name
        if path.is_file() and path not in seen:
            seen.add(path)
            yield path
    for pattern in SIDE_CONTEXT_DISCOVERY_PATTERNS:
        for path in runner_root.glob(pattern):
            if path not in seen:
                seen.add(path)
                yield path


def _imports(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
            imports.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return imports
