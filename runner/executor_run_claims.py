import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from runner._internal_utils import write_json_atomic


_PREVIEW_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


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
        path = self._safe_claim_path(preview_id)
        if path is None:
            return None
        if not os.path.isfile(path):
            return None
        root = os.path.realpath(self.claims_root)
        target = os.path.realpath(path)
        if not target.startswith(root + os.sep) and target != root:
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def write_claim(self, preview_id: str, claim: dict[str, Any]) -> None:
        write_json_atomic(self.claim_record_path(preview_id), claim)

    def acquire_claim(
        self,
        *,
        preview_id: str,
        artifact: dict[str, Any],
        provider: str,
        execution_mode: str,
    ) -> dict[str, Any]:
        os.makedirs(self.claims_root, exist_ok=True)
        claim_path = self.claim_record_path(preview_id)
        run_id = self.create_run_id()
        claimed_at = self.now_iso()
        artifact_model = str(artifact.get("model") or "").strip()
        artifact_model_source = str(artifact.get("model_source") or "").strip()
        claim_record = {
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
        try:
            fd = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return {"ok": False, "error_code": "CLAIM_EXISTS", "claim": self.read_claim(preview_id) or {}}
        except Exception:
            return {"ok": False, "error_code": "PREVIEW_CLAIM_FAILED"}
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(claim_record, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except Exception:
            try:
                os.unlink(claim_path)
            except Exception:
                pass
            return {"ok": False, "error_code": "PREVIEW_CLAIM_FAILED"}
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
        if not isinstance(preview_id, str) or not preview_id or not _PREVIEW_ID_RE.match(preview_id):
            return None
        root = os.path.realpath(self.claims_root)
        path = os.path.realpath(os.path.join(self.claims_root, f"{preview_id}.json"))
        if not path.startswith(root + os.sep) and path != root:
            return None
        return path

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
