"""The provenance record must describe this repository, not the shell's cwd."""

from __future__ import annotations

from ridescore import run_record


def test_provenance_does_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    root = run_record._source_root()
    assert root is not None, "running from a source tree, so the repository should be found"
    assert run_record._lockfile_hash(root) is not None
    assert run_record._code_version(root)["commit"] is not None
