import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileTransactionOperation:
    kind: str
    rel_path: str
    abs_path: Path
    content: str | None = None


class FileTransactionError(RuntimeError):
    def __init__(self, message: str, *, receipt: dict[str, Any]):
        super().__init__(message)
        self.receipt = receipt


class FileTransaction:
    def __init__(self, project_root: str | Path, *, label: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.label = label
        self._operations: list[FileTransactionOperation] = []

    def write_text(self, rel_path: str, content: str) -> None:
        self._operations.append(
            FileTransactionOperation(
                kind="write_text",
                rel_path=rel_path,
                abs_path=(self.project_root / rel_path).resolve(),
                content=content,
            )
        )

    def delete_file(self, rel_path: str) -> None:
        self._operations.append(
            FileTransactionOperation(
                kind="delete_file",
                rel_path=rel_path,
                abs_path=(self.project_root / rel_path).resolve(),
            )
        )

    def commit(self) -> dict[str, Any]:
        transaction_id = self._transaction_id()
        preimages: dict[Path, dict[str, Any]] = {}
        applied: list[FileTransactionOperation] = []
        try:
            for operation in self._operations:
                operation.abs_path.relative_to(self.project_root)
                preimages.setdefault(operation.abs_path, self._read_preimage(operation.abs_path))
                self._apply_operation(operation)
                applied.append(operation)
        except Exception as exc:
            rollback_error = self._rollback(preimages, applied)
            receipt = self._receipt(
                transaction_id,
                status="rolled_back" if rollback_error is None else "rollback_failed",
                operation_count=len(self._operations),
                applied_count=len(applied),
                error_code="FILE_TRANSACTION_APPLY_FAILED",
                rollback_error=str(rollback_error) if rollback_error is not None else "",
            )
            raise FileTransactionError("文件事务应用失败，已尝试回滚。", receipt=receipt) from exc
        return self._receipt(
            transaction_id,
            status="committed",
            operation_count=len(self._operations),
            applied_count=len(applied),
            error_code="",
            rollback_error="",
        )

    def _transaction_id(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.label.encode("utf-8"))
        for operation in self._operations:
            digest.update(operation.kind.encode("utf-8"))
            digest.update(b"\0")
            digest.update(operation.rel_path.encode("utf-8"))
            digest.update(b"\0")
            if operation.content is not None:
                digest.update(hashlib.sha256(operation.content.encode("utf-8")).hexdigest().encode("ascii"))
        return f"ftx-{digest.hexdigest()[:16]}"

    def _receipt(
        self,
        transaction_id: str,
        *,
        status: str,
        operation_count: int,
        applied_count: int,
        error_code: str,
        rollback_error: str,
    ) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "transaction_id": transaction_id,
            "label": self.label,
            "status": status,
            "operation_count": operation_count,
            "applied_count": applied_count,
            "paths": [operation.rel_path for operation in self._operations],
            "content_included": False,
        }
        if error_code:
            receipt["error_code"] = error_code
        if rollback_error:
            receipt["rollback_error"] = rollback_error
        return receipt

    def _read_preimage(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"exists": False}
        if not path.is_file():
            raise IsADirectoryError(str(path))
        return {
            "exists": True,
            "content": path.read_text(encoding="utf-8"),
        }

    def _apply_operation(self, operation: FileTransactionOperation) -> None:
        if operation.kind == "write_text":
            assert operation.content is not None
            self._atomic_write_text(operation.abs_path, operation.content)
            return
        if operation.kind == "delete_file":
            if operation.abs_path.exists():
                operation.abs_path.unlink()
            return
        raise ValueError(f"unknown transaction operation: {operation.kind}")

    def _atomic_write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise

    def _rollback(
        self,
        preimages: dict[Path, dict[str, Any]],
        applied: list[FileTransactionOperation],
    ) -> Exception | None:
        try:
            for operation in reversed(applied):
                preimage = preimages.get(operation.abs_path, {"exists": False})
                if preimage.get("exists") is True:
                    self._atomic_write_text(operation.abs_path, str(preimage.get("content", "")))
                elif operation.abs_path.exists():
                    operation.abs_path.unlink()
        except Exception as exc:
            return exc
        return None
