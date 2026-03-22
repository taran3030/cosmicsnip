# CosmicSnip Full Audit and Improvement Proposal

Date: 2026-03-21
Audited against: `ARCHITECTURE.md` (v1.0.0, updated 2026-03-21) and current source tree in `cosmicsnip/`

## Scope and Method

- Read all runtime modules:
  - `cosmicsnip/app.py`
  - `cosmicsnip/capture.py`
  - `cosmicsnip/config.py`
  - `cosmicsnip/editor.py`
  - `cosmicsnip/log.py`
  - `cosmicsnip/monitors.py`
  - `cosmicsnip/overlay.py`
  - `cosmicsnip/security.py`
  - `cosmicsnip/tray.py`
- Reviewed packaging and install paths:
  - `pyproject.toml`
  - `build-deb.sh`
  - `install.sh`
  - `debian/*`
- Ran non-GUI sanity checks:
  - `python3 -m py_compile cosmicsnip/*.py`
  - `python3 -m compileall -q cosmicsnip`
- Tried GUI smoke (`test_layershell.py`) but environment had no live GDK display in this session, so compositor behavior was validated by code-path audit, not runtime visual verification.

## Executive Summary

CosmicSnip has a strong base architecture and is close to production quality, but three overlay issues are holding back reliability and UX:

1. Multi-monitor coordinate normalization is incomplete, which can cause apparent screen compression or wrong crop alignment on some layouts.
2. Overlay teardown is workaround-based and currently leaks window surfaces; this is the likely root cause of ghosting remnants.
3. Drag selection redraws full monitor surfaces every motion event, which is the likely root cause of selection lag.

If we execute the Phase 1 and Phase 2 changes below, the app should feel much closer to Windows Snipping Tool responsiveness while preserving Wayland safety constraints.

## Findings by Severity

## P0 - User-facing defects

### 1) Overlay coordinate model can break on non-zero/negative monitor origins

- Evidence:
  - `cosmicsnip/overlay.py:116-119` clamps `monitor_info.x/y` directly into screenshot pixel coordinates.
  - `cosmicsnip/overlay.py:201-206` maps canvas/image coordinates assuming monitor coords and screenshot coords share origin `(0,0)`.
  - `cosmicsnip/monitors.py:56-60` uses compositor logical coordinates (good), but no global origin normalization step before cropping combined screenshot.
- Impact:
  - On layouts with monitors left/up of primary (negative X/Y), regions can be shifted, clipped, or appear compressed/squashed in overlay.
- Proposal:
  - Introduce a `LayoutSpace` transform in `overlay.py`:
    - Compute `origin_x = min(m.x)` and `origin_y = min(m.y)` across monitors.
    - Convert monitor rects into screenshot pixel rects with `sx = mon.x - origin_x`, `sy = mon.y - origin_y`.
    - Use this normalized space for crop and selection callback.
  - Add tests for:
    - Single monitor at `(0,0)`.
    - Two monitors with left monitor at `(-1920,0)`.
    - Vertical stack with top monitor at `(0,-1080)`.

### 2) Ghost overlay persists because hide path does not fully unmap/close surfaces

- Evidence:
  - `cosmicsnip/overlay.py:333-349` `hide_all()` only swaps pixbuf, changes layer, sets opacity 0.
  - `cosmicsnip/overlay.py:210-218` draw path always paints opaque black plus dim overlay before selection logic.
  - `cosmicsnip/overlay.py:351-361` finalise/cancel does not close overlay windows.
  - `cosmicsnip/overlay.py:505-513` fallback path also only sets opacity and keeps window alive on cancel.
- Impact:
  - Ghosting can remain on screen.
  - Hidden windows accumulate across snips.
  - Potential compositor strain and intermittent behavior.
- Proposal:
  - Add an explicit hidden state (`_is_hidden`) in overlays; when true, draw fully transparent and skip base image paint.
  - Split teardown into two stages:
    - Stage A immediate: release keyboard, clear drawable content, mark hidden.
    - Stage B deferred: attempt `close()` on idle/timeout in controlled order; if compositor breaks, fall back to current opacity workaround.
  - Track and log overlay instance IDs and live-count to prove windows are not leaking between snips.

