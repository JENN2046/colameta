import hashlib
import json
import os
import tempfile

from runner.state_store import StateStore
from schemas.state import BuildRunnerState


class StaleStateError(Exception):
    def __init__(
        self,
        message: str,
        *,
        expected_updated_at: str | None = None,
        actual_updated_at: str | None = None,
    ):
        self.expected_updated_at = expected_updated_at
        self.actual_updated_at = actual_updated_at
        super().__init__(message)


class StateMutationGateway:
    def __init__(self, state_store: StateStore | None = None):
        self._state_store = state_store or StateStore()

    def save(
        self,
        state: BuildRunnerState,
        path: str,
        *,
        expected_updated_at: str | None = None,
        expected_hash: str | None = None,
    ) -> None:
        self._check_stale(path, expected_updated_at, expected_hash)
        self._state_store.save_state(state, path)

    def save_raw(
        self,
        state_dict: dict,
        path: str,
        *,
        expected_updated_at: str | None = None,
        expected_hash: str | None = None,
    ) -> None:
        self._check_stale(path, expected_updated_at, expected_hash)
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp-state-gateway-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state_dict, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    def _check_stale(
        self,
        path: str,
        expected_updated_at: str | None,
        expected_hash: str | None,
    ) -> None:
        if expected_updated_at is None and expected_hash is None:
            return
        if not os.path.isfile(path):
            raise StaleStateError(
                f"State file does not exist at: {path}",
                expected_updated_at=expected_updated_at,
            )
        with open(path, "r", encoding="utf-8") as f:
            current = json.load(f)
        if expected_updated_at is not None:
            actual = current.get("updated_at") if isinstance(current, dict) else None
            if actual != expected_updated_at:
                raise StaleStateError(
                    f"updated_at mismatch: expected {expected_updated_at}, got {actual}",
                    expected_updated_at=expected_updated_at,
                    actual_updated_at=actual,
                )
        if expected_hash is not None:
            content = json.dumps(current, sort_keys=True, ensure_ascii=False).encode("utf-8")
            actual_hash = hashlib.sha256(content).hexdigest()
            if actual_hash != expected_hash:
                raise StaleStateError(
                    f"content hash mismatch: expected {expected_hash}, got {actual_hash}",
                )
