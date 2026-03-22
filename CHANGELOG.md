# Changelog

All notable changes to CosmicSnip are documented in this file.

## [1.0.1] - 2026-03-21

### Fixed
- Reused overlay windows across captures (including topology changes) to reduce hidden window accumulation risk.
- Enabled per-monitor overlay flow for single-monitor setups (instead of forced scaled fallback).
- Hardened security path checks:
  - save-path blocking now uses real path ancestry checks (not string prefix checks),
  - XDG path validation now uses ancestry checks,
  - temp cleanup validates path is inside temp root and rejects symlink targets.
- Added repository security policy and disclosure guidance (`SECURITY.md`).

### Changed
- README now prioritizes release `.deb` installation flow and links to policy/changelog docs.

## [1.0.0] - 2026-03-16

### Added
- First stable release.
- Libadwaita editor UI (HeaderBar, ToolbarView, ToastOverlay).
- System tray icon via DBus StatusNotifierItem.
- Persistent app lifecycle between snips.
- Out-of-bounds annotation with auto-trim transparent PNG output.
- Multi-monitor layer-shell overlays with shared selection state.
- Monitor detection with config caching.

## [0.2.0] - 2026-03-16

### Added
- Multi-monitor support via per-monitor overlays.
- Security hardening:
  - TOCTOU-safe temp file chmod path,
  - decompression bomb limits,
  - XDG path sanitization,
  - save path validation,
  - log/temp permission hardening.

## [0.1.0] - 2026-03-13

### Added
- Initial release.
- Screen capture via `cosmic-screenshot`.
- Drag-to-select overlay.
- Annotation editor with pen/highlighter/arrow/rectangle.
- GTK4 native clipboard support.