### 3) Selection lag from full-frame redraw on every drag-update

- Evidence:
  - `cosmicsnip/overlay.py:320-323` redraws every monitor window for each movement.
  - `cosmicsnip/overlay.py:210-263` each draw repaints full monitor image and dim pass.
  - `cosmicsnip/overlay.py:270-277` redraw called on every gesture update without throttle.
- Impact:
  - Noticeable latency while dragging selection, especially on 4K multi-monitor setups.
- Proposal:
  - Add motion throttling to max 60 FPS:
    - Store latest pointer in state.
    - Use one pending frame callback (`GLib.timeout_add(16, ...)`) instead of immediate `queue_draw()` per event.
  - Precompute dimmed base surfaces once per overlay on create/resize.
  - Redraw only dirty rectangles:
    - Union of previous and new selection rect (+ border padding).
  - Optional next step: use `Gtk.Picture` + overlay selection layer to offload image compositing.

## P1 - High priority stability and behavior gaps

### 4) `set_exclusive_zone(-1)` may cause workspace/layout side effects

- Evidence:
  - `cosmicsnip/overlay.py:141` calls `LayerShell.set_exclusive_zone(self, -1)` for transient screenshot overlay.
- Impact:
  - Can force compositor workarea recalculation on some shells, matching reports of "screen compressing down".
- Proposal:
  - For capture overlays, set exclusive zone to `0` (or remove call) to avoid reserving layout space.
  - Keep overlay on `OVERLAY` layer and all-edge anchored.

### 5) Config fallback rejects legitimate negative monitor coordinates

- Evidence:
  - `cosmicsnip/monitors.py:124-125` returns `None` if `x < 0 or y < 0`.
- Impact:
  - Saved layouts with left/top monitors cannot be used as fallback.
- Proposal:
  - Allow negative coordinates in config validation.
  - Add practical bounds check instead (for example absolute coordinate sanity).

### 6) Capture can choose stale screenshot file

- Evidence:
  - `cosmicsnip/capture.py:67-87` selects newest `Screenshot_*.png` after command, but does not enforce file creation time > command start.
- Impact:
  - In edge cases, wrong image can be picked when capture command returns without writing a new file.
- Proposal:
  - Record `t0 = time.time()` before subprocess call.
  - Accept only candidate files with `mtime >= t0 - epsilon`.
  - Optionally parse output path from `cosmic-screenshot` stdout if available.

## P2 - Maintainability and consistency

### 7) Documentation drift on undo behavior

- Evidence:
  - `README.md:35` says undo is unlimited.
  - `config.py:38` and `editor.py:381-382` cap at 200.
- Proposal:
  - Update docs to match code, or make max history configurable.

### 8) Save-path policy is hardcoded in editor instead of security/config

- Evidence:
  - `editor.py:570-577` blocked prefixes are inline.
- Proposal:
  - Move blocked path policy to `security.py` or `config.py` and reuse from editor.

### 9) Logging handler duplication risk on repeated setup

- Evidence:
  - `log.py:30-46` always adds handlers; no guard for existing handlers.
- Proposal:
  - Add idempotency check (`if root.handlers: return` or targeted dedupe).

### 10) API naming consistency mismatch

- Evidence:
  - `config.py:93` tool id is `"rectangle"`.
  - Annotation payload uses `"rect"` in `editor.py:345`.
- Proposal:
  - Standardize with one internal enum name and one serialized name map.

## Module Scorecard

- `overlay.py`: Functional but high-risk. Major refactor recommended (correctness + performance + lifecycle).
- `monitors.py`: Good base. Needs fallback validation fixes for negative coordinates.
- `capture.py`: Solid security posture. Needs stale-file guard and observability improvements.
- `editor.py`: Good UX foundation. Needs policy extraction, perf profiling hooks, and consistency cleanup.
- `security.py`: Good primitives. Move more policy checks here.
- `app.py`: Lifecycle clear. Add stronger error-parent handling and cleanup state metrics.
- `tray.py`: Good custom SNI implementation. Add unregister/cleanup path.
- `config.py`: Good centralization. Extend with blocked paths and tuning knobs.
- Packaging scripts: Works, but Debian packaging path and custom build script should be reconciled so install artifacts stay in sync.

