"""Security hardening — path validation, symlink checks, root refusal.

Covers: root execution prevention, symlink attacks in temp dirs,
path traversal, malformed PNGs, and TOCTOU-safe file operations.
"""

import os
import stat
import sys
from pathlib import Path

from cosmicsnip.log import get_logger

log = get_logger("security")

_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def refuse_root() -> None:
    """Hard exit if running as root. This app needs zero privileges."""
    if os.getuid() == 0:
        log.critical("CosmicSnip refuses to run as root.")
        sys.exit(1)
    log.debug("UID check passed: running as uid=%d", os.getuid())


def validate_path_within(path: str | Path, allowed_dir: str | Path) -> Path:
    """Resolve path and confirm it's inside allowed_dir. Raises ValueError."""
    resolved = Path(path).resolve()
    allowed = Path(allowed_dir).resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError:
        raise ValueError(f"Path traversal blocked: '{resolved}' outside '{allowed}'")
    log.debug("Path OK: %s is within %s", resolved, allowed)
    return resolved


def check_no_symlink(path: str | Path) -> None:
    """Raise ValueError if path is a symlink."""
    if Path(path).is_symlink():
        raise ValueError(f"Symlink rejected: {path}")
    log.debug("Symlink check passed: %s", path)


def validate_png_magic(path: str | Path) -> None:
    """Raise ValueError if the file doesn't start with PNG magic bytes."""
    try:
        with open(path, 'rb') as fh:
            header = fh.read(8)
    except OSError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    if header != _PNG_MAGIC:
        raise ValueError(f"Not a valid PNG: {path}")
    log.debug("PNG magic OK: %s", path)


def open_no_follow(path: str | Path) -> int:
    """Open with O_NOFOLLOW | O_RDONLY. Returns fd (caller must close)."""
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        if exc.errno == 40:  # ELOOP
            raise ValueError(f"Symlink rejected: {path}") from exc
        raise ValueError(f"Cannot open {path}: {exc}") from exc

    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        raise ValueError(f"Not a regular file (mode={oct(st.st_mode)}): {path}")
    return fd


def fchmod_safe(fd: int, mode: int) -> None:
    """chmod via fd — immune to TOCTOU symlink swaps."""
    os.fchmod(fd, mode)


def validate_png_magic_fd(fd: int, path: str | Path) -> None:
    """Check PNG magic bytes from an open fd. Resets position after."""
    os.lseek(fd, 0, os.SEEK_SET)
    header = os.read(fd, 8)
    if header != _PNG_MAGIC:
        raise ValueError(f"Not a valid PNG: {path}")
    os.lseek(fd, 0, os.SEEK_SET)


def verify_dir_ownership(dir_path: Path) -> None:
    """Verify directory is owned by current user and isn't a symlink."""
    p = Path(dir_path)
    st = p.lstat()
    if stat.S_ISLNK(st.st_mode):
        raise ValueError(f"Directory is a symlink: {dir_path}")
    if not stat.S_ISDIR(st.st_mode):
        raise ValueError(f"Not a directory: {dir_path}")
    if st.st_uid != os.getuid():
        raise ValueError(f"Owned by uid={st.st_uid}, expected {os.getuid()}: {dir_path}")
