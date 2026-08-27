import fcntl
import hashlib
import json
import logging
import os
import re
import stat
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from runner.work_item_governance.references import optional_work_item_reference_rejections


_PREVIEW_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_AUTHORITY_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXECUTOR_RUN_CLAIM_SCHEMA_VERSION = "executor_run_claim.v1"
_DURABLE_IDENTITY_KEY = "_colameta_durable_identity"
_MAX_CLAIM_BYTES = 1024 * 1024

_CLAIM_REQUIRED_FIELDS = frozenset(
    {
        "schema_version", "preview_id", "run_id", "artifact_kind",
        "project_root", "provider", "execution_mode", "current_version",
        "current_head", "claimed_at", "status", "model", "model_source",
        "worker_pid", "worker_started_at", "thread_started_at",
        "last_heartbeat_at", "heartbeat_interval_seconds",
        "heartbeat_timeout_seconds", "original_preview_created_at",
        "original_preview_expires_at",
    }
)
_CLAIM_OPTIONAL_FIELDS = frozenset(
    {
        "executor_authority_id", "admission_sha256", "work_item_id",
        "task_version", "attempt_id", "artifact_refs", "finished_at",
        "report_id", "error_code", "error_message", "exception_type",
        "blockers", "warnings",
    }
)
_CLAIM_STRING_FIELDS = frozenset(
    {
        "preview_id", "run_id", "artifact_kind", "project_root", "provider",
        "execution_mode", "current_version", "current_head", "claimed_at",
        "status", "worker_started_at", "thread_started_at",
        "last_heartbeat_at", "original_preview_created_at",
        "original_preview_expires_at", "finished_at", "report_id",
        "error_code", "error_message", "exception_type",
    }
)


def _stat_identity(metadata: os.stat_result) -> dict[str, int]:
    return {"device": int(metadata.st_dev), "inode": int(metadata.st_ino)}


def _stat_metadata(metadata: os.stat_result) -> dict[str, int]:
    return {
        "device": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "mode": int(metadata.st_mode),
        "uid": int(metadata.st_uid),
        "gid": int(metadata.st_gid),
        "nlink": int(metadata.st_nlink),
        "size": int(metadata.st_size),
        "mtime_ns": int(metadata.st_mtime_ns),
        "ctime_ns": int(metadata.st_ctime_ns),
    }


def _same_file_snapshot(first: os.stat_result, second: os.stat_result) -> bool:
    fields = (
        "st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size",
        "st_mtime_ns", "st_ctime_ns",
    )
    return all(getattr(first, field) == getattr(second, field) for field in fields)


def _trusted_directory(metadata: os.stat_result) -> bool:
    return bool(
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and metadata.st_nlink >= 1
        and stat.S_IMODE(metadata.st_mode) & 0o022 == 0
    )


def _trusted_claim_file(metadata: os.stat_result) -> bool:
    return bool(
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and metadata.st_nlink == 1
        and stat.S_IMODE(metadata.st_mode) & 0o077 == 0
        and 0 <= metadata.st_size <= _MAX_CLAIM_BYTES
    )


