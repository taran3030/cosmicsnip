"""
Security hardening for CosmicSnip.

Attack surface and mitigations
───────────────────────────────
1. Root execution
   Risk:  Any bug in this app becomes a privilege-escalation vector.
   Fix:   refuse_root() — hard exit if UID == 0.

2. Symlink attacks in temp directory
   Risk:  Attacker pre-creates a symlink in TEMP_DIR pointing at a sensitive
          file (e.g. /etc/shadow).  Our code follows it, chmod's it to 0600,
          or reads/writes over it.
   Fix:   check_no_symlink() before touching any discovered temp file.

3. Path traversal
   Risk:  A crafted filename could escape TEMP_DIR or SAVE_DIR
          (e.g. "../../.ssh/authorized_keys").
   Fix:   validate_path_within() resolves and checks relative_to().

4. Malformed / weaponised image files
   Risk:  A crafted PNG in TEMP_DIR triggers a Pillow or GdkPixbuf exploit
          before dimensions are checked.
   Fix:   validate_png_magic() checks the 8-byte PNG signature first.

5. Subprocess injection
   Risk:  Shell injection via user-controlled data passed to subprocess.
   Fix:   All subprocess calls use argument lists (no shell=True).  No
          user-controlled data ever reaches a subprocess argument.
          Enforced by audit — no changes needed here.

6. Unbounded memory
   Risk:  Oversized image causes OOM; unbounded annotation list grows forever.
   Fix:   MAX_IMAGE_WIDTH/HEIGHT in config (enforced in capture.py).
          MAX_UNDO_HISTORY in config (enforced in editor.py).
"""

import os
import sys
from pathlib import Path

from cosmicsnip.log import get_logger

log = get_logger("security")

# PNG file signature — first 8 bytes of every valid PNG.
_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def refuse_root() -> None:
    """
    Immediately exit if the process is running as root (UID 0).

    This app captures screens and writes to the user's home directory.
    It requires zero elevated privileges.  Running as root turns any
    future bug into a potential privilege escalation.
    """
    if os.getuid() == 0:
        log.critical(
            "CosmicSnip refuses to run as root.  "
            "Launch it as a normal user — no sudo or root shell."
        )
        sys.exit(1)
    log.debug("UID check passed: running as uid=%d", os.getuid())


def validate_path_within(path: str | Path, allowed_dir: str | Path) -> Path:
    """
    Resolve *path* and confirm it lives inside *allowed_dir*.

    Raises ValueError if the resolved path escapes the allowed directory.
    Returns the resolved Path on success.
    """
    resolved = Path(path).resolve()
    allowed  = Path(allowed_dir).resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError:
        raise ValueError(
            f"Path traversal blocked: '{resolved}' is outside '{allowed}'"
        )
    log.debug("Path OK: %s is within %s", resolved, allowed)
    return resolved


def check_no_symlink(path: str | Path) -> None:
    """
    Raise ValueError if *path* is a symbolic link.

    Prevents symlink-swap attacks where an attacker replaces a temp file
    with a symlink to a sensitive target before we chmod or read it.
    """
    if Path(path).is_symlink():
        raise ValueError(f"Symlink rejected (possible attack): {path}")
    log.debug("Symlink check passed: %s", path)


def validate_png_magic(path: str | Path) -> None:
    """
    Raise ValueError if the file at *path* does not begin with the 8-byte
    PNG magic number.

    Catches obviously wrong file types before handing them to Pillow or
    GdkPixbuf, reducing the risk of triggering image-decoder exploits.
    """
    try:
        with open(path, 'rb') as fh:
            header = fh.read(8)
    except OSError as exc:
        raise ValueError(f"Cannot read file for magic check: {path}: {exc}") from exc

    if header != _PNG_MAGIC:
        raise ValueError(
            f"File rejected — not a valid PNG (bad magic bytes): {path}"
        )
    log.debug("PNG magic OK: %s", path)
