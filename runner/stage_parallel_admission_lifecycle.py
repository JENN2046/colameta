from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Any

from runner.fresh_executor_authority import (
    create_or_resolve_stage_shard_fresh_executor_authority,
    inspect_stage_shard_fresh_executor_authority,
)
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.project_operation_lease import ProjectOperationLease
from runner.work_item_governance.canonical import canonical_sha256
from runner.work_item_governance.errors import WorkItemGovernanceError


PROGRESS_SCHEMA_VERSION = "stage_parallel_admission_progress.v1"
PROGRESS_RELATIVE_PARTS = (".colameta", "runtime", "stage-parallel-admissions")
PROGRESS_FILENAME = "progress.json"
MAX_PROGRESS_BYTES = 2 * 1024 * 1024
STATES = (
    "PLANNED",
    "B0_ALL_TASK_GRANTS_VALID",
    "B1_ALL_ATTEMPTS_ADMITTED",
    "B2_ALL_GOVERNED_TARGETS_COMPLETE",
    "B3_ALL_SHARD_CONTEXTS_BOUND",
    "B4_ALL_FRESH_AUTHORITIES_READY",
    "B5_ALL_EXECUTOR_PREVIEWS_READY",
    "PREPARED_FOR_EXECUTION",
)


class StageAdmissionLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trusted_directory(value: os.stat_result) -> bool:
    return bool(
        stat.S_ISDIR(value.st_mode)
        and value.st_uid == os.geteuid()
        and value.st_nlink >= 1
        and stat.S_IMODE(value.st_mode) & 0o022 == 0
    )


def _trusted_file(value: os.stat_result) -> bool:
    return bool(
        stat.S_ISREG(value.st_mode)
        and value.st_uid == os.geteuid()
        and value.st_nlink == 1
        and stat.S_IMODE(value.st_mode) & 0o077 == 0
        and 0 <= value.st_size <= MAX_PROGRESS_BYTES
    )


class StageAdmissionProgressStore:
    """FD-anchored monotonic recovery evidence; never an authority source."""

    def __init__(self, project_root: str, parallel_group_id: str) -> None:
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.parallel_group_id = str(parallel_group_id)
        self.group_key = hashlib.sha256(self.parallel_group_id.encode("utf-8")).hexdigest()

    def _open(self, *, create: bool) -> dict[str, Any]:
        fds: list[int] = []
        links: list[tuple[int | None, str, int, int]] = []
        try:
            project_fd = os.open(
                self.project_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            fds.append(project_fd)
            parent_fd = project_fd
            root_stat = os.fstat(project_fd)
            if not _trusted_directory(root_stat):
                raise OSError(errno.EPERM, "unsafe project root")
            links.append((None, self.project_root, root_stat.st_dev, root_stat.st_ino))
            for component in (*PROGRESS_RELATIVE_PARTS, self.group_key):
                try:
                    child_fd = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=parent_fd,
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(component, mode=0o700, dir_fd=parent_fd)
                    os.fsync(parent_fd)
                    child_fd = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=parent_fd,
                    )
                fds.append(child_fd)
                child_stat = os.fstat(child_fd)
                if not _trusted_directory(child_stat):
                    raise OSError(errno.EPERM, "unsafe progress ancestor")
                links.append((parent_fd, component, child_stat.st_dev, child_stat.st_ino))
                parent_fd = child_fd
            return {"fds": fds, "links": links, "directory_fd": parent_fd}
        except OSError as exc:
            for fd in reversed(fds):
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise StageAdmissionLifecycleError(
                "STAGE_ADMISSION_PROGRESS_PATH_UNSAFE",
                f"{type(exc).__name__}:{exc.errno}",
            ) from exc

    @staticmethod
    def _close(state: dict[str, Any]) -> None:
        for fd in reversed(state.get("fds", [])):
            try:
                os.close(fd)
            except OSError:
                pass

    @staticmethod
    def _stable(state: dict[str, Any]) -> bool:
        try:
            for parent_fd, name, device, inode in state["links"]:
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if (
                    not _trusted_directory(current)
                    or (current.st_dev, current.st_ino) != (device, inode)
                ):
                    return False
            return True
        except OSError:
            return False

    def read(self) -> dict[str, Any] | None:
        try:
            state = self._open(create=False)
        except StageAdmissionLifecycleError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                return None
            raise
        fd = -1
        try:
            if not self._stable(state):
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
            try:
                fd = os.open(
                    PROGRESS_FILENAME,
                    os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=state["directory_fd"],
                )
            except FileNotFoundError:
                return None
            before = os.fstat(fd)
            if not _trusted_file(before):
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
            raw = b""
            while len(raw) < before.st_size:
                chunk = os.read(fd, before.st_size - len(raw))
                if not chunk:
                    raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
                raw += chunk
            after = os.fstat(fd)
            current = os.stat(
                PROGRESS_FILENAME,
                dir_fd=state["directory_fd"],
                follow_symlinks=False,
            )
            identity_fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
            if (
                any(getattr(before, key) != getattr(after, key) for key in identity_fields)
                or any(getattr(before, key) != getattr(current, key) for key in identity_fields)
                or not self._stable(state)
            ):
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH") from exc
            if not isinstance(value, dict):
                raise StageAdmissionLifecycleError(
                    "STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH"
                )
            return value
        finally:
            if fd >= 0:
                os.close(fd)
            self._close(state)

    def write(self, record: dict[str, Any], *, prior: dict[str, Any] | None) -> None:
        self._validate_monotonic(record, prior=prior)
        payload = (
            json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        if len(payload) > MAX_PROGRESS_BYTES:
            raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_TOO_LARGE")
        state = self._open(create=True)
        temporary = f".{PROGRESS_FILENAME}.{uuid.uuid4().hex}.tmp"
        fd = -1
        try:
            if not self._stable(state):
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=state["directory_fd"],
            )
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
            os.close(fd)
            fd = -1
            if not self._stable(state):
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
            os.replace(
                temporary,
                PROGRESS_FILENAME,
                src_dir_fd=state["directory_fd"],
                dst_dir_fd=state["directory_fd"],
            )
            os.fsync(state["directory_fd"])
            current = os.stat(PROGRESS_FILENAME, dir_fd=state["directory_fd"], follow_symlinks=False)
            if not _trusted_file(current) or not self._stable(state):
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.unlink(temporary, dir_fd=state["directory_fd"])
            except OSError:
                pass
            self._close(state)

    def _validate_monotonic(
        self, record: dict[str, Any], *, prior: dict[str, Any] | None
    ) -> None:
        if record.get("schema_version") != PROGRESS_SCHEMA_VERSION:
            raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
        state = record.get("state")
        if state not in STATES:
            raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
        if prior is None:
            if state != "PLANNED":
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
            return
        for key in (
            "schema_version", "stage_id", "parallel_group_id",
            "stage_planning_preview_sha256", "project_identity", "base_head",
            "runner_plan_sha256", "repository", "task_order", "spec_sha256",
        ):
            if record.get(key) != prior.get(key):
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
        if STATES.index(str(state)) < STATES.index(str(prior.get("state"))):
            raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")


