"""Run F5 Thai in a short-lived separate process after unloading MOSS."""
import json
import subprocess
import sys
import wave
from pathlib import Path

from ...config import settings


def synthesize_f5(text: str, package: dict, output: Path) -> None:
    if package['runtime'] != 'f5-tts-th' or package['method'] != 'zero_shot':
        raise RuntimeError('Unsupported voice package runtime')
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'text': text,
        'reference_wav': str(Path(package['package_dir']) / 'reference.wav'),
        'reference_text': package['transcript'],
        'output_wav': str(output),
    }
    executable = settings.f5_python.strip() or sys.executable
    try:
        proc = subprocess.run(
            [executable, '-m', 'app.voice_models.f5_worker'],
            input=json.dumps(payload, ensure_ascii=False),
            text=True, capture_output=True, check=False,
            timeout=settings.f5_timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError('F5_PYTHON not found; configure the F5 virtual environment') from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('F5 worker exceeded timeout') from exc

    if proc.returncode != 0:
        raise RuntimeError('F5 worker failed (install requirements-f5-thai.txt): ' +
                           (proc.stderr.strip() or proc.stdout.strip())[-350:])
    try:
        with wave.open(str(output), 'rb') as wav:
            if not wav.getnframes():
                raise ValueError('Empty F5 output')
    except (FileNotFoundError, ValueError, wave.Error) as exc:
        raise RuntimeError('F5 did not produce a valid WAV file') from exc