## Proposed Implementation Plan

## Phase 1 (Fix User Pain First, 2-4 days)

Goal: eliminate compression/ghosting/lag regressions with minimal architecture churn.

1. Overlay correctness:
   - Add monitor-origin normalization transform.
   - Validate selection mapping with negative-coordinate fixtures.
2. Overlay teardown:
   - Add hidden-transparent draw branch.
   - Add deferred close strategy with fallback.
3. Overlay performance:
   - Add drag event coalescing (max 60 FPS).
   - Cache dimmed monitor background once per overlay.
4. Remove or neutralize `exclusive_zone` for transient overlays.

Success criteria:
- No persistent ghost frame after cancel/finalize (50 repeated captures).
- Selection border tracks pointer smoothly on dual 4K (<16ms p95 draw budget target).
- Correct region selection on left/right/top/bottom multi-monitor layouts.

## Phase 2 (Stabilize and Harden, 2-3 days)

1. Capture freshness guard and improved error signals.
2. Monitor fallback validation update (allow negative coordinates).
3. Move save-path restrictions into centralized security policy.
4. Add overlay and mapping unit tests:
   - Coordinate transform tests.
   - Bounds and crop tests.
   - Selection min-size tests.

Success criteria:
- No stale image captures in retry loops.
- Passing automated tests for known layout edge cases.

## Phase 3 (Quality and Sexy UX Upgrade, 3-5 days)

1. Visual polish pass (while preserving existing libadwaita style):
   - Better selection affordances (corner handles, subtle motion, improved label styling).
   - Faster perceived feedback (selection rectangle appears on press with zero delay).
2. Editor quality upgrades:
   - Smooth pen interpolation option.
   - Width presets and clearer active-tool state.
3. Telemetry-like local diagnostics (no network):
   - Timing logs for capture duration, overlay present time, average drag frame time.

Success criteria:
- Noticeably faster feel in user testing.
- No regressions in copy/save/output dimensions.

## Concrete Change List by File

- `cosmicsnip/overlay.py`
  - Add layout normalization helper.
  - Replace full redraw path with cached background + dirty rect updates.
  - Implement safe close lifecycle and hidden transparent state.
  - Remove/adjust exclusive zone behavior.
- `cosmicsnip/monitors.py`
  - Permit negative coords in cached config.
  - Clarify `force_detect` behavior naming/logic.
- `cosmicsnip/capture.py`
  - Add capture start-time filter for candidate files.
  - Strengthen logging around candidate choice.
- `cosmicsnip/security.py` and `cosmicsnip/config.py`
  - Centralize blocked save paths and reusable path policy.
- `cosmicsnip/editor.py`
  - Consume centralized save policy.
  - Normalize annotation/tool type naming (`rectangle` vs `rect`).
- `cosmicsnip/log.py`
  - Make logger setup idempotent.
- `README.md` and `ARCHITECTURE.md`
  - Sync undo behavior and updated overlay lifecycle notes.

## Risks and Mitigations

- Risk: Wayland compositor may still reject close/unmap timing.
  - Mitigation: keep fallback opacity path and gate close strategy behind runtime-safe sequence.
- Risk: Performance optimizations can introduce visual artifacts.
  - Mitigation: add dirty-rect debug mode and compare against full redraw path.
- Risk: Coordinate refactor can break existing good setups.
  - Mitigation: introduce transform tests before refactor and test across single + multi-monitor layouts.

## Acceptance Checklist

- [ ] Overlay does not shift or compress desktop layout during capture.
- [ ] No ghost background remains after finalize or cancel.
- [ ] Selection drag feels responsive on high-resolution multi-monitor setups.
- [ ] Region crop output always matches selected coordinates.
- [ ] No hidden overlay window accumulation across repeated captures.
- [ ] Docs and architecture notes match runtime behavior.

