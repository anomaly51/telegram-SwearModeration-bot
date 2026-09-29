"""Snapshot the loaded release, independently of later pulls or process restarts."""

import argparse
import hashlib
import html
import json
import re
import socket
import subprocess
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
METADATA_FILE = ".build-info.json"


@dataclass(frozen=True)
class BuildInfo:
    version: str
    code_hash: str
    revision: str | None = None
    committed_at: str | None = None
    built_at: str | None = None
    modified: bool = False


def source_hash(root: Path) -> str:
    paths = set(root.glob("*.py"))
    for directory in ("database", "handlers", "utils"):
        paths.update((root / directory).rglob("*.py"))
    paths.update(root / name for name in ("pyproject.toml", "poetry.lock", "Dockerfile"))
    digest = hashlib.sha256()
    for path in sorted(paths):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def git_metadata(root: Path) -> tuple[str | None, str | None, bool]:
    if not (root / ".git").exists():
        return None, None, False
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%H%n%cI", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        revision, committed_at = result.stdout.strip().splitlines()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        return revision, committed_at, bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, None, False


def read_build_info(root: Path = ROOT) -> BuildInfo:
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    code_hash = source_hash(root)
    metadata = root / METADATA_FILE
    if metadata.exists():
        try:
            info = BuildInfo(**json.loads(metadata.read_text()))
            if info.code_hash == code_hash:
                return info
            # Mounted or edited code is no longer the code stamped into this image.
            return BuildInfo(version, code_hash, modified=True)
        except (OSError, TypeError, ValueError):
            pass
    revision, committed_at, modified = git_metadata(root)
    return BuildInfo(version, code_hash, revision, committed_at, modified=modified)


def write_build_info(root: Path, revision: str | None, committed_at: str | None) -> BuildInfo:
    if revision and not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
        raise ValueError("VCS_REF must be a full Git commit hash")
    if committed_at:
        parsed = datetime.fromisoformat(committed_at)
        if parsed.tzinfo is None:
            raise ValueError("VCS_DATE must include a timezone")
    if committed_at and not revision:
        raise ValueError("VCS_DATE requires VCS_REF")
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    info = BuildInfo(
        version,
        source_hash(root),
        revision or None,
        committed_at or None,
        built_at=datetime.now(UTC).isoformat(),
    )
    (root / METADATA_FILE).write_text(json.dumps(asdict(info), indent=2) + "\n")
    return info


def _format_date(value: str | None) -> str:
    if not value:
        return "нет данных"
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return "нет данных"
        return parsed.astimezone(ZoneInfo("Europe/Kyiv")).strftime("%d.%m.%Y %H:%M:%S")
    except ValueError:
        return "нет данных"


def format_admin_build_report(info: BuildInfo, started_at: datetime, instance: str) -> str:
    revision = html.escape(info.revision[:12]) if info.revision else "не передан при сборке"
    lines = [
        "🛠 <b>Версия работающего бота</b>",
        f"Версия: <code>{html.escape(info.version)}</code>",
        f"Коммит: <code>{revision}</code>",
        f"Дата коммита: {_format_date(info.committed_at)}",
        f"Сборка образа: {_format_date(info.built_at)}",
        f"Запуск процесса: {_format_date(started_at.isoformat())}",
        f"Отпечаток кода: <code>{html.escape(info.code_hash[:16])}</code>",
        f"Экземпляр: <code>{html.escape(instance)}</code>",
        "\nВремя — по Киеву. Запуск процесса не означает обновление кода.",
    ]
    if info.modified:
        lines.append("⚠️ Исходники изменены относительно коммита или сборки.")
    return "\n".join(lines)


# Freeze these values once; a git pull without restart must not advertise a new release.
RUNNING_BUILD = read_build_info()
PROCESS_STARTED_AT = datetime.now(UTC)
INSTANCE_NAME = socket.gethostname()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--commit", default="")
    parser.add_argument("--commit-date", default="")
    args = parser.parse_args()
    if args.write:
        write_build_info(ROOT, args.commit, args.commit_date)
    else:
        print(json.dumps(asdict(RUNNING_BUILD), ensure_ascii=False, indent=2))
