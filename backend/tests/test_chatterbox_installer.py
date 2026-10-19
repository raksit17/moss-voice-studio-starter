"""Regression tests for Python 3.14 compatibility installer, without GPU/network."""
import csv
import io
import zipfile
from pathlib import Path

import pytest

from scripts.install_chatterbox import conditional_pkuseg, hash_record, patch_wheel


PREFIX = "chatterbox_tts-0.1.7.dist-info/"
METADATA = PREFIX + "METADATA"
RECORD = PREFIX + "RECORD"
CODE = "chatterbox/tts_turbo.py"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_marker_skips_only_optional_chinese_dependency(newline):
    headers = newline.join([
        "Metadata-Version: 2.2",
        "Name: chatterbox-tts",
        "Version: 0.1.7",
        "Requires-Dist: torch>=2.9.0; python_version >= '3.14'",
        "Requires-Dist: spacy-pkuseg",
        "Requires-Dist: soundfile",
        "",
        "",
    ]).encode("utf-8")
    updated = conditional_pkuseg(headers).decode("utf-8")
    assert updated.count('Requires-Dist: spacy-pkuseg; python_version < "3.14"') == 1
    assert "Requires-Dist: soundfile" in updated
    assert "Requires-Dist: torch>=2.9.0" in updated
    assert not updated.rstrip().endswith("Requires-Dist: spacy-pkuseg")


@pytest.mark.parametrize("metadata", [
    b"Metadata-Version: 2.2\nName: unrelated\n",
    b"Requires-Dist: spacy-pkuseg\nRequires-Dist: spacy-pkuseg\n",
])
def test_unexpected_metadata_is_rejected(metadata):
    with pytest.raises(ValueError, match="not found exactly once"):
        conditional_pkuseg(metadata)


def test_wheel_rewrites_only_metadata_and_record(tmp_path: Path):
    src = tmp_path / "chatterbox_tts-0.1.7-py3-none-any.whl"
    target_dir = tmp_path / "patched"
    target_dir.mkdir()
    dest = target_dir / src.name
    metadata = b"Metadata-Version: 2.2\nName: chatterbox-tts\nRequires-Dist: spacy-pkuseg\n"
    code = b"# Official model source remains unchanged\n"
    records = f"{METADATA},,\n{CODE},,\n{RECORD},,\n".encode("utf-8")
    with zipfile.ZipFile(src, "w") as original:
        original.writestr(METADATA, metadata)
        original.writestr(CODE, code)
        original.writestr(RECORD, records)
    patch_wheel(src, dest)
    with zipfile.ZipFile(dest) as patched:
        assert patched.read(CODE) == code
        output_metadata = patched.read(METADATA)
        assert b'python_version < "3.14"' in output_metadata
        rows = {row[0]: row for row in csv.reader(io.StringIO(patched.read(RECORD).decode()))}
        assert rows[METADATA][1:] == list(hash_record(output_metadata))
        assert rows[RECORD][1:] == ["", ""]
        assert patched.testzip() is None