class ExecutorRunClaimStore:
    def __init__(
        self,
        project_root: str,
        previews_relative_dir: str,
        claims_dir: str,
        heartbeat_interval_seconds: int,
        heartbeat_stale_multiplier: int,
        heartbeat_stale_min_seconds: int,
    ):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.previews_root = os.path.join(self.project_root, previews_relative_dir)
        self.claims_root = os.path.join(self.previews_root, claims_dir)
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.heartbeat_stale_multiplier = heartbeat_stale_multiplier
        self.heartbeat_stale_min_seconds = heartbeat_stale_min_seconds

    def create_run_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"exec_run_{ts}_{uuid.uuid4().hex[:8]}"

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).astimezone().isoformat()

    def heartbeat_timeout_seconds(self, interval_seconds: int) -> int:
        return max(
            self.heartbeat_stale_min_seconds,
            int(interval_seconds) * self.heartbeat_stale_multiplier,
        )

    def claim_record_path(self, preview_id: str) -> str:
        path = self._safe_claim_path(preview_id)
        if path is None:
            raise ValueError("invalid preview_id")
        return path

    def read_claim(self, preview_id: str) -> dict[str, Any] | None:
        verification = self._read_claim_verification(preview_id)
        record = verification.get("record") if verification.get("ok") else None
        return record if isinstance(record, dict) else None

    def _read_claim_verification(
        self, preview_id: str, *, expected_run_id: str | None = None
    ) -> dict[str, Any]:
        """Read one exact claim and return safe descriptor/digest evidence."""

        if not self._valid_preview_id(preview_id):
            return {"ok": False, "error_code": "CLAIM_PREVIEW_ID_INVALID"}
        opened = self._open_claims_chain()
        if not opened.get("ok"):
            return opened
        claim_fd = -1
        claim_locked = False
        try:
            try:
                claim_fd = os.open(
                    f"{preview_id}.json",
                    os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=opened["claims_fd"],
                )
            except FileNotFoundError:
                return {"ok": False, "error_code": "CLAIM_NOT_FOUND"}
            except OSError:
                return {"ok": False, "error_code": "CLAIM_FILE_UNSAFE"}
            try:
                before = os.fstat(claim_fd)
                if not _trusted_claim_file(before):
                    return {"ok": False, "error_code": "CLAIM_FILE_UNSAFE"}
                self._bounded_flock(claim_fd, fcntl.LOCK_SH)
                claim_locked = True
                locked = os.fstat(claim_fd)
                if (
                    not _trusted_claim_file(locked)
                    or not _same_file_snapshot(before, locked)
                    or not self._verify_claims_chain(opened)
                ):
                    return {"ok": False, "error_code": "CLAIM_READ_UNSTABLE"}
                raw = self._read_fd_complete(claim_fd, before.st_size)
                os.lseek(claim_fd, 0, os.SEEK_SET)
                repeated = self._read_fd_complete(claim_fd, before.st_size)
                after = os.fstat(claim_fd)
                current = os.stat(
                    f"{preview_id}.json",
                    dir_fd=opened["claims_fd"],
                    follow_symlinks=False,
                )
            except OSError:
                return {"ok": False, "error_code": "CLAIM_READ_UNSTABLE"}
            if (
                raw != repeated
                or not _same_file_snapshot(before, after)
                or not _trusted_claim_file(after)
                or not _trusted_claim_file(current)
                or not _same_file_snapshot(before, current)
                or not self._verify_claims_chain(opened)
            ):
                return {"ok": False, "error_code": "CLAIM_READ_UNSTABLE"}
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return {"ok": False, "error_code": "CLAIM_JSON_INVALID"}
            schema_error = self._validate_claim_contract(
                parsed,
                preview_id=preview_id,
                expected_run_id=expected_run_id,
            )
            if schema_error is not None:
                return {"ok": False, "error_code": schema_error}
            assert isinstance(parsed, dict)
            durable_contract = {
                "identity": _stat_identity(before),
                "metadata": _stat_metadata(before),
                "size": int(before.st_size),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "content_sha256": hashlib.sha256(
                    json.dumps(
                        parsed,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }
            try:
                final_descriptor = os.fstat(claim_fd)
                final_path = os.stat(
                    f"{preview_id}.json",
                    dir_fd=opened["claims_fd"],
                    follow_symlinks=False,
                )
            except OSError:
                return {"ok": False, "error_code": "CLAIM_READ_UNSTABLE"}
            if (
                not _trusted_claim_file(final_descriptor)
                or not _trusted_claim_file(final_path)
                or not _same_file_snapshot(before, final_descriptor)
                or not _same_file_snapshot(before, final_path)
                or not self._verify_claims_chain(opened)
            ):
                return {"ok": False, "error_code": "CLAIM_READ_UNSTABLE"}
            return {
                "ok": True,
                "record": parsed,
                "durable_contract": durable_contract,
            }
        finally:
            if claim_fd >= 0:
                try:
                    if claim_locked:
                        fcntl.flock(claim_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                try:
                    os.close(claim_fd)
                except OSError:
                    pass
            for fd in reversed(opened.get("fds", [])):
                try:
                    os.close(fd)
                except OSError:
                    pass

    def write_claim(self, preview_id: str, claim: dict[str, Any]) -> None:
        payload = {
            key: value for key, value in claim.items() if key != _DURABLE_IDENTITY_KEY
        }
        error = self._validate_claim_contract(payload, preview_id=preview_id)
        if error is not None:
            raise ValueError(error)
        raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        opened = self._open_claims_chain()
        if not opened.get("ok"):
            raise OSError(str(opened.get("error_code") or "claim directory unsafe"))
        claim_fd = -1
        temp_name = f".{preview_id}.{uuid.uuid4().hex}.tmp"
        try:
            claim_fd = os.open(
                temp_name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=opened["claims_fd"],
            )
            view = memoryview(raw)
            while view:
                written = os.write(claim_fd, view)
                if written <= 0:
                    raise OSError("incomplete claim write")
                view = view[written:]
            os.fsync(claim_fd)
            written_metadata = os.fstat(claim_fd)
            if not _trusted_claim_file(written_metadata):
                raise OSError("replacement claim file unsafe")
            os.close(claim_fd)
            claim_fd = -1
            if (
                not self._refresh_claims_chain_snapshot(opened)
                or not self._verify_claims_chain(opened)
            ):
                raise OSError("claim ancestor changed before replacement")
            os.replace(
                temp_name,
                f"{preview_id}.json",
                src_dir_fd=opened["claims_fd"],
                dst_dir_fd=opened["claims_fd"],
            )
            temp_name = ""
            os.fsync(opened["claims_fd"])
            if (
                not self._refresh_claims_chain_snapshot(opened)
                or not self._verify_claims_chain(opened)
            ):
                raise OSError("claim ancestor changed during replacement")
        finally:
            if claim_fd >= 0:
                os.close(claim_fd)
            if temp_name:
                try:
                    os.unlink(temp_name, dir_fd=opened["claims_fd"])
                except FileNotFoundError:
                    pass
            for fd in reversed(opened.get("fds", [])):
                try:
                    os.close(fd)
                except OSError:
                    pass
        verification = self._read_claim_verification(
            preview_id,
            expected_run_id=str(payload.get("run_id") or ""),
        )
        if not verification.get("ok") or verification.get("record") != payload:
            raise OSError("persisted claim replacement failed readback verification")

    def acquire_claim(
        self,
        *,
        preview_id: str,
        artifact: dict[str, Any],
        provider: str,
        execution_mode: str,
        executor_authority_id: str | None = None,
        admission_sha256: str | None = None,
    ) -> dict[str, Any]:
        self.claim_record_path(preview_id)
        work_item_binding: dict[str, Any] = {}
        if any(field in artifact for field in ("work_item_id", "task_version", "attempt_id", "artifact_refs")):
            work_item_binding = {
                "work_item_id": artifact.get("work_item_id"),
                "task_version": artifact.get("task_version"),
                "attempt_id": artifact.get("attempt_id"),
                "artifact_refs": list(artifact.get("artifact_refs") or []),
            }
            binding_rejections = optional_work_item_reference_rejections(work_item_binding)
            if binding_rejections:
                return {
                    "ok": False,
                    "error_code": "WORK_ITEM_BINDING_INVALID",
                    "binding_rejections": binding_rejections,
                }
        if "fresh_execution_authority" in artifact:
            artifact_authority = artifact.get("fresh_execution_authority")
            if not isinstance(artifact_authority, dict):
                return {"ok": False, "error_code": "PREVIEW_CLAIM_FAILED"}
            expected_authority_id = artifact_authority.get("executor_authority_id")
            expected_admission_sha256 = artifact_authority.get("admission_sha256")
            if (
                type(expected_authority_id) is not str
                or _AUTHORITY_ID_RE.fullmatch(expected_authority_id) is None
                or type(expected_admission_sha256) is not str
                or _SHA256_RE.fullmatch(expected_admission_sha256) is None
                or type(executor_authority_id) is not str
                or _AUTHORITY_ID_RE.fullmatch(executor_authority_id) is None
                or type(admission_sha256) is not str
                or _SHA256_RE.fullmatch(admission_sha256) is None
                or executor_authority_id != expected_authority_id
                or admission_sha256 != expected_admission_sha256
            ):
                return {"ok": False, "error_code": "PREVIEW_CLAIM_FAILED"}
        run_id = self.create_run_id()
        claimed_at = self.now_iso()
        artifact_model = str(artifact.get("model") or "").strip()
        artifact_model_source = str(artifact.get("model_source") or "").strip()
        claim_record = {
            "schema_version": EXECUTOR_RUN_CLAIM_SCHEMA_VERSION,
            "preview_id": preview_id,
            "run_id": run_id,
            "artifact_kind": str(artifact.get("artifact_kind") or ""),
            "project_root": self.project_root,
            "provider": provider,
            "execution_mode": execution_mode,
            "current_version": str(artifact.get("current_version") or ""),
            "current_head": str(artifact.get("current_head") or ""),
            "claimed_at": claimed_at,
            "status": "RUNNING",
            "model": artifact_model or None,
            "model_source": artifact_model_source or None,
            "worker_pid": os.getpid(),
            "worker_started_at": claimed_at,
            "thread_started_at": "",
            "last_heartbeat_at": claimed_at,
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "heartbeat_timeout_seconds": self.heartbeat_timeout_seconds(self.heartbeat_interval_seconds),
            "original_preview_created_at": str(artifact.get("created_at") or ""),
            "original_preview_expires_at": str(artifact.get("expires_at") or ""),
        }
        if type(executor_authority_id) is str and executor_authority_id:
            claim_record["executor_authority_id"] = executor_authority_id
        if type(admission_sha256) is str and admission_sha256:
            claim_record["admission_sha256"] = admission_sha256
        claim_record.update(work_item_binding)
        contract_error = self._validate_claim_contract(
            claim_record, preview_id=preview_id, expected_run_id=run_id
        )
        if contract_error is not None:
            return {"ok": False, "error_code": contract_error}
        opened = self._open_claims_chain(create=True)
        if not opened.get("ok"):
            return {"ok": False, "error_code": "PREVIEW_CLAIM_FAILED"}
        fd = -1
        try:
            fd = os.open(
                f"{preview_id}.json",
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=opened["claims_fd"],
            )
        except FileExistsError:
            for opened_fd in reversed(opened["fds"]):
                os.close(opened_fd)
            return {"ok": False, "error_code": "CLAIM_EXISTS", "claim": self.read_claim(preview_id) or {}}
        except Exception:
            for opened_fd in reversed(opened["fds"]):
                os.close(opened_fd)
            return {"ok": False, "error_code": "PREVIEW_CLAIM_FAILED"}
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                json.dump(claim_record, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(opened["claims_fd"])
            if (
                not self._refresh_claims_chain_snapshot(opened)
                or not self._verify_claims_chain(opened)
            ):
                raise OSError("claim ancestor changed during create")
            verification = self._read_claim_verification(
                preview_id,
                expected_run_id=run_id,
            )
            if (
                not verification.get("ok")
                or verification.get("record") != claim_record
            ):
                raise OSError("persisted claim create failed readback verification")
        except Exception:
            try:
                os.unlink(f"{preview_id}.json", dir_fd=opened["claims_fd"])
            except Exception:
                pass
            return {"ok": False, "error_code": "PREVIEW_CLAIM_FAILED"}
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            for opened_fd in reversed(opened["fds"]):
                try:
                    os.close(opened_fd)
                except OSError:
                    pass
        return {
            "ok": True,
            "run_id": run_id,
            "claimed_at": claimed_at,
            "preview_claim_status": "RUNNING",
            "claim": claim_record,
        }

    def finalize_claim(
        self,
        *,
        preview_id: str,
        run_id: str,
        final_status: str,
        report_id: str = "",
        error_code: str = "",
        message: str = "",
        exception_type: str = "",
        blockers: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        claim = self.read_claim(preview_id)
        if not isinstance(claim, dict):
            return
        if run_id and str(claim.get("run_id") or "") and str(claim.get("run_id") or "") != run_id:
            return
        now_iso = self.now_iso()
        claim["status"] = final_status
        claim["finished_at"] = now_iso
        claim["last_heartbeat_at"] = now_iso
        if report_id:
            claim["report_id"] = report_id
        if error_code:
            claim["error_code"] = error_code
        if message:
            claim["error_message"] = message
        if exception_type:
            claim["exception_type"] = exception_type
        if blockers:
            claim["blockers"] = blockers
        if warnings:
            claim["warnings"] = warnings
        self.write_claim(preview_id, claim)

    def mark_worker_started(
        self,
        *,
        preview_id: str,
        run_id: str,
        thread_started_at: str,
        worker_pid: int,
        heartbeat_interval_seconds: int,
    ) -> None:
        claim = self.read_claim(preview_id)
        if not isinstance(claim, dict):
            return
        if run_id and str(claim.get("run_id") or "") and str(claim.get("run_id") or "") != run_id:
            return
        claim["worker_pid"] = worker_pid
        claim["worker_started_at"] = thread_started_at
        claim["thread_started_at"] = thread_started_at
        claim["last_heartbeat_at"] = thread_started_at
        claim["heartbeat_interval_seconds"] = max(1, int(heartbeat_interval_seconds))
        claim["heartbeat_timeout_seconds"] = self.heartbeat_timeout_seconds(claim["heartbeat_interval_seconds"])
        self.write_claim(preview_id, claim)

    def refresh_heartbeat(
        self,
        *,
        preview_id: str,
        run_id: str,
        error_state: dict[str, Any] | None = None,
    ) -> bool:
        try:
            claim = self.read_claim(preview_id)
            if not isinstance(claim, dict):
                return False
            if run_id and str(claim.get("run_id") or "") and str(claim.get("run_id") or "") != run_id:
                return False
            if str(claim.get("status") or "") != "RUNNING":
                return False
            now_iso = self.now_iso()
            interval = self._coerce_int(claim.get("heartbeat_interval_seconds"), self.heartbeat_interval_seconds)
            claim["last_heartbeat_at"] = now_iso
            claim["heartbeat_interval_seconds"] = max(1, interval)
            claim["heartbeat_timeout_seconds"] = self.heartbeat_timeout_seconds(claim["heartbeat_interval_seconds"])
            self.write_claim(preview_id, claim)
            return True
        except Exception as exc:
            if isinstance(error_state, dict):
                error_state["errors"] = int(error_state.get("errors", 0) or 0) + 1
                error_state["last_error"] = str(exc)
            logging.exception("刷新 executor claim heartbeat 失败")
            return False

    def release_claim(self, preview_id: str) -> None:
        path = self._safe_claim_path(preview_id)
        if path is None:
            return
        try:
            if os.path.isfile(path):
                os.unlink(path)
        except Exception:
            pass

    def find_claim_by_run_id(self, run_id: str) -> dict[str, Any] | None:
        if not os.path.isdir(self.claims_root):
            return None
        try:
            for fname in os.listdir(self.claims_root):
                if not fname.endswith(".json"):
                    continue
                claim = self.read_claim(fname[:-5])
                if isinstance(claim, dict) and str(claim.get("run_id") or "") == run_id:
                    return claim
        except Exception:
            return None
        return None

    def list_claims(self, status: str | None = None) -> list[dict[str, Any]]:
        if not os.path.isdir(self.claims_root):
            return []
        claims: list[dict[str, Any]] = []
        try:
            for fname in os.listdir(self.claims_root):
                if not fname.endswith(".json"):
                    continue
                claim = self.read_claim(fname[:-5])
                if not isinstance(claim, dict):
                    continue
                if status is not None and str(claim.get("status") or "") != status:
                    continue
                claims.append(claim)
        except Exception:
            return claims
        claims.sort(
            key=lambda c: (
                c.get("claimed_at") or c.get("worker_started_at") or c.get("last_heartbeat_at") or ""
            ),
            reverse=True,
        )
        return claims

    def find_active_claim(self, status: str = "RUNNING") -> dict[str, Any] | None:
        candidates = self.list_claims(status=status)
        if not candidates:
            return None
        return candidates[0]

    def evaluate_orphaned_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        claim_status = str(claim.get("status") or "")
        if claim_status != "RUNNING":
            return {"orphaned": False}
        interval = claim.get("heartbeat_interval_seconds")
        if interval is None:
            return {"orphaned": False}
        interval_seconds = max(1, self._coerce_int(interval, self.heartbeat_interval_seconds))
        timeout_seconds = self.heartbeat_timeout_seconds(interval_seconds)
        heartbeat_raw = str(claim.get("last_heartbeat_at") or "").strip()
        if not heartbeat_raw:
            return {"orphaned": False}
        heartbeat_at = parse_iso_datetime(heartbeat_raw)
        if heartbeat_at is None:
            return {
                "orphaned": True,
                "error_code": "CLAIM_HEARTBEAT_INVALID",
                "message": "RUNNING claim 的 heartbeat 时间格式无效，状态无法确认。",
            }
        elapsed_seconds = (datetime.now(timezone.utc) - heartbeat_at).total_seconds()
        if elapsed_seconds <= timeout_seconds:
            return {"orphaned": False}
        run_id = str(claim.get("run_id") or "")
        preview_id = str(claim.get("preview_id") or "")
        return {
            "orphaned": True,
            "error_code": "EXECUTOR_RUN_ORPHANED",
            "message": (
                f"执行器运行疑似失联：run_id={run_id or 'unknown'} preview_id={preview_id or 'unknown'} "
                f"在 {int(elapsed_seconds)} 秒内未刷新 heartbeat（阈值 {timeout_seconds} 秒）。"
            ),
        }

    def _safe_claim_path(self, preview_id: str) -> str | None:
        if not self._valid_preview_id(preview_id):
            return None
        return os.path.join(self.claims_root, f"{preview_id}.json")

    @staticmethod
    def _valid_preview_id(preview_id: Any) -> bool:
        return bool(
            isinstance(preview_id, str)
            and preview_id not in {".", ".."}
            and _PREVIEW_ID_RE.fullmatch(preview_id) is not None
        )

    def _claim_relative_parts(self) -> tuple[str, ...] | None:
        relative = os.path.join(
            os.path.relpath(self.previews_root, self.project_root),
            os.path.basename(self.claims_root),
        )
        if os.path.isabs(relative):
            return None
        parts = tuple(part for part in relative.split(os.sep) if part)
        if not parts or any(part in {".", ".."} for part in parts):
            return None
        return parts

    def _open_claims_chain(self, *, create: bool = False) -> dict[str, Any]:
        parts = self._claim_relative_parts()
        if parts is None:
            return {"ok": False, "error_code": "CLAIM_ANCESTOR_UNSAFE"}
        fds: list[int] = []
        links: list[dict[str, Any]] = []
        try:
            root_before = os.stat(self.project_root, follow_symlinks=False)
            project_fd = os.open(
                self.project_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            fds.append(project_fd)
            project_stat = os.fstat(project_fd)
            if (
                not _trusted_directory(root_before)
                or not _trusted_directory(project_stat)
                or not _same_file_snapshot(root_before, project_stat)
            ):
                raise OSError("unsafe project root")
            links.append({
                "fd": project_fd,
                "parent_fd": None,
                "name": self.project_root,
                "metadata": project_stat,
            })
            parent_fd = project_fd
            for part in parts:
                try:
                    child_fd = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=parent_fd,
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, mode=0o700, dir_fd=parent_fd)
                    child_fd = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=parent_fd,
                    )
                fds.append(child_fd)
                child_stat = os.fstat(child_fd)
                if not _trusted_directory(child_stat):
                    raise OSError("unsafe claim ancestor")
                links.append({
                    "fd": child_fd,
                    "parent_fd": parent_fd,
                    "name": part,
                    "metadata": child_stat,
                })
                parent_fd = child_fd
            if not self._refresh_claims_chain_snapshot({"links": links}):
                raise OSError("unsafe claim ancestor snapshot")
            return {
                "ok": True,
                "fds": fds,
                "links": links,
                "claims_fd": parent_fd,
            }
        except OSError:
            for fd in reversed(fds):
                try:
                    os.close(fd)
                except OSError:
                    pass
            return {"ok": False, "error_code": "CLAIM_ANCESTOR_UNSAFE"}

    @staticmethod
    def _verify_claims_chain(opened: dict[str, Any]) -> bool:
        try:
            for link in opened["links"]:
                parent_fd = link["parent_fd"]
                name = link["name"]
                expected = link["metadata"]
                descriptor = os.fstat(link["fd"])
                current = os.stat(
                    name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                if (
                    not _trusted_directory(descriptor)
                    or not _trusted_directory(current)
                    or not _same_file_snapshot(expected, descriptor)
                    or not _same_file_snapshot(expected, current)
                ):
                    return False
            return True
        except OSError:
            return False

    @staticmethod
    def _refresh_claims_chain_snapshot(opened: dict[str, Any]) -> bool:
        """Establish a complete chain snapshot after intentional creation."""
        try:
            refreshed: list[os.stat_result] = []
            for link in opened["links"]:
                descriptor = os.fstat(link["fd"])
                current = os.stat(
                    link["name"],
                    dir_fd=link["parent_fd"],
                    follow_symlinks=False,
                )
                if (
                    not _trusted_directory(descriptor)
                    or not _trusted_directory(current)
                    or (descriptor.st_dev, descriptor.st_ino)
                    != (current.st_dev, current.st_ino)
                ):
                    return False
                refreshed.append(descriptor)
            for link, metadata in zip(opened["links"], refreshed):
                link["metadata"] = metadata
            return True
        except OSError:
            return False

    @staticmethod
    def _bounded_flock(fd: int, operation: int) -> None:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                fcntl.flock(fd, operation | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("claim lock unavailable")
                time.sleep(0.01)

    @staticmethod
    def _read_fd_complete(fd: int, expected_size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = expected_size
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                raise OSError("claim truncated during read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise OSError("claim grew during read")
        return b"".join(chunks)

    def _validate_claim_contract(
        self,
        value: Any,
        *,
        preview_id: str,
        expected_run_id: str | None = None,
    ) -> str | None:
        if not isinstance(value, dict):
            return "CLAIM_CONTRACT_NOT_OBJECT"
        keys = frozenset(value)
        if not _CLAIM_REQUIRED_FIELDS.issubset(keys):
            return "CLAIM_CONTRACT_INCOMPLETE"
        if not keys.issubset(_CLAIM_REQUIRED_FIELDS | _CLAIM_OPTIONAL_FIELDS):
            return "CLAIM_CONTRACT_FIELDS_INVALID"
        if value.get("schema_version") != EXECUTOR_RUN_CLAIM_SCHEMA_VERSION:
            return "CLAIM_SCHEMA_VERSION_INVALID"
        if value.get("preview_id") != preview_id:
            return "CLAIM_PREVIEW_ID_MISMATCH"
        run_id = value.get("run_id")
        if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
            return "CLAIM_RUN_ID_INVALID"
        if expected_run_id is not None and run_id != expected_run_id:
            return "CLAIM_RUN_ID_MISMATCH"
        for field in _CLAIM_STRING_FIELDS & keys:
            if not isinstance(value.get(field), str):
                return "CLAIM_CONTRACT_TYPES_INVALID"
        if value.get("project_root") != self.project_root:
            return "CLAIM_PROJECT_ROOT_MISMATCH"
        if value.get("status") not in {"RUNNING", "COMPLETED", "FAILED"}:
            return "CLAIM_STATUS_INVALID"
        if value.get("model") is not None and not isinstance(value.get("model"), str):
            return "CLAIM_CONTRACT_TYPES_INVALID"
        if value.get("model_source") is not None and not isinstance(value.get("model_source"), str):
            return "CLAIM_CONTRACT_TYPES_INVALID"
        for field in ("worker_pid", "heartbeat_interval_seconds", "heartbeat_timeout_seconds"):
            item = value.get(field)
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                return "CLAIM_CONTRACT_TYPES_INVALID"
        authority_fields = {"executor_authority_id", "admission_sha256"}
        if bool(keys & authority_fields) != authority_fields.issubset(keys):
            return "CLAIM_AUTHORITY_CONTRACT_INCOMPLETE"
        if authority_fields.issubset(keys):
            authority_id = value.get("executor_authority_id")
            admission_sha256 = value.get("admission_sha256")
            if (
                type(authority_id) is not str
                or _AUTHORITY_ID_RE.fullmatch(authority_id) is None
                or type(admission_sha256) is not str
                or _SHA256_RE.fullmatch(admission_sha256) is None
            ):
                return "CLAIM_AUTHORITY_CONTRACT_INVALID"
        work_fields = {"work_item_id", "task_version", "attempt_id", "artifact_refs"}
        if bool(keys & work_fields) != work_fields.issubset(keys):
            return "CLAIM_WORK_TARGET_INCOMPLETE"
        if work_fields.issubset(keys):
            target = {field: value[field] for field in work_fields}
            if optional_work_item_reference_rejections(target):
                return "CLAIM_WORK_TARGET_INVALID"
        for field in {"blockers", "warnings"} & keys:
            items = value.get(field)
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                return "CLAIM_CONTRACT_TYPES_INVALID"
        return None

    def _coerce_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default


def parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
