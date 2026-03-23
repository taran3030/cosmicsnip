# CosmicSnip — Release Audit Log

This document provides a cumulative, append-only record of security reviews, risk
decisions, and compliance evidence for every release of CosmicSnip. It is designed
to support SOC 2 Type II, ISO 27001, and similar compliance frameworks that require
demonstrable change-management controls and continuous audit traceability.

Each release section records: what changed, who reviewed it, what checks were run,
what risks were accepted, and what conditions apply to those acceptances.

---

## Compliance Framework Mapping

| Control Area | SOC 2 Criterion | How CosmicSnip Addresses It |
|---|---|---|
| Change management | CC8.1 | Every release is tagged, changelogs maintained, audit log records review evidence |
| Risk assessment | CC3.2 | CISO risk acceptance table with severity, rationale, and review deadlines |
| Vulnerability management | CC7.1 | Bandit static analysis, pip-audit dependency scan, manual code review per release |
| Secure development | CC8.1 | No risky APIs (`eval`/`exec`/`shell=True`), path validation, symlink protection, root refusal |
| Monitoring & detection | CC7.2 | CI pipeline runs security + maintainability checks on every push/PR |
| Incident response | CC7.3 | SECURITY.md with private disclosure process, 72-hour acknowledgment SLA |
| Access control | CC6.1 | App refuses root execution, umask 0o077, temp dir ownership verification |
| Data integrity | CC6.1 | PNG magic-byte validation, image dimension limits, TOCTOU-safe file operations |

---

## Release: v1.0.4 (2026-03-22)

### Summary
Security-audited release with persistent overlay window reuse, full compliance
traceability, and maintainability CI pipeline.

### Changes from v1.0.2 (last published release)
- Overlay windows persist and are reused via `reconfigure()` instead of being
  created/destroyed per capture (COSMIC Wayland cannot safely destroy layer-shell surfaces)
- Removed `DBusActivatable=true` from packaged desktop entry and source installer
  (caused COSMIC session crash)
- Removed Pillow dependency — all image handling uses native GdkPixbuf
- Added `CONTRIBUTING.md`, expanded `SECURITY.md`
- AppStream metadata: OARS content rating, screenshots section, developer contact
- Desktop entry: added `TryExec` for freedesktop.org compliance
- Build/install scripts hardened with file existence checks and idempotent PATH setup
- Maintainability audit script and CI job added
- Unused `Callable` import removed
- All version/date metadata synced

### Security Checks Performed
| Check | Tool | Result |
|-------|------|--------|
| Static analysis | `bandit -q -r cosmicsnip` | PASS — no findings |
| Dependency advisories | `pip-audit` | PASS — no known vulnerabilities (`dbus-python` skipped: distro-managed) |
| Risky API scan | `rg eval/exec/os.system/shell=True` | PASS — none found |
| Desktop entry validation | `desktop-file-validate` | PASS |
| AppStream validation | `appstreamcli validate --no-net` | PASS (1 pedantic notice: uppercase in component ID) |
| Python compilation | `py_compile` + `compileall` | PASS |
| Complexity analysis | `radon cc -s` | Highest: `load_config` C(16), `_capture_cosmic` C(12) — acceptable for I/O-heavy functions |
| Duplication analysis | `jscpd` | 0.76% (18 lines) — overlay/fallback input setup, accepted |
| Dead code scan | `vulture --min-confidence 80` | 1 finding: unused `Callable` import — FIXED |

### Manual Security Review
- No `eval()`, `exec()`, `os.system()`, or `shell=True` in runtime code
- Subprocess calls use argument lists with timeout guards (`capture.py`, `clipboard.py`)
- Path/symlink hardening verified in all critical flows:
  - `validate_path_within()` in crop and temp cleanup
  - `open_no_follow()`, `validate_png_magic_fd()`, `fchmod_safe()` in capture ingestion
  - `is_save_path_blocked()` on Save As
- Root execution refused at startup
- Process umask `0077`, temp dir ownership verified
- Log files created with `0600` permissions

### Risk Acceptance Decisions

