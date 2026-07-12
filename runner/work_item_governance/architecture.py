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
DIRECT_WRITE_BOUNDARY_IMPORT_PREFIXES = SIDE_CONTEXT_FORBIDDEN_IMPORT_PREFIXES
DIRECT_WRITE_BOUNDARY_REEXPORTS = frozenset(
    {
        "SQLiteWorkItemLedger",
        "WorkItemApplicationService",
    }
)
DIRECT_WRITE_BOUNDARY_ALLOWED_PATHS = frozenset(
    {
        "runner/work_item_canary_runtime.py",
        "runner/work_item_commands.py",
    }
)
WORK_ITEM_CORE_PACKAGE = "runner.work_item_governance"
LEASE_CONTROLLED_WRITE_METHODS = (
    "apply_work_item_create",
    "add_task_version",
    "create_execution_attempt",
    "complete_execution_attempt",
    "register_artifact_reference",
    "record_review_decision",
    "apply_work_item_transition",
)
LEASE_DENIED_WRITE_METHODS = (
    "apply_legacy_work_item_import",
    "bind_historical_execution_attempt",
    "apply_blocker",
    "clear_blocker",
    "create_delivery_receipt",
    "retry_delivery",
    "acknowledge_delivery",
    "record_outbox_delivery_result",
    "recover_outbox_event",
)


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

    checked_write_boundary_files = 0
    side_context_path_set = set(side_context_paths)
    for source_root_name in ("runner", "scripts", "adapters"):
        source_root = root / source_root_name
        if not source_root.is_dir():
            continue
        for path in sorted(source_root.rglob("*.py")):
            checked_write_boundary_files += 1
            relative = path.relative_to(root).as_posix()
            if relative != "runner/work_item_governance/activation.py":
                for boundary_call in (
                    "authorize_activation_domain_write",
                    "finalize_activation_domain_write",
                ):
                    if _calls_name(path, boundary_call):
                        violations.append(
                            {
                                "rule": "activation_repository_unlock_bypass",
                                "path": relative,
                                "import": boundary_call,
                            }
                        )
            if (
                path.is_relative_to(core_root)
                or path in side_context_path_set
                or relative in DIRECT_WRITE_BOUNDARY_ALLOWED_PATHS
            ):
                continue
            imported = _direct_write_boundary_import(path)
            if imported is not None:
                violations.append(
                    {
                        "rule": "direct_work_item_write_boundary_import",
                        "path": relative,
                        "import": imported,
                    }
                )
    service_path = core_root / "service.py"
    if service_path.is_file():
        service_calls = _method_calls(service_path)
        for method, calls in service_calls.items():
            if method != "_write_transaction" and "write_transaction" in calls:
                violations.append(
                    {
                        "rule": "application_write_bypasses_composition_guard",
                        "path": str(service_path.relative_to(root)),
                        "import": method,
                    }
                )
            if method == "_write_transaction" or "_write_transaction" not in calls:
                continue
            if method in LEASE_CONTROLLED_WRITE_METHODS or method == "_apply_create":
                required_boundary = "_activation_begin"
            elif method in LEASE_DENIED_WRITE_METHODS:
                required_boundary = "_deny_activation_command"
            elif method == "_deny_activation_command":
                required_boundary = "deny_command"
            else:
                required_boundary = "_assert_internal_activation_write_denied"
            if required_boundary not in calls:
                violations.append(
                    {
                        "rule": "application_write_transaction_unclassified",
                        "path": str(service_path.relative_to(root)),
                        "import": method,
                    }
                )
        for method in LEASE_CONTROLLED_WRITE_METHODS:
            required_call = "_apply_create" if method == "apply_work_item_create" else "_activation_begin"
            if required_call not in service_calls.get(method, set()):
                violations.append(
                    {
                        "rule": "activation_lease_write_path_missing",
                        "path": str(service_path.relative_to(root)),
                        "import": method,
                    }
                )
        if "_activation_begin" not in service_calls.get("_apply_create", set()):
            violations.append(
                {
                    "rule": "activation_lease_create_transaction_missing",
                    "path": str(service_path.relative_to(root)),
                    "import": "_apply_create",
                }
            )
        for method in LEASE_DENIED_WRITE_METHODS:
            if "_deny_activation_command" not in service_calls.get(method, set()):
                violations.append(
                    {
                        "rule": "activation_denied_write_path_missing",
                        "path": str(service_path.relative_to(root)),
                        "import": method,
                    }
                )
    activation_path = core_root / "activation.py"
    if activation_path.is_file():
        activation_calls = _method_calls(activation_path)
        if "authorize_activation_domain_write" not in activation_calls.get("begin_write", set()):
            violations.append(
                {
                    "rule": "activation_repository_unlock_missing",
                    "path": str(activation_path.relative_to(root)),
                    "import": "begin_write",
                }
            )
        for method in ("_authorize_replay", "_commit_new"):
            if "finalize_activation_domain_write" not in activation_calls.get(method, set()):
                violations.append(
                    {
                        "rule": "activation_repository_relock_missing",
                        "path": str(activation_path.relative_to(root)),
                        "import": method,
                    }
                )
    return {
        "ok": not violations,
        "schema_version": "work_item_architecture_check.v1",
        "violations": violations,
        "checked_core_files": len(list(core_root.rglob("*.py"))),
        "checked_side_context_files": len(side_context_paths),
        "checked_write_boundary_files": checked_write_boundary_files,
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


def _direct_write_boundary_import(path: Path) -> str | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == WORK_ITEM_CORE_PACKAGE or alias.name.startswith(
                    DIRECT_WRITE_BOUNDARY_IMPORT_PREFIXES
                ):
                    return alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(DIRECT_WRITE_BOUNDARY_IMPORT_PREFIXES):
                return node.module
            if node.module == WORK_ITEM_CORE_PACKAGE:
                for alias in node.names:
                    if alias.name in DIRECT_WRITE_BOUNDARY_REEXPORTS or alias.name == "*":
                        return f"{node.module}.{alias.name}"
    return None


def _method_calls(path: Path) -> dict[str, set[str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return {}
    result: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute):
                    calls.add(child.func.attr)
                elif isinstance(child.func, ast.Name):
                    calls.add(child.func.id)
        result[node.name] = calls
    return result


def _calls_name(path: Path, name: str) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return False
    return any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == name)
            or (isinstance(node.func, ast.Name) and node.func.id == name)
        )
        for node in ast.walk(tree)
    )
