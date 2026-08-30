"""Private, symlink-safe local state files for CodeCanopy."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import TextIO


def private_path(path: str | Path) -> Path:
    """Return a lexical absolute path without resolving symlinked components."""
    return Path(os.path.abspath(Path(path).expanduser()))


def _open_parent(path: str | Path, *, create: bool) -> tuple[Path, int]:
    """Open each ancestor as a no-follow directory and return its descriptor."""
    target = private_path(path)
    if not target.name:
        raise ValueError(f"state path must name a file: {target}")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target.anchor or ".", flags)
    try:
        for component in target.parts[1:-1]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except OSError as error:
                try:
                    metadata = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    if not create:
                        raise error
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                    child = os.open(component, flags, dir_fd=descriptor)
                else:
                    # macOS exposes root-owned aliases such as /var -> /private/var.
                    # User-controlled directory links remain outside the state boundary.
                    if not stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0:
                        raise error
                    child = os.open(component, flags & ~getattr(os, "O_NOFOLLOW", 0), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return target, descriptor
    except Exception:
        os.close(descriptor)
        raise


def ensure_private_directory(path: str | Path) -> Path:
    """Create or validate one owner-only directory without following symlinks."""
    target = private_path(path)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        target, parent = _open_parent(target, create=True)
        try:
            try:
                descriptor = os.open(target.name, flags, dir_fd=parent)
            except FileNotFoundError:
                os.mkdir(target.name, 0o700, dir_fd=parent)
                descriptor = os.open(target.name, flags, dir_fd=parent)
        finally:
            os.close(parent)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"state path is not a directory: {target}")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise ValueError(f"state directory is not owned by the current user: {target}")
        os.fchmod(descriptor, 0o700)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700:
            raise ValueError(f"state directory permissions are not private: {target}")
        return target
    except ValueError:
        raise
    except OSError as error:
        raise ValueError(f"refusing unsafe state directory: {target}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def open_private(path: str | Path, *, append: bool) -> TextIO:
    """Open one owner-only regular file without following any path symlink."""
    flags = os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= os.O_RDWR if append else os.O_RDONLY
    if append:
        flags |= os.O_APPEND | os.O_CREAT
    try:
        target, parent = _open_parent(path, create=append)
        try:
            descriptor = os.open(target.name, flags, 0o600, dir_fd=parent)
        finally:
            os.close(parent)
    except OSError as error:
        raise ValueError(f"refusing unsafe state file: {private_path(path)}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"state path is not a regular file: {target}")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise ValueError(f"state file is not owned by the current user: {target}")
        if metadata.st_nlink != 1:
            raise ValueError(f"state file has multiple hard links: {target}")
        if append:
            os.fchmod(descriptor, 0o600)
        elif stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError(f"state file permissions are not private: {target}")
        return os.fdopen(descriptor, "a+" if append else "r", encoding="utf-8")
    except Exception:
        os.close(descriptor)
        raise


def read_regular_limited(path: str | Path, limit: int) -> bytes:
    """Read one descriptor-pinned regular file without following path symlinks."""
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        target, parent = _open_parent(path, create=False)
        try:
            descriptor = os.open(target.name, flags, dir_fd=parent)
        finally:
            os.close(parent)
    except OSError as error:
        raise ValueError(f"refusing unsafe input file: {private_path(path)}") from error
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
