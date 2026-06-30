import contextlib
import fcntl
import json
import os
import subprocess
import sys

from runner.runner_paths import user_config_dir


class ServiceLifecycleStore:
    METADATA_FILENAME = "service.json"
    PID_FILENAME = "service.pid"
    LOG_FILENAME = "service.log"
    LOCK_FILENAME = "service.lock"

    def __init__(self, project_path: str):
        self._project_path = project_path

    @property
    def project_path(self) -> str:
        return self._project_path

    def service_dir(self) -> str:
        return os.path.join(user_config_dir(), "runtime", "service")

    def paths(self) -> dict[str, str]:
        service_dir = self.service_dir()
        return {
            "dir": service_dir,
            "metadata": os.path.join(service_dir, self.METADATA_FILENAME),
            "pid": os.path.join(service_dir, self.PID_FILENAME),
            "log": os.path.join(service_dir, self.LOG_FILENAME),
            "lock": os.path.join(service_dir, self.LOCK_FILENAME),
        }

    def ensure_dir(self) -> dict[str, str]:
        paths = self.paths()
        os.makedirs(paths["dir"], exist_ok=True)
        return paths

    def read_metadata(self) -> dict[str, object] | None:
        metadata_path = self.paths()["metadata"]
        if not os.path.isfile(metadata_path):
            return None
        try:
            with open(metadata_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @contextlib.contextmanager
    def _lock(self):
        paths = self.ensure_dir()
        lock_path = paths["lock"]
        with open(lock_path, "w") as lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)

    def write_metadata(self, payload: dict[str, object]) -> None:
        with self._lock():
            paths = self.paths()
            tmp_meta = paths["metadata"] + ".tmp"
            tmp_pid = paths["pid"] + ".tmp"
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_meta, paths["metadata"])
            with open(tmp_pid, "w", encoding="utf-8") as f:
                f.write(str(payload.get("pid", "")))
            os.replace(tmp_pid, paths["pid"])

    def clear_metadata(self) -> None:
        with self._lock():
            paths = self.paths()
            for key in ("metadata", "pid"):
                try:
                    os.remove(paths[key])
                except FileNotFoundError:
                    continue

    @staticmethod
    def is_pid_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def read_process_cmdline(pid: int) -> str | None:
        parts = ServiceLifecycleStore.read_process_cmdline_parts(pid)
        return " ".join(parts) if parts else None

    @staticmethod
    def read_process_cmdline_parts(pid: int) -> list[str] | None:
        if pid <= 0:
            return None
        try:
            if sys.platform == "linux":
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    raw = f.read()
                parts = raw.rstrip(b"\x00").split(b"\x00")
                decoded = [p.decode(sys.getfilesystemencoding(), errors="replace") for p in parts if p]
                return decoded if decoded else None
            elif sys.platform == "darwin":
                result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    capture_output=True,
                    timeout=5,
                    text=True,
                )
                if result.returncode != 0 or not result.stdout.strip():
                    return None
                return result.stdout.strip().split()
            else:
                return None
        except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            return None

    @staticmethod
    def iter_process_ids() -> list[int]:
        if sys.platform == "linux":
            try:
                return sorted(
                    int(name)
                    for name in os.listdir("/proc")
                    if name.isdigit()
                )
            except OSError:
                return []
        if sys.platform == "darwin":
            try:
                result = subprocess.run(
                    ["ps", "-axo", "pid="],
                    capture_output=True,
                    timeout=5,
                    text=True,
                )
            except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
                return []
            pids: list[int] = []
            for line in result.stdout.splitlines():
                try:
                    pids.append(int(line.strip()))
                except ValueError:
                    continue
            return sorted(pids)
        return []

    @staticmethod
    def pid_matches_metadata(
        pid: int,
        metadata: dict[str, object],
        *,
        is_pid_running=None,
        read_process_cmdline=None,
    ) -> bool | None:
        if is_pid_running is None:
            is_pid_running = ServiceLifecycleStore.is_pid_running
        if read_process_cmdline is None:
            read_process_cmdline = ServiceLifecycleStore.read_process_cmdline

        if not is_pid_running(pid):
            return False
        recorded_command = metadata.get("command")
        if not isinstance(recorded_command, list) or not recorded_command:
            return None
        cmdline = read_process_cmdline(pid)
        if cmdline is None:
            return None
        if "runner_cli.py" not in cmdline:
            return False
        if "--service-child" not in cmdline:
            return False
        project_root = metadata.get("project_root")
        if isinstance(project_root, str) and project_root not in cmdline:
            return False
        return True
