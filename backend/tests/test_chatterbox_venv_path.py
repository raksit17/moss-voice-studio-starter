"""Keep virtualenv executable paths intact when launched from the API.

A Linux virtualenv's bin/python is typically a symlink to the base interpreter.
Calling Path.resolve() loses the venv's site-packages (ModuleNotFoundError).
"""
from pathlib import Path
import sys

import pytest

from app import chatterbox_runtime
from app.config import settings


@pytest.fixture
def symlinked_venv_python(tmp_path):
    executable = tmp_path / ".venv-chatterbox" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    try:
        executable.symlink_to(Path(sys.executable).resolve())
    except (OSError, NotImplementedError):
        pytest.skip("Cannot create a Python interpreter symlink on this host")
    assert executable.is_file()
    assert executable.resolve() != executable
    return executable


def test_preserves_absolute_venv_python_symlink(monkeypatch, symlinked_venv_python):
    monkeypatch.setattr(settings, "chatterbox_python", str(symlinked_venv_python))
    worker = chatterbox_runtime.ChatterboxRuntime()

    assert worker._python() == symlinked_venv_python
    assert worker.status()["python_found"] is True


def test_preserves_relative_venv_python_symlink(monkeypatch, symlinked_venv_python):
    monkeypatch.setattr(chatterbox_runtime, "BACKEND_DIR", symlinked_venv_python.parents[2])
    monkeypatch.setattr(settings, "chatterbox_python", ".venv-chatterbox/bin/python")

    assert chatterbox_runtime.ChatterboxRuntime()._python() == symlinked_venv_python
