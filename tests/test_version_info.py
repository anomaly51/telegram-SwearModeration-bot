import json
import shutil
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from version_info import (
    METADATA_FILE,
    BuildInfo,
    format_admin_build_report,
    read_build_info,
    source_hash,
    write_build_info,
)


@pytest.fixture
def source_tree(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.4"\n')
    (tmp_path / "app.py").write_text('print("release one")\n')
    return tmp_path


def test_build_without_git_has_date_and_reproducible_fingerprint(source_tree):
    written = write_build_info(source_tree, None, None)
    loaded = read_build_info(source_tree)
    assert loaded == written
    assert loaded.built_at is not None
    assert loaded.revision is loaded.committed_at is None
    assert loaded.code_hash == source_hash(source_tree)
    # Credentials, logs and documentation are not part of the code fingerprint.
    (source_tree / ".env").write_text("BOT_TOKEN=never-export-this\n")
    (source_tree / "README.md").write_text("documentation")
    assert source_hash(source_tree) == loaded.code_hash


def test_build_arguments_are_preserved_without_git(source_tree):
    revision = "a" * 40
    committed_at = "2026-09-28T08:00:00+00:00"
    write_build_info(source_tree, revision, committed_at)
    info = read_build_info(source_tree)
    assert info.revision == revision
    assert info.committed_at == committed_at


def test_modified_image_does_not_claim_old_build_date(source_tree):
    write_build_info(source_tree, "a" * 40, "2026-09-28T08:00:00+00:00")
    (source_tree / "app.py").write_text('print("release two")\n')
    info = read_build_info(source_tree)
    assert info.modified
    assert info.built_at is info.revision is info.committed_at is None


def test_git_release_snapshot_does_not_change_after_pull(source_tree):
    if not shutil.which("git"):
        pytest.skip("git executable required")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=source_tree, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("add", ".")
    git("commit", "-qm", "Initial release")
    running = read_build_info(source_tree)
    assert running.revision == git("rev-parse", "HEAD")
    assert running.committed_at is not None
    assert not running.modified
    (source_tree / "app.py").write_text('print("release two")\n')
    git("add", ".")
    git("commit", "-qm", "Second release")
    updated = read_build_info(source_tree)
    assert running.revision != updated.revision
    assert running.code_hash != updated.code_hash


def test_report_distinguishes_commit_build_and_restart():
    info = BuildInfo(
        "0.1.4",
        "b" * 64,
        "a" * 40,
        committed_at="2026-09-26T08:00:00+00:00",
        built_at="2026-09-27T08:00:00+00:00",
    )
    report = format_admin_build_report(info, datetime(2026, 9, 28, tzinfo=UTC), "<instance>")
    assert "Дата коммита: 26.09.2026 11:00:00" in report
    assert "Сборка образа: 27.09.2026 11:00:00" in report
    assert "Запуск процесса: 28.09.2026 03:00:00" in report
    assert "&lt;instance&gt;" in report
    assert "a" * 12 in report
    assert "⚠️" in format_admin_build_report(
        replace(info, modified=True),
        datetime.now(UTC),
        "instance",
    )


def test_invalid_metadata_falls_back_safely(source_tree):
    (source_tree / METADATA_FILE).write_text(json.dumps({"unexpected": "value"}))
    info = read_build_info(source_tree)
    assert info.version == "0.1.4"
    assert info.revision is None


@pytest.mark.parametrize(
    "revision, date",
    [
        ("not-a-sha", ""),
        ("a" * 40, "2026-09-28"),
        (None, "2026-09-28T08:00:00+00:00"),
    ],
)
def test_build_rejects_misleading_metadata(source_tree, revision, date):
    with pytest.raises(ValueError):
        write_build_info(source_tree, revision, date)


def test_image_build_excludes_credentials():
    rules = Path(".dockerignore").read_text().splitlines()
    assert ".env" in rules and ".env.*" in rules
