
"""Run F5 Thai in a separate Python environment without loading MOSS."""

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

from ...config import settings


BACKEND_DIR = Path(__file__).resolve().parents[3]


def synthesize_f5(text: str, package: dict, output: Path) -> None:
    if package["runtime"] != "f5-tts-th" or package["method"] != "zero_shot":
        raise RuntimeError("Unsupported voice package runtime")

    output.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "text": text,
        "reference_wav": str(
            Path(package["package_dir"]) / "reference.wav"
        ),
        "reference_text": package["transcript"],
        "output_wav": str(output),
    }

    # Choose F5 Python from config, otherwise use the separate venv.
    configured_python = settings.f5_python.strip()

    if configured_python:
        executable_path = Path(configured_python).expanduser()
        if not executable_path.is_absolute():
            executable_path = BACKEND_DIR / executable_path
    else:
        executable_path = (
            BACKEND_DIR / ".venv-f5" / "Scripts" / "python.exe"
        )

    executable_path = executable_path.resolve()

    if not executable_path.is_file():
        raise RuntimeError(
            f"F5 Python executable not found: {executable_path}"
        )

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.run(
            [
                str(executable_path),
                "-m",
                "app.voice_models.f5_worker",
            ],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            check=False,
            cwd=str(BACKEND_DIR),
            env=env,
            timeout=settings.f5_timeout_seconds,
        )

    except FileNotFoundError as exc:
        raise RuntimeError(
            "F5_PYTHON not found; configure the F5 virtual environment"
        ) from exc

    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("F5 worker exceeded timeout") from exc

    if proc.returncode != 0:
        detail = (proc.stderr.strip() or proc.stdout.strip())[-2000:]
        raise RuntimeError(
            f"F5 worker failed (exit {proc.returncode}): {detail}"
        )

    try:
        with wave.open(str(output), "rb") as wav:
            if wav.getnframes() == 0:
                raise ValueError("Empty F5 output")

    except (FileNotFoundError, ValueError, wave.Error) as exc:
        raise RuntimeError(
            "F5 did not produce a valid WAV file"
        ) from exc
