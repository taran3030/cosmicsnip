# Security Policy

## Threat Model

CosmicSnip processes screenshots which may contain sensitive information
(passwords, personal data, financial info). The security design reflects this.

### What we protect against

| Threat | Mitigation |
|--------|-----------|
| Temp files leaking screenshot data | Written to `$XDG_RUNTIME_DIR/cosmicsnip/` with `0600` perms; auto-cleaned after 1 hour |
| Memory bomb via crafted image | Max dimensions enforced (`15360 × 8640`) before loading |
| Unbounded memory via annotations | Undo history capped at 200 entries |
| Shell injection via filenames | All subprocess calls use argument lists, never `shell=True` |
| Clipboard data exfiltration | Only `image/png` MIME type is written; no arbitrary clipboard content |
| Dependency supply chain | System packages only (`apt`); no PyPI downloads at runtime |

### What is explicitly out of scope

- Encrypting screenshots at rest (user's responsibility via full-disk encryption)
- Preventing the user's own screen from being captured
- Protecting against root-level compromise

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Current |

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Email: Open a GitHub Security Advisory via the repository's "Security" tab,
or contact the maintainer directly.

Response time target: 72 hours for acknowledgement, 7 days for patch.
