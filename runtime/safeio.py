"""Private, symlink-safe local state files for CodeCanopy."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import TextIO


def private_path(path: str | Path) -> Path:
    """Resolve the parent, but never follow the final path component."""
    candidate = Path(path).expanduser()
    return candidate.parent.resolve() / candidate.name


def open_private(path: str | Path, *, append: bool) -> TextIO:
    """Open one owner-only regular file without following a final symlink."""
    target = private_path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    flags |= os.O_RDWR
    if append:
        flags |= os.O_APPEND | os.O_CREAT
    try:
        descriptor = os.open(target, flags, 0o600)
    except OSError as error:
        raise ValueError(f"refusing unsafe state file: {target}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"state path is not a regular file: {target}")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise ValueError(f"state file is not owned by the current user: {target}")
        if metadata.st_nlink != 1:
            raise ValueError(f"state file has multiple hard links: {target}")
        os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "a+" if append else "r", encoding="utf-8")
    except Exception:
        os.close(descriptor)
        raise


def read_regular_limited(path: str | Path, limit: int) -> bytes:
    """Read one descriptor-pinned regular file without following its final link."""
    target = private_path(path)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(target, flags)
    except OSError as error:
        raise ValueError(f"refusing unsafe input file: {target}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"input path is not a regular file: {target}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read(limit + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