class StageParallelAdmissionLifecycle:
    def __init__(self, project_root: str, *, attempt_bridge: Any, repository: str) -> None:
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.attempt_bridge = attempt_bridge
        self.repository = repository
        self._next_authoritative_action: dict[str, Any] | None = None

    def initialize(
        self,
        *,
        spec: dict[str, Any],
        task_authorizations: list[dict[str, str]],
    ) -> dict[str, Any]:
        auth = self._validate_authorizations(spec, task_authorizations)
        store = StageAdmissionProgressStore(self.project_root, spec["parallel_group_id"])
        lease = ProjectOperationLease(
            self.project_root,
            operation_kind="stage_parallel_admission_progress",
            surface="stage_parallel_admission",
        ).acquire()
        if not lease.held:
            raise StageAdmissionLifecycleError(lease.error_code or "PROJECT_OPERATION_LEASE_UNAVAILABLE")
        try:
            existing = store.read()
            if existing is not None:
                self._verify_spec(existing, spec)
                return self.public_projection(existing)
            record = {
                "schema_version": PROGRESS_SCHEMA_VERSION,
                "stage_id": spec["stage_id"],
                "parallel_group_id": spec["parallel_group_id"],
                "stage_planning_preview_sha256": spec["stage_planning_preview_sha256"],
                "project_identity": spec["project_identity"],
                "base_head": spec["base_head"],
                "runner_plan_sha256": spec["runner_plan_sha256"],
                "repository": self.repository,
                "task_order": list(spec["task_order"]),
                "spec_sha256": canonical_sha256(spec),
                "state": "PLANNED",
                "tasks": {
                    task_id: {
                        "grant_id": auth[task_id],
                        "target": None,
                        "attempt": None,
                        "artifacts": None,
                        "shard": None,
                        "fresh_authority": None,
                        "executor_preview": None,
                    }
                    for task_id in spec["task_order"]
                },
                "provider_started_count": 0,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            store.write(record, prior=None)
            return self.public_projection(record)
        finally:
            lease.release()

    def advance(
        self,
        *,
        spec: dict[str, Any],
        task_authorizations: list[dict[str, str]],
    ) -> dict[str, Any]:
        auth = self._validate_authorizations(spec, task_authorizations)
        store = StageAdmissionProgressStore(self.project_root, spec["parallel_group_id"])
        lease = ProjectOperationLease(
            self.project_root,
            operation_kind="stage_parallel_admission_advance",
            surface="stage_parallel_admission",
        ).acquire()
        if not lease.held:
            raise StageAdmissionLifecycleError(lease.error_code or "PROJECT_OPERATION_LEASE_UNAVAILABLE")
        try:
            self._next_authoritative_action = None
            record = store.read()
            if record is None:
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_NOT_FOUND")
            self._verify_spec(record, spec)
            self._verify_progress_reality(record, spec)
            prior = json.loads(json.dumps(record))
            state = record["state"]
            if state == "PLANNED":
                self._advance_b0(record, spec, auth)
            elif state == "B0_ALL_TASK_GRANTS_VALID":
                self._advance_b1(record, spec, auth)
            elif state == "B1_ALL_ATTEMPTS_ADMITTED":
                self._advance_b2(record, spec, auth)
            elif state == "B2_ALL_GOVERNED_TARGETS_COMPLETE":
                self._advance_b3(record, spec)
            elif state == "B3_ALL_SHARD_CONTEXTS_BOUND":
                self._advance_b4(record, spec, auth)
            elif state == "B4_ALL_FRESH_AUTHORITIES_READY":
                self._advance_b5(record, spec, auth)
            elif state == "B5_ALL_EXECUTOR_PREVIEWS_READY":
                self._advance_prepared(record, spec, auth)
            elif state == "PREPARED_FOR_EXECUTION":
                # PREPARED is a durable checkpoint, not standing governance
                # authority.  A later authenticated advance must earn a fresh
                # per-task canonical sweep before readiness can be asserted
                # again.
                self._verify_prepared(record, spec)
                for task_id in record["task_order"]:
                    record["tasks"][task_id]["executor_preview"][
                        "prepared_reverified"
                    ] = False
                record["state"] = "B5_ALL_EXECUTOR_PREVIEWS_READY"
            if record.get("provider_started_count") != 0:
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROVIDER_START_FORBIDDEN")
            record["updated_at"] = _now_iso()
            store.write(record, prior=prior)
            projection = self.public_projection(
                record,
                current_governance_revalidated=(
                    state == "B5_ALL_EXECUTOR_PREVIEWS_READY"
                    and record["state"] == "PREPARED_FOR_EXECUTION"
                ),
            )
            if self._next_authoritative_action is not None:
                projection["next_authoritative_action"] = dict(
                    self._next_authoritative_action
                )
            return projection
        except WorkItemGovernanceError as exc:
            raise StageAdmissionLifecycleError(exc.code, str(exc)) from exc
        finally:
            lease.release()

    def status(self, *, spec: dict[str, Any]) -> dict[str, Any]:
        record = StageAdmissionProgressStore(
            self.project_root, spec["parallel_group_id"]
        ).read()
        if record is None:
            raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_NOT_FOUND")
        self._verify_spec(record, spec)
        self._verify_progress_reality(record, spec)
        projection = self.public_projection(
            record, current_governance_revalidated=False
        )
        if record["state"] == "PREPARED_FOR_EXECUTION":
            projection["status"] = "CURRENT_GOVERNANCE_REVALIDATION_REQUIRED"
        return projection

    def _verify_progress_reality(
        self, record: dict[str, Any], spec: dict[str, Any]
    ) -> None:
        if set(record) != {
            "schema_version", "stage_id", "parallel_group_id",
            "stage_planning_preview_sha256", "project_identity", "base_head",
            "runner_plan_sha256", "repository", "task_order", "spec_sha256",
            "state", "tasks", "provider_started_count", "created_at", "updated_at",
        } or record.get("provider_started_count") != 0:
            raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
        if record.get("state") not in STATES:
            raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
        tasks = record.get("tasks")
        if not isinstance(tasks, dict) or set(tasks) != set(record["task_order"]):
            raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
        state_index = STATES.index(record["state"])
        for task_id in record["task_order"]:
            task = tasks.get(task_id)
            if not isinstance(task, dict) or set(task) != {
                "grant_id", "target", "attempt", "artifacts", "shard",
                "fresh_authority", "executor_preview",
            }:
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")
            required_by_barrier = (
                (1, "target"), (2, "attempt"), (3, "artifacts"),
                (4, "shard"), (5, "fresh_authority"), (6, "executor_preview"),
            )
            for barrier_index, field in required_by_barrier:
                if state_index >= barrier_index and task.get(field) is None:
                    raise StageAdmissionLifecycleError(
                        "STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH"
                    )
            if task.get("target") is not None:
                target = task["target"]
                raw_target = {
                    "work_item_id": target.get("work_item_id"),
                    "task_version": target.get("task_version"),
                }
                if set(target) != {"work_item_id", "task_version", "binding_sha256"} or (
                    target.get("binding_sha256") != canonical_sha256(raw_target)
                ):
                    raise StageAdmissionLifecycleError(
                        "STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH"
                    )
        completed_targets = [
            (tasks[item]["target"]["work_item_id"], tasks[item]["target"]["task_version"])
            for item in record["task_order"]
            if tasks[item]["target"] is not None
        ]
        if len(completed_targets) != len(set(completed_targets)):
            raise StageAdmissionLifecycleError("DUPLICATE_GOVERNED_TARGET")
        if state_index >= STATES.index("B3_ALL_SHARD_CONTEXTS_BOUND"):
            for task_id in record["task_order"]:
                current = self._verify_shard(
                    spec["tasks"][task_id]["shard"],
                    parallel_group_id=record["parallel_group_id"],
                    task_id=task_id,
                )
                if current != tasks[task_id]["shard"]:
                    raise StageAdmissionLifecycleError(
                        "STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH"
                    )
        if state_index >= STATES.index("B4_ALL_FRESH_AUTHORITIES_READY"):
            self._verify_existing_authorities(record)
        if state_index >= STATES.index("B5_ALL_EXECUTOR_PREVIEWS_READY"):
            for task_id in record["task_order"]:
                self._verify_executor_preview(tasks[task_id])

    def _advance_b0(self, record: dict[str, Any], spec: dict[str, Any], auth: dict[str, str]) -> None:
        for task_id in record["task_order"]:
            task = record["tasks"][task_id]
            if task["target"] is not None:
                continue
            inspected = self.attempt_bridge.inspect_task_grant(
                auth[task_id],
                expected_execution_context=spec["tasks"][task_id]["execution_context"],
            )
            if inspected.get("task_id") != task_id or inspected.get("target_authorized") is not True:
                raise StageAdmissionLifecycleError("STAGE_ATTEMPT_GRANT_CONTEXT_MISMATCH")
            target = {
                "work_item_id": inspected.get("work_item_id"),
                "task_version": inspected.get("task_version"),
            }
            if not isinstance(target["work_item_id"], str) or not isinstance(target["task_version"], int):
                raise StageAdmissionLifecycleError("STAGE_ATTEMPT_GRANT_TARGET_INVALID")
            task["grant_id"] = auth[task_id]
            task["target"] = {**target, "binding_sha256": canonical_sha256(target)}
            break
        if all(record["tasks"][task]["target"] is not None for task in record["task_order"]):
            targets = [
                (
                    record["tasks"][task]["target"]["work_item_id"],
                    record["tasks"][task]["target"]["task_version"],
                )
                for task in record["task_order"]
            ]
            if len(targets) != len(set(targets)):
                raise StageAdmissionLifecycleError("DUPLICATE_GOVERNED_TARGET")
            record["state"] = "B0_ALL_TASK_GRANTS_VALID"

    def _advance_b1(self, record: dict[str, Any], spec: dict[str, Any], auth: dict[str, str]) -> None:
        for task_id in record["task_order"]:
            task = record["tasks"][task_id]
            if task["attempt"] is not None:
                continue
            if task.get("grant_id") != auth[task_id]:
                inspected = self.attempt_bridge.inspect_task_grant(
                    auth[task_id],
                    expected_execution_context=spec["tasks"][task_id]["execution_context"],
                )
                target = task["target"]
                if (
                    inspected.get("task_id") != task_id
                    or inspected.get("target_authorized") is not True
                    or inspected.get("work_item_id") != target["work_item_id"]
                    or inspected.get("task_version") != target["task_version"]
                ):
                    raise StageAdmissionLifecycleError(
                        "STAGE_ATTEMPT_GRANT_TARGET_MISMATCH"
                    )
                # Re-mint recovery is deliberately a separate read-only outer
                # call.  The next call may perform the one permitted Attempt
                # mutation using this newly verified opaque handle.
                task["grant_id"] = auth[task_id]
                break
            result = self.attempt_bridge.inspect_task_attempt_admission(
                auth[task_id],
                expected_execution_context=spec["tasks"][task_id]["execution_context"],
            )
            if result.get("status") == "governance_admission_required":
                self._next_authoritative_action = {
                    "task_id": task_id,
                    "governance_admission_required": True,
                    "grant_id": auth[task_id],
                    "operation": "apply_execution_attempt_create",
                }
                break
            attempt = result.get("attempt")
            target = task["target"]
            if (
                not isinstance(attempt, dict)
                or attempt.get("work_item_id") != target["work_item_id"]
                or attempt.get("task_version") != target["task_version"]
                or not isinstance(attempt.get("attempt_id"), str)
            ):
                raise StageAdmissionLifecycleError("STAGE_ATTEMPT_RESULT_MISMATCH")
            task["grant_id"] = auth[task_id]
            task["attempt"] = {
                "attempt_id": attempt["attempt_id"],
                "source_event_key": attempt.get("source_event_key"),
                "verified": True,
            }
            break
        if all(record["tasks"][task]["attempt"] is not None for task in record["task_order"]):
            record["state"] = "B1_ALL_ATTEMPTS_ADMITTED"

    def _advance_b2(self, record: dict[str, Any], spec: dict[str, Any], auth: dict[str, str]) -> None:
        for task_id in record["task_order"]:
            task = record["tasks"][task_id]
            if task["artifacts"] is not None:
                continue
            refs = self._resolve_current_artifacts(record, spec, auth, task_id)
            task["grant_id"] = auth[task_id]
            task["artifacts"] = {
                "artifact_refs": refs,
                "refs_sha256": canonical_sha256({"artifact_refs": refs}),
                "count": len(refs),
                "ledger_backed": True,
                "verified": True,
            }
            break
        if all(record["tasks"][task]["artifacts"] is not None for task in record["task_order"]):
            record["state"] = "B2_ALL_GOVERNED_TARGETS_COMPLETE"

    def _advance_b3(self, record: dict[str, Any], spec: dict[str, Any]) -> None:
        for task_id in record["task_order"]:
            shard = self._verify_shard(
                spec["tasks"][task_id]["shard"],
                parallel_group_id=record["parallel_group_id"],
                task_id=task_id,
            )
            record["tasks"][task_id]["shard"] = shard
        record["state"] = "B3_ALL_SHARD_CONTEXTS_BOUND"

    def _advance_b4(self, record: dict[str, Any], spec: dict[str, Any], auth: dict[str, str]) -> None:
        self._verify_existing_authorities(record)
        created_this_call = False
        for task_id in record["task_order"]:
            task = record["tasks"][task_id]
            if task["fresh_authority"] is not None:
                continue
            refs = self._resolve_current_artifacts(record, spec, auth, task_id)
            if refs != task["artifacts"]["artifact_refs"]:
                task["artifacts"] = {
                    "artifact_refs": refs,
                    "refs_sha256": canonical_sha256({"artifact_refs": refs}),
                    "count": len(refs),
                    "ledger_backed": True,
                    "verified": True,
                }
            target = task["target"]
            shard = task["shard"]
            result = create_or_resolve_stage_shard_fresh_executor_authority(
                shard["project_root"],
                expected_repository=self.repository,
                stage_preview_sha256=record["stage_planning_preview_sha256"],
                runner_plan_sha256=record["runner_plan_sha256"],
                stage_id=record["stage_id"],
                parallel_group_id=record["parallel_group_id"],
                task_id=task_id,
                work_item_id=target["work_item_id"],
                task_version=target["task_version"],
                attempt_id=task["attempt"]["attempt_id"],
                artifact_refs=list(task["artifacts"]["artifact_refs"]),
                expected_git_branch=shard["branch"],
                expected_head=shard["head"],
                provider=shard["provider"],
            )
            if not result.get("ok") or result.get("unconsumed") is not True:
                raise StageAdmissionLifecycleError(str(result.get("error_code") or "STAGE_SHARD_AUTHORITY_FAILED"))
            task["grant_id"] = auth[task_id]
            task["fresh_authority"] = {
                "reservation_key": result["stage_shard_admission_key"],
                "authority_id": result["executor_authority_id"],
                "admission_sha256": result["admission_sha256"],
                "verified": True,
                "consumed": False,
                "barrier_reverified": False,
            }
            created_this_call = True
            break
        if not created_this_call and all(
            record["tasks"][task]["fresh_authority"] is not None
            for task in record["task_order"]
        ):
            for task_id in record["task_order"]:
                authority = record["tasks"][task_id]["fresh_authority"]
                if authority.get("barrier_reverified") is True:
                    continue
                latest = self._resolve_current_artifacts(record, spec, auth, task_id)
                if latest != record["tasks"][task_id]["artifacts"]["artifact_refs"]:
                    raise StageAdmissionLifecycleError("STAGE_ATTEMPT_ARTIFACT_PROJECTION_DRIFT")
                authority["barrier_reverified"] = True
                break
        if all(
            record["tasks"][task]["fresh_authority"] is not None
            and record["tasks"][task]["fresh_authority"].get("barrier_reverified") is True
            for task in record["task_order"]
        ):
            self._verify_existing_authorities(record)
            record["state"] = "B4_ALL_FRESH_AUTHORITIES_READY"

    def _advance_b5(
        self,
        record: dict[str, Any],
        spec: dict[str, Any],
        auth: dict[str, str],
    ) -> None:
        self._verify_existing_authorities(record)
        created_this_call = False
        for task_id in record["task_order"]:
            task = record["tasks"][task_id]
            if task["executor_preview"] is not None:
                self._verify_executor_preview(task)
                continue
            latest = self._resolve_current_artifacts(record, spec, auth, task_id)
            if latest != task["artifacts"]["artifact_refs"]:
                raise StageAdmissionLifecycleError("STAGE_ATTEMPT_ARTIFACT_PROJECTION_DRIFT")
            target = {
                "work_item_id": task["target"]["work_item_id"],
                "task_version": task["target"]["task_version"],
                "attempt_id": task["attempt"]["attempt_id"],
                "artifact_refs": list(task["artifacts"]["artifact_refs"]),
            }
            shard = task["shard"]
            authority = task["fresh_authority"]
            request = {
                "project_root": shard["project_root"],
                "provider": shard["provider"],
                "execution_mode": "run",
                "executor_session_mode": "start_new",
                "expected_execution_branch": shard["branch"],
                "expected_head": shard["head"],
                "work_target": target,
                "authority_id": authority["authority_id"],
                "admission_sha256": authority["admission_sha256"],
            }
            request_sha = canonical_sha256(request)
            result = MCPExecutorWorkflowManager(shard["project_root"]).handle(
                "run_once_preview",
                {
                    "provider": shard["provider"],
                    "execution_mode": "run",
                    "executor_session_mode": "start_new",
                    "executor_authority_id": authority["authority_id"],
                    "admission_sha256": authority["admission_sha256"],
                    "_stage_execution_context": {
                        "expected_execution_branch": shard["branch"],
                        "expected_head": shard["head"],
                        "work_target": target,
                        "executor_preview_request_sha256": request_sha,
                    },
                },
            )
            if not result.get("ok"):
                raise StageAdmissionLifecycleError(str(result.get("error_code") or "EXECUTOR_PREVIEW_CREATE_FAILED"))
            task["executor_preview"] = {
                "request_sha256": request_sha,
                "preview_id": result.get("preview_id"),
                "verified": True,
                "barrier_reverified": False,
                "prepared_reverified": False,
            }
            created_this_call = True
            self._verify_executor_preview(task)
            break
        if not created_this_call and all(
            record["tasks"][task]["executor_preview"] is not None
            for task in record["task_order"]
        ):
            for task_id in record["task_order"]:
                preview = record["tasks"][task_id]["executor_preview"]
                if preview.get("barrier_reverified") is True:
                    continue
                latest = self._resolve_current_artifacts(record, spec, auth, task_id)
                if latest != record["tasks"][task_id]["artifacts"]["artifact_refs"]:
                    raise StageAdmissionLifecycleError("STAGE_ATTEMPT_ARTIFACT_PROJECTION_DRIFT")
                self._verify_executor_preview(record["tasks"][task_id])
                preview["barrier_reverified"] = True
                break
        if all(
            record["tasks"][task]["executor_preview"] is not None
            and record["tasks"][task]["executor_preview"].get("barrier_reverified") is True
            for task in record["task_order"]
        ):
            record["state"] = "B5_ALL_EXECUTOR_PREVIEWS_READY"

    def _advance_prepared(
        self,
        record: dict[str, Any],
        spec: dict[str, Any],
        auth: dict[str, str],
    ) -> None:
        self._verify_prepared(record, spec)
        for task_id in record["task_order"]:
            preview = record["tasks"][task_id]["executor_preview"]
            if preview.get("prepared_reverified") is True:
                continue
            latest = self._resolve_current_artifacts(record, spec, auth, task_id)
            if latest != record["tasks"][task_id]["artifacts"]["artifact_refs"]:
                raise StageAdmissionLifecycleError(
                    "STAGE_ATTEMPT_ARTIFACT_PROJECTION_DRIFT"
                )
            self._verify_executor_preview(record["tasks"][task_id])
            preview["prepared_reverified"] = True
            break
        if all(
            record["tasks"][task]["executor_preview"].get("prepared_reverified")
            is True
            for task in record["task_order"]
        ):
            record["state"] = "PREPARED_FOR_EXECUTION"

    def _resolve_current_artifacts(
        self,
        record: dict[str, Any],
        spec: dict[str, Any],
        auth: dict[str, str],
        task_id: str,
    ) -> list[str]:
        task = record["tasks"][task_id]
        result = self.attempt_bridge.resolve_task_attempt_artifacts(
            auth[task_id],
            expected_execution_context=spec["tasks"][task_id]["execution_context"],
            attempt_id=task["attempt"]["attempt_id"],
        )
        target = task["target"]
        refs = result.get("artifact_refs")
        if (
            result.get("work_item_id") != target["work_item_id"]
            or result.get("task_version") != target["task_version"]
            or result.get("attempt_id") != task["attempt"]["attempt_id"]
            or result.get("dispatch_eligible") is not True
            or result.get("ledger_backed") is not True
            or result.get("synthetic_empty") is not False
            or not isinstance(refs, list)
            or refs != sorted(set(refs))
        ):
            raise StageAdmissionLifecycleError("STAGE_ATTEMPT_ARTIFACT_PROJECTION_INVALID")
        return refs

    def _verify_existing_authorities(self, record: dict[str, Any]) -> None:
        for task_id in record["task_order"]:
            task = record["tasks"][task_id]
            authority = task.get("fresh_authority")
            if authority is None:
                continue
            shard = task["shard"]
            result = inspect_stage_shard_fresh_executor_authority(
                shard["project_root"],
                authority["authority_id"],
                expected_stage_shard_admission_key=authority["reservation_key"],
                expected_admission_sha256=authority["admission_sha256"],
                expected_binding=self._authority_binding(record, task_id),
            )
            if not result.get("ok") or result.get("unconsumed") is not True:
                raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")

    def _authority_binding(self, record: dict[str, Any], task_id: str) -> dict[str, Any]:
        task = record["tasks"][task_id]
        target = task["target"]
        shard = task["shard"]
        refs = list(task["artifacts"]["artifact_refs"])
        return {
            "project_identity": canonical_sha256(
                {"project_root": shard["project_root"], "repository": self.repository}
            ),
            "project_root": shard["project_root"],
            "repository": self.repository,
            "stage_preview_sha256": record["stage_planning_preview_sha256"],
            "runner_plan_sha256": record["runner_plan_sha256"],
            "stage_id": record["stage_id"],
            "parallel_group_id": record["parallel_group_id"],
            "task_id": task_id,
            "work_item_id": target["work_item_id"],
            "task_version": target["task_version"],
            "attempt_id": task["attempt"]["attempt_id"],
            "artifact_refs": refs,
            "artifact_refs_sha256": canonical_sha256({"artifact_refs": refs}),
            "git_branch": shard["branch"],
            "git_head": shard["head"],
            "provider": shard["provider"],
        }

    def _verify_executor_preview(self, task: dict[str, Any]) -> None:
        preview = task["executor_preview"]
        shard = task["shard"]
        artifact = MCPExecutorWorkflowManager(shard["project_root"])._read_preview_artifact(
            preview["preview_id"]
        )
        authority = task["fresh_authority"]
        expected_target = {
            "work_item_id": task["target"]["work_item_id"],
            "task_version": task["target"]["task_version"],
            "attempt_id": task["attempt"]["attempt_id"],
            "artifact_refs": task["artifacts"]["artifact_refs"],
        }
        if (
            not isinstance(artifact, dict)
            or artifact.get("stage_executor_preview_request_sha256") != preview["request_sha256"]
            or artifact.get("project_root") != shard["project_root"]
            or artifact.get("current_branch") != shard["branch"]
            or artifact.get("current_head") != shard["head"]
            or artifact.get("expected_execution_branch") != shard["branch"]
            or artifact.get("provider") != shard["provider"]
            or artifact.get("execution_mode") != "run"
            or artifact.get("fresh_execution_authority", {}).get("executor_authority_id")
            != authority["authority_id"]
            or artifact.get("fresh_execution_authority", {}).get("admission_sha256")
            != authority["admission_sha256"]
            or artifact.get("work_target") != expected_target
        ):
            raise StageAdmissionLifecycleError("STAGE_EXECUTOR_PREVIEW_RECONCILIATION_MISMATCH")

    def _verify_prepared(self, record: dict[str, Any], spec: dict[str, Any]) -> None:
        self._verify_spec(record, spec)
        self._verify_existing_authorities(record)
        for task_id in record["task_order"]:
            self._verify_shard(
                spec["tasks"][task_id]["shard"],
                parallel_group_id=record["parallel_group_id"],
                task_id=task_id,
            )
            self._verify_executor_preview(record["tasks"][task_id])

    def _verify_shard(
        self,
        shard: dict[str, Any],
        *,
        parallel_group_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        root = os.path.abspath(os.path.expanduser(str(shard.get("project_root") or "")))
        expected_runtime = os.path.join(
            self.project_root, ".colameta", "runtime", "parallel-worktrees"
        )
        expected_root = os.path.join(expected_runtime, parallel_group_id, task_id)
        if (
            os.path.realpath(root) != root
            or root != expected_root
            or not os.path.isdir(root)
        ):
            raise StageAdmissionLifecycleError("STAGE_SHARD_ROOT_MISMATCH")
        completed = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        entries: dict[str, dict[str, str]] = {}
        current: dict[str, str] | None = None
        for line in completed.stdout.splitlines():
            if line.startswith("worktree "):
                current = {"worktree": line[9:]}
                entries[os.path.abspath(line[9:])] = current
            elif current is not None and " " in line:
                key, value = line.split(" ", 1)
                current[key] = value
        observed = entries.get(root)
        branch = str(shard.get("branch") or "")
        head = str(shard.get("head") or "")
        provider = str(shard.get("provider") or "")
        if (
            completed.returncode != 0
            or observed is None
            or observed.get("branch") != f"refs/heads/{branch}"
            or observed.get("HEAD") != head
            or provider != "codex"
        ):
            raise StageAdmissionLifecycleError("STAGE_SHARD_CONTEXT_MISMATCH")
        return {
            "project_root": root,
            "root_identity": canonical_sha256({"project_root": root, "worktree": observed}),
            "branch": branch,
            "head": head,
            "provider": provider,
            "verified": True,
        }

    def _validate_authorizations(
        self, spec: dict[str, Any], values: list[dict[str, str]]
    ) -> dict[str, str]:
        if not isinstance(values, list):
            raise StageAdmissionLifecycleError("TASK_AUTHORIZATIONS_REQUIRED")
        result: dict[str, str] = {}
        grants: set[str] = set()
        for value in values:
            if not isinstance(value, dict) or set(value) != {"task_id", "grant_id"}:
                raise StageAdmissionLifecycleError("TASK_AUTHORIZATION_INVALID")
            task_id = value.get("task_id")
            grant_id = value.get("grant_id")
            if not isinstance(task_id, str) or not task_id or not isinstance(grant_id, str) or not grant_id:
                raise StageAdmissionLifecycleError("TASK_AUTHORIZATION_INVALID")
            if task_id in result:
                raise StageAdmissionLifecycleError("TASK_AUTHORIZATION_DUPLICATE_TASK")
            if grant_id in grants:
                raise StageAdmissionLifecycleError("TASK_AUTHORIZATION_DUPLICATE_GRANT")
            result[task_id] = grant_id
            grants.add(grant_id)
        if set(result) != set(spec.get("task_order", [])):
            raise StageAdmissionLifecycleError("TASK_AUTHORIZATION_COVERAGE_MISMATCH")
        return result

    @staticmethod
    def _verify_spec(record: dict[str, Any], spec: dict[str, Any]) -> None:
        if (
            record.get("schema_version") != PROGRESS_SCHEMA_VERSION
            or record.get("spec_sha256") != canonical_sha256(spec)
            or record.get("parallel_group_id") != spec.get("parallel_group_id")
            or record.get("task_order") != spec.get("task_order")
        ):
            raise StageAdmissionLifecycleError("STAGE_ADMISSION_PROGRESS_INTEGRITY_MISMATCH")

    @staticmethod
    def public_projection(
        record: dict[str, Any], *, current_governance_revalidated: bool = False
    ) -> dict[str, Any]:
        tasks = record.get("tasks") if isinstance(record.get("tasks"), dict) else {}
        return {
            "ok": True,
            "status": (
                "PREPARED_FOR_EXECUTION"
                if record.get("state") == "PREPARED_FOR_EXECUTION"
                and current_governance_revalidated
                else "admission_in_progress"
            ),
            "lifecycle_state": record.get("state"),
            "stage_id": record.get("stage_id"),
            "parallel_group_id": record.get("parallel_group_id"),
            "tasks": [
                {
                    "task_id": task_id,
                    "attempt_admitted": tasks.get(task_id, {}).get("attempt") is not None,
                    "artifact_binding_ready": tasks.get(task_id, {}).get("artifacts") is not None,
                    "shard_context_ready": tasks.get(task_id, {}).get("shard") is not None,
                    "fresh_authority_ready": tasks.get(task_id, {}).get("fresh_authority") is not None,
                    "executor_preview_ready": tasks.get(task_id, {}).get("executor_preview") is not None,
                }
                for task_id in record.get("task_order", [])
            ],
            "provider_started_count": 0,
            "provider_start_authorized": False,
            "prepared_checkpoint_present": (
                record.get("state") == "PREPARED_FOR_EXECUTION"
            ),
            "current_governance_revalidated": current_governance_revalidated,
            "execution_attempt_mutation_count_max_per_call": 1,
            "private_authority_material_exposed": False,
        }
