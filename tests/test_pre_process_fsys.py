"""Pre-process validator: .fsys output target must be a real FSYS with
exactly one model entry, plus PKX metadata when the inner entry is .pkx.
"""
import os

import pytest

from exporter.phases.pre_process.pre_process import (
    _validate_fsys_target,
    _validate_pkx_metadata,
)
from shared.helpers.logger import StubLogger

from helpers import build_fsys_archive


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


# ---------------------------------------------------------------------------
# _validate_fsys_target
# ---------------------------------------------------------------------------

def test_missing_file_rejected(tmp_path):
    with pytest.raises(ValueError, match="no file at"):
        _validate_fsys_target(str(tmp_path / "nope.fsys"), StubLogger())


def test_non_fsys_bytes_rejected(tmp_path):
    path = _write(tmp_path, "junk.fsys", b"NOTFSYS" + b"\x00" * 100)
    with pytest.raises(ValueError, match="FSYS"):
        _validate_fsys_target(path, StubLogger())


def test_zero_model_entries_rejected(tmp_path):
    archive = build_fsys_archive([
        {'file_type': 0x06, 'data': b"x" * 32, 'compressed': False, 'filename': 'a.ccd'},
    ])
    path = _write(tmp_path, "no_model.fsys", archive)
    with pytest.raises(ValueError, match="no model entries"):
        _validate_fsys_target(path, StubLogger())


def test_two_model_entries_rejected(tmp_path):
    archive = build_fsys_archive([
        {'file_type': 0x04, 'data': b"a" * 32, 'compressed': False, 'filename': 'a.dat'},
        {'file_type': 0x04, 'data': b"b" * 32, 'compressed': False, 'filename': 'b.dat'},
    ])
    path = _write(tmp_path, "two_models.fsys", archive)
    with pytest.raises(ValueError, match="contains 2 model entries"):
        _validate_fsys_target(path, StubLogger())


def test_one_dat_entry_accepted_returns_dat(tmp_path):
    archive = build_fsys_archive([
        {'file_type': 0x04, 'data': b"d" * 32, 'compressed': False, 'filename': 'one.dat'},
        {'file_type': 0x06, 'data': b"c" * 32, 'compressed': False, 'filename': 'col.ccd'},
    ])
    path = _write(tmp_path, "ok.fsys", archive)
    assert _validate_fsys_target(path, StubLogger()) == 'dat'


def test_one_pkx_entry_accepted_returns_pkx(tmp_path):
    archive = build_fsys_archive([
        {'file_type': 0x1E, 'data': b"p" * 32, 'compressed': False, 'filename': 'one.pkx'},
    ])
    path = _write(tmp_path, "okpkx.fsys", archive)
    assert _validate_fsys_target(path, StubLogger()) == 'pkx'


# ---------------------------------------------------------------------------
# _validate_pkx_metadata
# ---------------------------------------------------------------------------

class _FakeArm:
    def __init__(self, name, fmt=None):
        self.name = name
        self.type = 'ARMATURE'
        self._props = {}
        if fmt is not None:
            self._props['dat_pkx_format'] = fmt
    def get(self, key, default=None):
        return self._props.get(key, default)


class _FakeScene:
    def __init__(self, objects):
        self.objects = objects


class _FakeContext:
    def __init__(self, objects):
        self.scene = _FakeScene(objects)


def test_dat_output_skips_pkx_check():
    ctx = _FakeContext([])
    _validate_pkx_metadata(ctx, 'dat', None, StubLogger())  # no error


def test_pkx_output_requires_metadata():
    ctx = _FakeContext([_FakeArm('Armature')])
    with pytest.raises(ValueError, match="dat_pkx_format"):
        _validate_pkx_metadata(ctx, 'pkx', None, StubLogger())


def test_pkx_output_with_metadata_passes():
    ctx = _FakeContext([_FakeArm('Armature', fmt='XD')])
    _validate_pkx_metadata(ctx, 'pkx', None, StubLogger())  # no error


def test_fsys_pkx_output_requires_metadata():
    ctx = _FakeContext([_FakeArm('Armature')])
    with pytest.raises(ValueError, match="dat_pkx_format"):
        _validate_pkx_metadata(ctx, 'fsys', 'pkx', StubLogger())


def test_fsys_dat_output_skips_pkx_check():
    ctx = _FakeContext([_FakeArm('Armature')])
    _validate_pkx_metadata(ctx, 'fsys', 'dat', StubLogger())  # no error


def test_pkx_output_no_armature_rejected():
    ctx = _FakeContext([])
    with pytest.raises(ValueError, match="no armature"):
        _validate_pkx_metadata(ctx, 'pkx', None, StubLogger())
