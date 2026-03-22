# Security Policy

This project handles screenshots, which may include sensitive personal or business data.  
Security is treated as a core feature, not a best-effort add-on.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x | Yes |
| < 1.0.0 | No |

## Reporting a Vulnerability

Please do **not** open public issues for security bugs.

Preferred:
1. GitHub repository Security tab -> **Report a vulnerability** (private advisory)

Fallback:
1. Email maintainer: `itssoup@users.noreply.github.com`
2. Subject: `CosmicSnip security report`
3. Include reproduction steps, affected version/commit, impact, and logs if relevant

## Disclosure Process

1. We acknowledge reports within 72 hours.
2. We triage and reproduce within 7 days when possible.
3. We coordinate a fix and release before public disclosure.
4. We credit reporters (if desired) in release notes.

## Security Boundaries and Threat Model

CosmicSnip is a local desktop app for COSMIC on Wayland.

Primary trust boundaries:
- File system paths (temp captures, save destinations, config files)
- Capture pipeline (`cosmic-screenshot` portal output)
- Clipboard output (`image/png`)
- Session DBus tray interface

Primary threats considered:
- Path traversal
- Symlink and TOCTOU file attacks
- Malformed image payloads
- Unsafe subprocess execution
- Privilege misuse

Out of scope:
- Physical access to an unlocked session
- Kernel/OS-level compromise
- Secrets management (the app does not manage credentials)

## Current Security Controls

- Refuses to run as root
- Process umask `0077`
- Temp directory ownership verification and restricted permissions
- Path validation to allowed directories
- `O_NOFOLLOW` for file-open symlink rejection
- PNG magic-byte validation and image dimension limits
- FD-based chmod (`fchmod`) to reduce TOCTOU risk
- Save-path blocking for sensitive system locations
- No shell-based subprocesses (`shell=True` not used)
- No telemetry or network exfiltration paths in app runtime
- Rotating local logs with `0600` permissions

## Secure Development Requirements

Before release:
1. Run static checks and compile checks
2. Verify no new risky APIs (`eval`, `exec`, `os.system`, `shell=True`)
3. Validate path and symlink protections still pass
4. Confirm desktop/autostart `Exec=` entries are expected and minimal
5. Re-test capture -> overlay -> save/copy flows on COSMIC Wayland

## User Security Notes

- Screenshots are stored locally as PNG files.
- Clipboard contents persist until replaced by another copy action.
- If your screenshots include secrets, clear clipboard and delete saved files after use.
