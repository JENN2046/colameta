from __future__ import annotations

import ast
from dataclasses import dataclass
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
            # These are the only domain modules allowed to hold the sealed
            # repository capabilities.  Pilot authorization owns the durable
            # issuance/claim facts; it is part of the bounded authority model,
            # not a transport-side escape hatch.
            if relative not in {
                "runner/work_item_governance/activation.py",
                "runner/work_item_governance/pilot.py",
                "runner/work_item_governance/pilot_authorization.py",
            }:
                for boundary_call in (
                    "authorize_activation_domain_write",
                    "finalize_activation_domain_write",
                    "authorize_activation_control_write",
                    "finalize_activation_control_write",
                    "_bind_activation_controller",
                ):
                    if _calls_name(path, boundary_call):
                        violations.append(
                            {
                                "rule": "activation_repository_unlock_bypass",
                                "path": relative,
                                "import": boundary_call,
                            }
                        )
            if relative != "runner/work_item_governance/repository.py" and _calls_name(
                path,
                "_connect",
            ):
                violations.append(
                    {
                        "rule": "activation_repository_raw_connection_bypass",
                        "path": relative,
                        "import": "_connect",
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
        service_methods = _class_method_analyses(
            service_path,
            class_name="WorkItemApplicationService",
        )
        for method, analysis in service_methods.items():
            raw_transactions = [
                call
                for call in analysis.calls
                if call.path[-1:] == ("write_transaction",)
                and call.path != ("self", "_write_transaction")
            ]
            if method != "_write_transaction" and raw_transactions:
                violations.append(
                    {
                        "rule": "application_write_bypasses_composition_guard",
                        "path": str(service_path.relative_to(root)),
                        "import": method,
                    }
                )
            transactions = analysis.transactions
            if method == "_write_transaction" or not transactions:
                continue
            if method in LEASE_CONTROLLED_WRITE_METHODS or method == "_apply_create":
                boundary_valid = _every_transaction_begins_with_exact_call(
                    transactions,
                    analysis.calls,
                    ("self", "_activation_begin"),
                )
            elif method in LEASE_DENIED_WRITE_METHODS:
                boundary_valid = _exact_call_precedes_every_transaction(
                    transactions,
                    analysis.calls,
                    ("self", "_deny_activation_command"),
                )
            elif method == "_deny_activation_command":
                boundary_valid = _every_transaction_begins_with_exact_call(
                    transactions,
                    analysis.calls,
                    ("self", "activation_guard", "deny_command"),
                )
            else:
                boundary_valid = _exact_call_precedes_every_transaction(
                    transactions,
                    analysis.calls,
                    ("self", "_assert_internal_activation_write_denied"),
                )
            if not boundary_valid:
                violations.append(
                    {
                        "rule": "application_write_transaction_unclassified",
                        "path": str(service_path.relative_to(root)),
                        "import": method,
                    }
                )
        for method in LEASE_CONTROLLED_WRITE_METHODS:
            analysis = service_methods.get(method)
            required_call = (
                ("self", "_apply_create")
                if method == "apply_work_item_create"
                else ("self", "_activation_begin")
            )
            if analysis is None or not analysis.has_exact_call(required_call):
                violations.append(
                    {
                        "rule": "activation_lease_write_path_missing",
                        "path": str(service_path.relative_to(root)),
                        "import": method,
                    }
                )
        apply_create = service_methods.get("_apply_create")
        if apply_create is None or not _every_transaction_begins_with_exact_call(
            apply_create.transactions,
            apply_create.calls,
            ("self", "_activation_begin"),
        ):
            violations.append(
                {
                    "rule": "activation_lease_create_transaction_missing",
                    "path": str(service_path.relative_to(root)),
                    "import": "_apply_create",
                }
            )
        if apply_create is None or not _exact_call_precedes_every_transaction(
            apply_create.transactions,
            apply_create.calls,
            ("self", "_assert_internal_activation_write_denied"),
        ):
            violations.append(
                {
                    "rule": "activation_legacy_create_boundary_missing",
                    "path": str(service_path.relative_to(root)),
                    "import": "_apply_create",
                }
            )
        for normalizer in ("_normalize_create_command", "_normalize_legacy_import_command"):
            if apply_create is None or not apply_create.has_exact_call(("self", normalizer)):
                violations.append(
                    {
                        "rule": "activation_create_operation_validation_missing",
                        "path": str(service_path.relative_to(root)),
                        "import": normalizer,
                    }
                )
        for method in LEASE_DENIED_WRITE_METHODS:
            analysis = service_methods.get(method)
            if analysis is None or not analysis.has_exact_call(("self", "_deny_activation_command")):
                violations.append(
                    {
                        "rule": "activation_denied_write_path_missing",
                        "path": str(service_path.relative_to(root)),
                        "import": method,
                    }
                )
    activation_path = core_root / "activation.py"
    if activation_path.is_file():
        guard_methods = _class_method_analyses(
            activation_path,
            class_name="AuthoritativeCanaryGuard",
        )
        begin_write = guard_methods.get("begin_write")
        if begin_write is None or not begin_write.has_exact_call(
            ("self", "ledger", "authorize_activation_domain_write")
        ):
            violations.append(
                {
                    "rule": "activation_repository_unlock_missing",
                    "path": str(activation_path.relative_to(root)),
                    "import": "begin_write",
                }
            )
        for method in ("_authorize_replay", "_commit_new"):
            analysis = guard_methods.get(method)
            if analysis is None or not analysis.has_exact_call(
                ("self", "ledger", "finalize_activation_domain_write")
            ):
                violations.append(
                    {
                        "rule": "activation_repository_relock_missing",
                        "path": str(activation_path.relative_to(root)),
                        "import": method,
                    }
                )
        for method in ("begin_write", "deny_command"):
            analysis = guard_methods.get(method)
            if analysis is None or not _ordered_exact_calls(
                analysis,
                ("self", "ledger", "authorize_activation_control_write"),
                ("self", "ledger", "finalize_activation_control_write"),
            ):
                violations.append(
                    {
                        "rule": "activation_control_write_boundary_missing",
                        "path": str(activation_path.relative_to(root)),
                        "import": method,
                    }
                )
        control_plane_methods = _class_method_nodes(
            activation_path,
            class_name="ActivationLeaseControlPlane",
        )
        for method in (
            "issue_prepared_lease",
            "claim_prepared_lease",
            "attest_listener",
            "freeze",
            "close",
            "revoke",
        ):
            if not _control_plane_method_has_guarded_transaction(
                control_plane_methods.get(method)
            ):
                violations.append(
                    {
                        "rule": "activation_control_write_boundary_missing",
                        "path": str(activation_path.relative_to(root)),
                        "import": method,
                    }
                )
    pilot_path = core_root / "pilot.py"
    if pilot_path.is_file():
        pilot_guard_methods = _class_method_analyses(
            pilot_path,
            class_name="PilotActivationGuard",
        )
        begin_write = pilot_guard_methods.get("begin_write")
        if begin_write is None or not begin_write.has_exact_call(
            ("self", "ledger", "authorize_activation_domain_write")
        ):
            violations.append(
                {
                    "rule": "pilot_repository_unlock_missing",
                    "path": str(pilot_path.relative_to(root)),
                    "import": "begin_write",
                }
            )
        for method in ("_authorize_replay", "_commit_new_checked"):
            analysis = pilot_guard_methods.get(method)
            if analysis is None or not analysis.has_exact_call(
                ("self", "ledger", "finalize_activation_domain_write")
            ):
                violations.append(
                    {
                        "rule": "pilot_repository_relock_missing",
                        "path": str(pilot_path.relative_to(root)),
                        "import": method,
                    }
                )
        for method in ("begin_write", "deny_command"):
            analysis = pilot_guard_methods.get(method)
            if analysis is None or not _ordered_exact_calls(
                analysis,
                ("self", "ledger", "authorize_activation_control_write"),
                ("self", "ledger", "finalize_activation_control_write"),
            ):
                violations.append(
                    {
                        "rule": "pilot_control_write_boundary_missing",
                        "path": str(pilot_path.relative_to(root)),
                        "import": method,
                    }
                )
        pilot_control_methods = _class_method_analyses(
            pilot_path,
            class_name="PilotActivationControlPlane",
        )
        for method in (
            "prepare_lease",
            "_transition_runtime",
            "revoke",
            "freeze",
            "_terminal_transition",
        ):
            analysis = pilot_control_methods.get(method)
            if analysis is None or not _ordered_exact_calls(
                analysis,
                ("self", "ledger", "authorize_activation_control_write"),
                ("self", "ledger", "finalize_activation_control_write"),
            ):
                violations.append(
                    {
                        "rule": "pilot_control_write_boundary_missing",
                        "path": str(pilot_path.relative_to(root)),
                        "import": method,
                    }
                )
        if "transition_runtime" in pilot_control_methods:
            violations.append(
                {
                    "rule": "pilot_runtime_transition_public_bypass",
                    "path": str(pilot_path.relative_to(root)),
                    "import": "transition_runtime",
                }
            )
    pilot_authorization_path = core_root / "pilot_authorization.py"
    if pilot_authorization_path.is_file():
        consumer_methods = _class_method_analyses(
            pilot_authorization_path,
            class_name="PilotAuthorizationDecisionConsumer",
        )
        authorize = consumer_methods.get("_authorize_control_write")
        finalize = consumer_methods.get("_finalize_control_write")
        consume = consumer_methods.get("consume")
        if authorize is None or not authorize.has_exact_call(
            ("self", "ledger", "authorize_activation_control_write")
        ):
            violations.append(
                {
                    "rule": "pilot_authorization_repository_unlock_missing",
                    "path": str(pilot_authorization_path.relative_to(root)),
                    "import": "_authorize_control_write",
                }
            )
        if finalize is None or not finalize.has_exact_call(
            ("self", "ledger", "finalize_activation_control_write")
        ):
            violations.append(
                {
                    "rule": "pilot_authorization_repository_relock_missing",
                    "path": str(pilot_authorization_path.relative_to(root)),
                    "import": "_finalize_control_write",
                }
            )
        if consume is None or not _ordered_exact_calls(
            consume,
            ("self", "_authorize_control_write"),
            ("self", "_finalize_control_write"),
        ):
            violations.append(
                {
                    "rule": "pilot_authorization_issuance_transaction_missing",
                    "path": str(pilot_authorization_path.relative_to(root)),
                    "import": "consume",
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


@dataclass(frozen=True)
class _CallSite:
    path: tuple[str, ...]
    lineno: int
    col_offset: int
    transaction_stack: tuple[int, ...]
    context_manager: bool

    @property
    def position(self) -> tuple[int, int]:
        return self.lineno, self.col_offset


@dataclass(frozen=True)
class _TransactionSite:
    identity: int
    lineno: int
    col_offset: int

    @property
    def position(self) -> tuple[int, int]:
        return self.lineno, self.col_offset


@dataclass(frozen=True)
class _MethodAnalysis:
    calls: tuple[_CallSite, ...]
    transactions: tuple[_TransactionSite, ...]

    def exact_calls(self, path: tuple[str, ...]) -> tuple[_CallSite, ...]:
        return tuple(call for call in self.calls if call.path == path)

    def has_exact_call(self, path: tuple[str, ...]) -> bool:
        return bool(self.exact_calls(path))


class _ExecutableCallScanner(ast.NodeVisitor):
    """Collect live call sites without accepting nested/dead-code spoofs.

    This is deliberately a small control-flow-aware scanner rather than an
    ``ast.walk`` query.  A nested function or lambda is not executed by the
    containing Application Service method, and a statically false branch
    cannot provide its write boundary.  Each ``self._write_transaction()``
    context receives an identity so a boundary in another transaction cannot
    satisfy the one being classified.
    """

    def __init__(
        self,
        *,
        transaction_path: tuple[str, ...] = ("self", "_write_transaction"),
    ) -> None:
        self.calls: list[_CallSite] = []
        self.transactions: list[_TransactionSite] = []
        self._transaction_path = transaction_path
        self._transaction_stack: list[int] = []
        self._context_manager = False
        self._next_transaction_identity = 1

    def scan(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> _MethodAnalysis:
        self._visit_statements(node.body)
        return _MethodAnalysis(tuple(self.calls), tuple(self.transactions))

    def _visit_statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self.visit(statement)
            if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                break

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        return

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        path = _call_path(node.func)
        if path is not None:
            self.calls.append(
                _CallSite(
                    path=path,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    transaction_stack=tuple(self._transaction_stack),
                    context_manager=self._context_manager,
                )
            )
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        self.visit(node.test)
        truth = _static_truth(node.test)
        if truth is True:
            self._visit_statements(node.body)
        elif truth is False:
            self._visit_statements(node.orelse)
        else:
            self._visit_statements(node.body)
            self._visit_statements(node.orelse)

    def visit_IfExp(self, node: ast.IfExp) -> None:  # noqa: N802
        self.visit(node.test)
        truth = _static_truth(node.test)
        if truth is True:
            self.visit(node.body)
        elif truth is False:
            self.visit(node.orelse)
        else:
            self.visit(node.body)
            self.visit(node.orelse)

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        self.visit(node.test)
        truth = _static_truth(node.test)
        if truth is not False:
            self._visit_statements(node.body)
        self._visit_statements(node.orelse)

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self.visit(node.iter)
        self._visit_statements(node.body)
        self._visit_statements(node.orelse)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
        self.visit(node.iter)
        self._visit_statements(node.body)
        self._visit_statements(node.orelse)

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
        self._visit_statements(node.body)
        for handler in node.handlers:
            if handler.type is not None:
                self.visit(handler.type)
            self._visit_statements(handler.body)
        self._visit_statements(node.orelse)
        self._visit_statements(node.finalbody)

    def visit_TryStar(self, node: ast.TryStar) -> None:  # noqa: N802
        self.visit_Try(node)

    def visit_With(self, node: ast.With) -> None:  # noqa: N802
        self._visit_with(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802
        self._visit_with(node)

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        transaction_identity: int | None = None
        for item in node.items:
            previous = self._context_manager
            self._context_manager = True
            try:
                self.visit(item.context_expr)
            finally:
                self._context_manager = previous
            if _is_exact_call(item.context_expr, self._transaction_path):
                if transaction_identity is None:
                    transaction_identity = self._next_transaction_identity
                    self._next_transaction_identity += 1
                    self.transactions.append(
                        _TransactionSite(
                            identity=transaction_identity,
                            lineno=item.context_expr.lineno,
                            col_offset=item.context_expr.col_offset,
                        )
                    )
        if transaction_identity is not None:
            self._transaction_stack.append(transaction_identity)
        try:
            self._visit_statements(node.body)
        finally:
            if transaction_identity is not None:
                self._transaction_stack.pop()


def _static_truth(node: ast.AST) -> bool | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            operand = _static_truth(node.operand)
            return None if operand is None else not operand
        return None
    return bool(value)


def _call_path(node: ast.AST) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        prefix = _call_path(node.value)
        if prefix is not None:
            return (*prefix, node.attr)
    return None


def _is_exact_call(node: ast.AST, path: tuple[str, ...]) -> bool:
    return isinstance(node, ast.Call) and _call_path(node.func) == path


def _class_method_nodes(
    path: Path,
    *,
    class_name: str,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                child.name: child
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return {}


def _class_method_analyses(path: Path, *, class_name: str) -> dict[str, _MethodAnalysis]:
    return {
        name: _ExecutableCallScanner().scan(node)
        for name, node in _class_method_nodes(path, class_name=class_name).items()
    }


def _every_transaction_begins_with_exact_call(
    transactions: tuple[_TransactionSite, ...],
    calls: tuple[_CallSite, ...],
    path: tuple[str, ...],
) -> bool:
    if not transactions:
        return False
    for transaction in transactions:
        transaction_calls = sorted(
            (
                call
                for call in calls
                if transaction.identity in call.transaction_stack
            ),
            key=lambda call: call.position,
        )
        if not transaction_calls or transaction_calls[0].path != path:
            return False
    return True


def _exact_call_precedes_every_transaction(
    transactions: tuple[_TransactionSite, ...],
    calls: tuple[_CallSite, ...],
    path: tuple[str, ...],
) -> bool:
    return bool(transactions) and all(
        any(
            call.path == path
            and not call.transaction_stack
            and call.position < transaction.position
            for call in calls
        )
        for transaction in transactions
    )


def _ordered_exact_calls(
    analysis: _MethodAnalysis,
    first: tuple[str, ...],
    second: tuple[str, ...],
) -> bool:
    return any(
        earlier.position < later.position
        for earlier in analysis.exact_calls(first)
        for later in analysis.exact_calls(second)
    )


def _control_plane_method_has_guarded_transaction(
    method: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> bool:
    if method is None:
        return False
    helper = next(
        (
            statement
            for statement in method.body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and statement.name == "control_transaction"
        ),
        None,
    )
    if helper is None:
        return False
    outer = _ExecutableCallScanner().scan(method)
    if not any(
        call.path == ("control_transaction",) and call.context_manager
        for call in outer.calls
    ):
        return False
    guarded = _ExecutableCallScanner(
        transaction_path=("self", "ledger", "write_transaction"),
    ).scan(helper)
    authorize_path = ("self", "ledger", "authorize_activation_control_write")
    finalize_path = ("self", "ledger", "finalize_activation_control_write")
    if not _every_transaction_begins_with_exact_call(
        guarded.transactions,
        guarded.calls,
        authorize_path,
    ):
        return False
    return all(
        any(
            transaction.identity in authorize.transaction_stack
            and transaction.identity in finalize.transaction_stack
            and authorize.position < finalize.position
            for authorize in guarded.exact_calls(authorize_path)
            for finalize in guarded.exact_calls(finalize_path)
        )
        for transaction in guarded.transactions
    )


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
