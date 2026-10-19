"""Install Chatterbox-Turbo on CPython 3.14 without the unavailable Chinese pkuseg wheel.

Uses the official PyPI chatterbox-tts 0.1.7 wheel. Only its local wheel METADATA is
patched to make the optional Chinese segmenter conditional on Python <3.14.
All inference/model source code is byte-for-byte unchanged; wheel RECORD is updated.
No edited wheels are published. On 3.10-3.13 use the upstream requirements.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "chatterbox-tts==0.1.7"
MIN_TORCH = "2.9.1"
CUDA_INDEX = "https://download.pytorch.org/whl/cu128"


def run_pip(*args: str) -> None:
    print("+", sys.executable, "-m pip", *args, flush=True)
    subprocess.run([sys.executable, "-m", "pip", *args], check=True)


def conditional_pkuseg(metadata: bytes) -> bytes:
    """Return PyPI wheel METADATA with pkuseg skipped only on Python >=3.14."""
    content = metadata.decode("utf-8")
    pattern = r"(?m)^Requires-Dist: spacy[-_]pkuseg[^\S\r\n]*\r?$"
    if len(re.findall(pattern, content)) != 1:
        raise ValueError(
            "Unexpected Chatterbox wheel metadata: unmodified spacy-pkuseg "
            "requirement not found exactly once. Refusing to patch a changed release."
        )
    return re.sub(
        pattern,
        'Requires-Dist: spacy-pkuseg; python_version < "3.14"',
        content,
        count=1,
    ).encode("utf-8")


def hash_record(content: bytes) -> tuple[str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode("ascii")
    return "sha256=" + digest, str(len(content))


def patch_wheel(original: Path, patched: Path) -> None:
    with zipfile.ZipFile(original) as wheel:
        entries = {name: wheel.read(name) for name in wheel.namelist()}
        info = wheel.infolist()
    metadatas = [p for p in entries if p.endswith(".dist-info/METADATA")]
    records = [p for p in entries if p.endswith(".dist-info/RECORD")]
    if len(metadatas) != 1 or len(records) != 1:
        raise ValueError("Expected exactly one wheel METADATA and RECORD")
    metadata_name, record_name = metadatas[0], records[0]
    entries[metadata_name] = conditional_pkuseg(entries[metadata_name])

    rows = list(csv.reader(io.StringIO(entries[record_name].decode("utf-8"))))
    updates = 0
    for row in rows:
        if row[0] == metadata_name:
            row[1], row[2] = hash_record(entries[metadata_name])
            updates += 1
        if row[0] == record_name:
            row[1], row[2] = "", ""
    if updates != 1:
        raise ValueError("Wheel RECORD did not contain a unique METADATA entry")
    out = io.StringIO(newline="")
    csv.writer(out, lineterminator="\n").writerows(rows)
    entries[record_name] = out.getvalue().encode("utf-8")

    with zipfile.ZipFile(patched, "w") as target:
        for member in info:
            target.writestr(member, entries[member.filename])

    with zipfile.ZipFile(patched) as check:
        assert check.testzip() is None
        assert b'python_version < "3.14"' in check.read(metadata_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Chatterbox-Turbo in this isolated Python venv")
    parser.add_argument("--cpu", action="store_true", help="Install CPU PyTorch instead of CUDA 12.8")
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error("Chatterbox requires Python 3.10+")
    if sys.version_info >= (3, 15):
        parser.error("This compatibility installer is only validated through Python 3.14")
    print(f"Chatterbox setup for Python {sys.version.split()[0]}", flush=True)
    run_pip("install", "--upgrade", "pip")

    if sys.version_info < (3, 14):
        # Upstream pins torch 2.6; do not force newer torch against that pin.
        run_pip("install", "-r", str(ROOT / "requirements-chatterbox.txt"))
        return

    print("Python 3.14: using official Chatterbox 0.1.7 with optional Chinese pkuseg marker.", flush=True)
    # Pre-install matching CUDA wheels so pip does not replace them with CPU-only PyPI wheels.
    index = "https://download.pytorch.org/whl/cpu" if args.cpu else CUDA_INDEX
    run_pip("install", f"torch=={MIN_TORCH}", f"torchaudio=={MIN_TORCH}", "--index-url", index)

    with tempfile.TemporaryDirectory(prefix="chatterbox-cp314-") as root:
        directory = Path(root)
        original = directory / "original"
        original.mkdir()
        run_pip(
            "download", "--no-deps", "--only-binary=:all:",
            PACKAGE, "--dest", str(original),
        )
        wheels = list(original.glob("chatterbox_tts-0.1.7-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"Expected one official Chatterbox 0.1.7 wheel, got {len(wheels)}")
        target = directory / wheels[0].name
        patch_wheel(wheels[0], target)
        run_pip("install", str(target), "soundfile>=0.12")

    # A valid installation must not have unresolved requirements after our marker patch.
    run_pip("check")
    print("Chatterbox-Turbo Python 3.14 dependencies installed successfully.", flush=True)
    print("Next: run a model warm/load in the Studio Model Manager.", flush=True)


if __name__ == "__main__":
    main()
