"""Persistent, isolated Chatterbox-Turbo worker: one loaded model, many jobs."""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from .config import settings


BACKEND_DIR = Path(__file__).resolve().parents[1]


class ChatterboxRuntime:
    def __init__(self):
        self._lock = threading.RLock()
        self._process = None
        self._log = None
        self.state = "not_loaded"
        self.device = "not loaded"
        self.last_error = None

    def _python(self):
        specified = settings.chatterbox_python.strip()
        if specified:
            path = Path(specified).expanduser()
            if not path.is_absolute():
                path = BACKEND_DIR / path
        elif sys.platform == "win32":
            path = BACKEND_DIR / ".venv-chatterbox" / "Scripts" / "python.exe"
        else:
            path = BACKEND_DIR / ".venv-chatterbox" / "bin" / "python"
        return path.resolve()

    def status(self):
        # Do not acquire the inference lock: UI polls while a long job is running.
        proc = self._process
        alive = proc is not None and proc.poll() is None
        state = self.state if alive or proc is None else "error"
        error = self.last_error
        if proc is not None and not alive and not error:
            error = "Chatterbox worker exited unexpectedly; check logs"
        return {
            "engine": "chatterbox-turbo", "state": state,
            "ready": alive and state == "ready",
            "python_found": self._python().is_file(),
            "device": self.device, "error": error,
            "pid": proc.pid if alive else None,
            "log_path": str((settings.data_dir / "logs" / "chatterbox.log").resolve()),
        }

    def _close_locked(self):
        if self._process is not None:
            proc = self._process
            self._process = None
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            if proc.stdin:
                proc.stdin.close()
            if proc.stdout:
                proc.stdout.close()
        if self._log is not None:
            self._log.close()
            self._log = None

    def unload(self):
        with self._lock:
            self._close_locked()
            self.state = "not_loaded"
            self.device = "not loaded"
            self.last_error = None

    def _start_locked(self):
        if self._process is not None:
            if self._process.poll() is None:
                return
            # Reap a crashed worker before relaunching (close pipes and log).
            self._close_locked()
        executable = self._python()
        if not executable.is_file():
            raise RuntimeError(
                f"Chatterbox Python not found at {executable}. "
                "Install backend/requirements-chatterbox.txt in the separate .venv-chatterbox."
            )
        logs = settings.data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._log = open(logs / "chatterbox.log", "a", encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
            "CHATTERBOX_DEVICE": settings.chatterbox_device,
        })
        try:
            self._process = subprocess.Popen(
                [str(executable), "-u", "-m", "app.chatterbox_worker"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._log, cwd=str(BACKEND_DIR), env=env,
                text=True, encoding="utf-8", bufsize=1,
            )
        except Exception:
            self._close_locked()
            raise
        self.state = "loading"
        self.last_error = None

    def _call(self, payload):
        with self._lock:
            try:
                self._start_locked()
                assert self._process and self._process.stdin and self._process.stdout
                proc = self._process
                response_queue = queue.Queue(maxsize=1)

                def read_response():
                    try:
                        response_queue.put(proc.stdout.readline())
                    except Exception as error:
                        response_queue.put(error)

                reader = threading.Thread(target=read_response, daemon=True)
                reader.start()
                proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                proc.stdin.flush()
                try:
                    line = response_queue.get(timeout=settings.chatterbox_timeout_seconds)
                except queue.Empty as error:
                    raise TimeoutError("Chatterbox-Turbo exceeded its inference timeout") from error
                if isinstance(line, Exception):
                    raise line
                if not line:
                    raise RuntimeError("Chatterbox worker stopped; check chatterbox.log")
                result = json.loads(line)
                if not result.get("ok"):
                    raise RuntimeError(str(result.get("error", "Unknown Chatterbox error"))[:500])
                self.state = "ready"
                self.device = result.get("device", self.device)
                return result
            except Exception as error:
                self.last_error = str(error)[:500]
                self.state = "error"
                self._close_locked()
                raise

    def load(self):
        return self._call({"command": "load"})

    def synthesize(self, text: str, reference: Path | None, output: Path):
        output.parent.mkdir(parents=True, exist_ok=True)
        # A validated local reference path comes from the studio's own voice registry.
        self._call({
            "command": "synthesize", "text": text,
            "reference_wav": str(reference.resolve()) if reference else None,
            "output_wav": str(output.resolve()),
        })
        if not output.is_file() or output.stat().st_size <= 44:
            raise RuntimeError("Chatterbox did not produce a valid WAV")


runtime = ChatterboxRuntime()