| ID | Issue | Severity | Decision | Rationale | Review By |
|----|-------|----------|----------|-----------|-----------|
| 4.1 | Ghost surfaces on monitor topology change | LOW | ACCEPT | Platform constraint (COSMIC layer-shell); restart guidance provided | 2026-06-30 |
| 4.2 | Keyboard shortcut not bound | LOW | ACCEPT | Usability only, no security impact | — |
| 4.3 | No automated test suite | MEDIUM | ACCEPT | Manual QA gate required per release; headless Wayland testing infeasible | 2026-06-30 |
| 4.5 | Monitor identity assumption in reconfigure | HIGH | ACCEPT | Safe fallback to new creation; no privilege escalation vector | 2026-06-30 |
| 4.6 | Ghost accumulation over long sessions | MEDIUM | ACCEPT | Known platform tradeoff; documented in release notes | 2026-06-30 |
| 4.9 | `pycairo` not in pyproject.toml | MEDIUM | ACCEPT | Distro-scope only; `python3-cairo` in deb deps | — |
| 4.11 | Overlay/fallback code duplication | LOW | ACCEPT | 0.76%; refactor risk exceeds value | — |
| DBus | Tray accepts calls from any session-bus client | LOW | ACCEPT | Standard StatusNotifierItem behavior; same-user session-bus scope | — |
| Deps | `dbus-python` not auditable via pip-audit | LOW | ACCEPT | Distro-managed; not a confirmed vulnerability | — |

### Resolved Issues (closed this release)
- **4.4** `DBusActivatable=true` in source installer — FIXED (removed from `install.sh`)
- **4.7** Changelog/code behavior mismatch — FIXED (synced descriptions)
- **4.8** Version/date metadata drift — FIXED (all files synced to 2026-03-22)
- **4.10** Empty audit evidence log — FIXED (three audit passes recorded)
- **4.12** Unused `Callable` import — FIXED (removed)

### Release Authority
Release authorized under conditional risk acceptance for items 4.1, 4.3, 4.5,
and 4.6, with mandatory review checkpoint on **2026-06-30**.

---

## Release: v1.0.2 (2026-03-21)

### Summary
Distro-submission polish release. Professional documentation, removed Pillow
dependency, AppStream/desktop entry compliance, contributor guide.

### Security Checks Performed
- `bandit -q -r cosmicsnip` — PASS
- `pip-audit` — PASS
- `desktop-file-validate` — PASS
- `appstreamcli validate --no-net` — PASS
- Python compile checks — PASS

### Known Issues at Release
- `DBusActivatable=true` in desktop entry — caused session crash (fixed in v1.0.4)
- Overlay window pooling created ghost surfaces (fixed in v1.0.4)

### Risk Acceptance
No formal risk acceptance process was in place for this release.

---

## Release: v1.0.1 (2026-03-21)

### Summary
Overlay reliability, security hardening, and repository polish.

### Changes
- Overlay window reuse across captures
- Per-monitor overlay for single-monitor setups
- Path/symlink hardening: ancestry checks, symlink rejection in temp cleanup
- Added `SECURITY.md`

### Security Checks Performed
- `bandit -q -r cosmicsnip` — PASS
- Python compile checks — PASS

### Risk Acceptance
No formal risk acceptance process was in place for this release.

---

## Release: v1.0.0 (2026-03-16)

### Summary
First stable release.

### Features
- Libadwaita editor UI with pen, highlighter, arrow, rectangle tools
- System tray icon via DBus StatusNotifierItem
- Persistent app lifecycle between snips
- Out-of-bounds annotation with auto-trim transparent PNG output
- Multi-monitor layer-shell overlays with shared selection state
- GTK4 native clipboard support

### Security Controls (initial)
- Root execution refusal
- Process umask `0077`
- Temp directory ownership verification
- `O_NOFOLLOW` symlink rejection
- PNG magic-byte validation
- Image dimension limits
- FD-based `fchmod` for TOCTOU safety
- Save-path blocking for system directories
- No `shell=True` subprocess calls
- Rotating logs with `0600` permissions

### Risk Acceptance
No formal risk acceptance process was in place for this release.

---

## Audit Process

### Per-Release Checklist
1. Run `bandit -q -r cosmicsnip` — must be clean
2. Run `pip-audit` against pinned dependencies — must be clean
3. Run `desktop-file-validate` and `appstreamcli validate --no-net` — must pass
4. Run `python3 -m compileall -q cosmicsnip` — must pass
5. Run `./scripts/audit-maintainability.sh cosmicsnip` — review findings
6. Grep for `eval`, `exec`, `os.system`, `shell=True` — must find none in app code
7. Verify `DBusActivatable` is not present in any desktop entry
8. Manual smoke test: 5+ consecutive captures on multi-monitor COSMIC Wayland
9. Record all findings and risk decisions in this log
10. Tag release only after all DO NOT ACCEPT items are resolved

### Conditional Acceptance Review
Items accepted with conditions must be reviewed by their stated deadline. If the
deadline passes without review, the item escalates to DO NOT ACCEPT for the next
release and must be resolved before shipping.

### Evidence Retention
- CI artifacts (bandit, pip-audit, maintainability reports) are retained per GitHub Actions policy
- This log is committed to the repository and versioned alongside the code
- Working audit documents (`CODEX_AUDIT_*.md`) are gitignored but retained locally
