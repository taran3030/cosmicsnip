# CosmicSnip — Architecture & Current State

> Complete technical reference for the codebase. Intended for contributors and
> maintainers who need to understand how every piece fits together.
>
> **Last updated:** 2026-03-21 · **Version:** 1.0.2

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Use Cases & User Flows](#2-use-cases--user-flows)
3. [Module Reference](#3-module-reference)
4. [Signal & Callback Chains](#4-signal--callback-chains)
5. [Code Navigation Index](#5-code-navigation-index)
6. [Packaging & Distribution](#6-packaging--distribution)
7. [Known Issues & Constraints](#7-known-issues--constraints)

---

## 1. Project Overview

CosmicSnip is a screenshot snipping tool for COSMIC Desktop (Pop!_OS 24.04, Wayland). It captures the screen via `cosmic-screenshot` (XDG Desktop Portal), presents a per-monitor selection overlay using `gtk4-layer-shell`, crops the selection, and opens an annotation editor with pen/highlighter/arrow/rectangle tools.

### Why it exists

No existing screenshot tool works on COSMIC's Wayland compositor:
- `grim`/`slurp` need `wlr-screencopy` (COSMIC doesn't expose it)
- `flameshot` crashes on COSMIC Wayland
- COSMIC's built-in screenshot has no region select or annotation

### Tech stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12+ |
| UI toolkit | GTK4 + libadwaita 1.x (PyGObject) |
| Drawing | Cairo 2D (pycairo) |
| Clipboard | GTK4 native `Gdk.ContentProvider` (image/png) |
| Overlays | `gtk4-layer-shell` (wlr-layer-shell protocol) |
| Capture | `cosmic-screenshot` CLI → XDG Desktop Portal |
| Tray icon | DBus StatusNotifierItem protocol |
| Packaging | dpkg `.deb` |

### File tree

```
cosmicsnip/
├── __init__.py      # Version + app ID
├── app.py           # Lifecycle orchestrator (Adw.Application)
├── capture.py       # Screen capture via cosmic-screenshot
├── clipboard.py     # Desktop notification helper
├── config.py        # All constants, paths, tool/color defs
├── editor.py        # Annotation editor (Adw.ApplicationWindow)
├── log.py           # Rotating file + stderr logging
├── monitors.py      # GDK monitor detection + config cache
├── overlay.py       # Multi-monitor layer-shell overlay + selection
├── security.py      # Path validation, symlink checks, root refusal
└── tray.py          # System tray via DBus StatusNotifierItem
```

---

## 2. Use Cases & User Flows

### UC-1: First launch (keyboard shortcut or app launcher)

**Trigger:** User runs `cosmicsnip` or presses `Super+Shift+S`.

**Flow:**
1. `main()` in `app.py:193` ensures LD_PRELOAD for gtk4-layer-shell, sets umask, inits logging
2. `CosmicSnipApp.__init__()` creates `Adw.Application` with `__app_id__`
3. `_on_activate()` fires → calls `self.hold()` (keeps app alive), registers tray icon, loads CSS
4. `_start_capture()` → `capture.py:capture_screen()` runs `cosmic-screenshot`
5. `SelectionOverlay` created → `OverlayController` spawns `MonitorOverlay` per monitor
6. User drags to select → `finalise()` → `hide_all()` → `_on_region_selected()` callback
7. GdkPixbuf crops the image, saves to `~/Pictures/screenshots/snip-YYYYMMDD-HHMMSS.png`
8. `SnipEditor` opens with the cropped image, auto-copies to clipboard

### UC-2: Subsequent capture (app already running)

**Trigger:** User clicks tray icon, presses `Ctrl+N` in editor, or re-runs `cosmicsnip`.

**Flow:**
1. `Adw.Application` detects existing instance → sends `activate` signal
2. `_on_activate()` fires again → `_start_capture()` (same as UC-1 step 4+)
3. Any existing overlay is hidden first (`_start_capture` line 81-83)

### UC-3: Autostart (login, tray-only mode)

**Trigger:** System boots, autostart desktop entry runs `cosmicsnip --tray`.

**Flow:**
1. `main()` detects `--tray` flag → `CosmicSnipApp(tray_only=True)`
2. `_on_activate()` fires → `hold()` + tray registration, but skips `_start_capture()`
3. App sits idle with tray icon. User clicks tray → `_start_capture()`

### UC-4: Annotate and copy

**Trigger:** User draws on screenshot in editor, presses `Ctrl+C`.

**Flow:**
1. Mouse/gesture events → `_on_press`/`_on_motion`/`_on_release` in editor
2. Annotation stored as dict in `self._annotations` list
3. `Ctrl+C` → `_copy_to_clipboard()` → `_render_to_surface()`
4. `_annotation_bounds()` computes tight bounding box of image + all annotations
5. Cairo renders image + annotations to `ImageSurface(FORMAT_ARGB32)`
6. PNG bytes → `Gdk.ContentProvider.new_for_bytes("image/png", ...)` → clipboard
7. Toast notification "Copied WxH to clipboard"

### UC-5: Save as PNG

**Trigger:** User presses `Ctrl+S` or clicks save button.

**Flow:**
1. `_save_as_dialog()` opens `Gtk.FileDialog` with PNG filter
2. User picks path → `_on_save_response()` validates path (security checks)
3. `_render_to_surface()` → `surface.write_to_png(path)`
4. Toast notification "Saved to filename.png"

### UC-6: Cancel selection

**Trigger:** User presses `Esc` or right-clicks during overlay.

**Flow:**
1. Key event / GestureClick → `controller.cancel()`
2. `cancel()` → `_release_keyboard()` → `hide_all()` → `_on_cancelled()` callback
3. App goes idle (stays in dock/tray)

### UC-7: Quit

**Trigger:** User presses `Ctrl+Q` in editor or clicks "Quit" in tray menu.

**Flow:**
1. `Ctrl+Q` → `self.get_application().quit()` (editor.py key handler)
2. Tray "Quit" → `GLib.idle_add(self._app.quit)` (tray.py:172)

---

## 3. Module Reference

### 3.1 `__init__.py`

| Symbol | Line | Value |
|--------|------|-------|
| `__version__` | 3 | `"1.0.2"` |
| `__app_id__` | 4 | `"io.github.itssoup.CosmicSnip"` |

Referenced by: `app.py` (application ID), `tray.py` (icon name).

---

### 3.2 `app.py` — Lifecycle Orchestrator

**Class: `CosmicSnipApp(Adw.Application)`** (line 33)

| Method | Line | Purpose |
|--------|------|---------|
| `__init__(tray_only)` | 41 | Init app, connect `activate` signal |
| `_on_activate(_app)` | 50 | Hold app, register tray, load CSS, start capture |
| `_start_capture()` | 79 | Clean old overlays, run cosmic-screenshot, present overlay |
| `_on_region_selected(path, x1,y1,x2,y2)` | 109 | Crop with GdkPixbuf, save, open editor |
| `_on_cancelled()` | 138 | Hide overlay, go idle |
| `_show_error(message)` | 145 | Alert dialog for capture failures |

**Function: `_ensure_layer_shell_preload()`** (line 179)
- Checks LD_PRELOAD for `libgtk4-layer-shell.so`
- If missing, finds the .so in 4 known paths and re-execs with it

**Function: `main()`** (line 193)
- Entry point. Calls preload check, umask, logging, root check
- Parses `--debug` and `--tray` flags
- Runs `CosmicSnipApp.run()`

**CSS** (line 155): `.snip-pill` class for overlay hint label.

---

### 3.3 `capture.py` — Screen Capture

| Function | Line | Purpose |
|----------|------|---------|
| `capture_screen()` | ~30 | Runs `cosmic-screenshot --interactive=false`, returns path to PNG |
| `cleanup_temp_files()` | ~90 | Removes temp screenshots older than 5 minutes |
| `cleanup_file(path)` | ~110 | Immediately deletes a specific temp file |

**Capture flow:**
1. Ensures temp dir exists with correct ownership
2. Runs `cosmic-screenshot --interactive=false --save-dir=TEMP_DIR --notify=false`
3. Globs for `Screenshot_????-??-??_??-??-??.png` in temp dir
4. Validates each candidate: path within TEMP_DIR, is regular file (not symlink), PNG magic bytes, dimensions within limits
5. Returns first valid file path

**Security checks per candidate:**
- `validate_path_within(path, TEMP_DIR)` — no path traversal
- `open_no_follow(path)` — rejects symlinks (O_NOFOLLOW)
- `validate_png_magic(fd)` — checks `\x89PNG\r\n\x1a\n` header
- GdkPixbuf header dimension check against `MAX_IMAGE_WIDTH` / `MAX_IMAGE_HEIGHT`

---

### 3.4 `clipboard.py` — Notification Helper

| Function | Line | Purpose |
|----------|------|---------|
| `send_notification(title, body)` | ~8 | Runs `notify-send` with truncation + 5s timeout |

Note: Actual clipboard operations use GTK4 native API in `editor.py`, not this module.

---

### 3.5 `config.py` — Constants & Configuration

#### Paths
| Constant | Line | Value |
|----------|------|-------|
| `SAVE_DIR` | 29 | `~/Pictures/screenshots/` |
| `TEMP_DIR` | 32 | `$XDG_RUNTIME_DIR/cosmicsnip/` |

#### Security Limits
| Constant | Line | Value |
|----------|------|-------|
| `MAX_IMAGE_WIDTH` | 36 | 15360 |
| `MAX_IMAGE_HEIGHT` | 37 | 8640 |
| `MAX_UNDO_HISTORY` | 38 | 200 |
| `MAX_STROKE_POINTS` | 39 | 10000 |
| `TEMP_FILE_MODE` | 40 | 0o600 |

#### Overlay Visual
| Constant | Line | Value |
|----------|------|-------|
| `OVERLAY_DIM_ALPHA` | 45 | 0.45 |
| `SELECTION_BORDER_COLOR` | 46 | (0.15, 0.56, 1.0, 1.0) — blue |
| `SELECTION_BORDER_WIDTH` | 47 | 2.0 |
| `MIN_SELECTION_SIZE` | 48 | 10 px |

#### Editor Defaults
| Constant | Line | Value |
|----------|------|-------|
| `DEFAULT_PEN_WIDTH` | 52 | 3 |
| `DEFAULT_HIGHLIGHT_WIDTH` | 53 | 20 |
| `DEFAULT_ARROW_HEAD_ANGLE` | 54 | 0.45 rad (~26°) |
| `DEFAULT_ARROW_HEAD_RATIO` | 55 | 5.0 |

#### Color Palette (`PALETTE`)
| Index | Name | RGBA |
|-------|------|------|
| 0 | Red | (0.93, 0.16, 0.16, 1.0) |
| 1 | Orange | (0.96, 0.52, 0.10, 1.0) |
| 2 | Blue | (0.15, 0.45, 0.93, 1.0) |
| 3 | Green | (0.20, 0.72, 0.30, 1.0) |
| 4 | Black | (0.12, 0.12, 0.12, 1.0) |
| 5 | White | (1.00, 1.00, 1.00, 1.0) |

Default color: Red (index 0).

#### Tool Definitions (`TOOLS`)
| tool_id | label | icon_name | shortcut |
|---------|-------|-----------|----------|
| `pen` | Pen | `edit-symbolic` | P |
| `highlighter` | Highlighter | `format-text-highlight-symbolic` | H |
| `arrow` | Arrow | `go-next-symbolic` | A |
| `rect` | Rectangle | `view-fullscreen-symbolic` | R |

Default tool: `pen`.

#### Function: `ensure_directories()`
- Creates `SAVE_DIR` and `TEMP_DIR`
- Verifies `TEMP_DIR` ownership matches current UID

---

### 3.6 `editor.py` — Annotation Editor

**Class: `SnipEditor(Adw.ApplicationWindow)`** (line ~40)

The editor is the largest module (~680 lines). It handles:
- Canvas with 25% margin padding for out-of-bounds drawing
- 4 annotation tools (pen, highlighter, arrow, rectangle)
- Undo stack (up to 200 entries)
- Auto-copy on first map
- Save as transparent PNG with auto-trim to content bounds

#### Initialization (line ~45)

```
self._pad = max(100, int(max(img_w, img_h) * 0.25))
self._margin_x = self._pad
self._margin_y = self._pad
self._canvas_w = self._img_w + self._pad * 2
self._canvas_h = self._img_h + self._pad * 2
```

The canvas is larger than the image by `_pad` pixels on each side. The image is drawn at `(_margin_x, _margin_y)` within the canvas. Annotations can extend into the margin area.

#### Key Methods

| Method | Line | Purpose |
|--------|------|---------|
| `_build_headerbar()` | ~140 | Creates Adw.HeaderBar with tool toggles, color swatches, width controls, action buttons |
| `_draw_canvas(area, cr, w, h)` | ~280 | Main Cairo draw function — dark background, image at margin offset, annotations |
| `_on_press(gesture, n, x, y)` | ~330 | Start annotation: records start point in canvas coords |
| `_on_motion(ctrl, x, y)` | ~350 | Update current stroke: appends points (pen/highlighter) or updates endpoint (arrow/rect) |
| `_on_release(gesture, n, x, y)` | ~370 | Finalize annotation: append to `_annotations` list |
| `_annotation_bounds()` | ~458 | Compute bounding box of image + all annotations (for auto-trim) |
| `_render_to_surface()` | ~506 | Render image + annotations to Cairo surface, trimmed to content bounds |
| `_copy_to_clipboard()` | ~522 | Render → PNG bytes → `Gdk.ContentProvider` → clipboard |
| `_save_as_dialog()` | ~540 | Open file dialog, validate path, write PNG |
| `_on_key(ctl, keyval, kc, st)` | ~590 | Keyboard shortcuts: P/H/A/R tools, Ctrl+C/S/Z/N/Q, Esc |

#### Annotation Data Format

Each annotation is a `dict`:

```python
# Pen / Highlighter
{"type": "pen", "color": (r,g,b,a), "width": 3, "points": [(x,y), ...]}
{"type": "highlighter", "color": (r,g,b,0.4), "width": 20, "points": [(x,y), ...]}

# Arrow
{"type": "arrow", "color": (r,g,b,a), "width": 3, "start": (x,y), "end": (x,y)}

# Rectangle
{"type": "rect", "color": (r,g,b,a), "width": 3, "start": (x,y), "end": (x,y)}
```

All coordinates are in **canvas space** (image offset by `_margin_x`, `_margin_y`).

#### Rendering Pipeline

**`_render_annotation(cr, ann)`** — module-level function (~440)
- Dispatches to drawing code based on `ann["type"]`
- Pen/highlighter: `cr.move_to` + `cr.line_to` for each point, then `cr.stroke()`
- Highlighter uses `cairo.OPERATOR_OVER` with alpha 0.4
- Arrow: line + triangular arrowhead at the endpoint
- Rectangle: `cr.rectangle` + `cr.stroke()`

**`_render_to_surface()`** — called by copy and save
1. Calls `_annotation_bounds()` → `(bx1, by1, bx2, by2)` in canvas coords
2. Creates `cairo.ImageSurface(FORMAT_ARGB32, bx2-bx1, by2-by1)` — transparent
3. `cr.translate(-bx1, -by1)` — shift origin so content starts at (0,0)
4. Paints image pixbuf at `(_margin_x, _margin_y)` — only covers image area, rest is transparent
5. Iterates `_annotations`, calls `_render_annotation(cr, ann)` for each
6. Returns surface

**`_annotation_bounds()`** — computes tight crop
1. Starts with `min_x/y = inf`, `max_x/y = -inf`
2. For each annotation, expands bounds by stroke width + 2px padding
3. Unions with image bounds `(margin_x, margin_y, margin_x+img_w, margin_y+img_h)`
4. Clamps to canvas limits `(0, 0, canvas_w, canvas_h)`

---

### 3.7 `log.py` — Logging

| Function | Line | Purpose |
|----------|------|---------|
| `setup_logging(debug)` | 17 | Init rotating file handler (512KB, 3 backups) + stderr |
| `get_logger(name)` | 52 | Returns `logging.getLogger(f"cosmicsnip.{name}")` |

Log location: `~/.local/share/cosmicsnip/cosmicsnip.log`
Permissions: `0o600` on all log files.

---

### 3.8 `monitors.py` — Monitor Detection

**Dataclass: `MonitorInfo`** (line ~15)
```python
@dataclass(frozen=True)
class MonitorInfo:
    name: str       # connector name, e.g. "DP-2"
    x: int          # compositor X offset
    y: int          # compositor Y offset
    width: int      # logical width
    height: int     # logical height
    scale: int      # integer scale factor
    gdk_index: int  # GDK monitor index
```

| Function | Line | Purpose |
|----------|------|---------|
| `get_monitors()` | ~40 | Detect monitors via GDK, cache to JSON, return list |
| `get_gdk_monitor(index)` | ~130 | Get `Gdk.Monitor` by index for layer-shell binding |

**Critical detail:** GDK on COSMIC reports **logical/compositor coordinates**, NOT physical pixels. The code does NOT divide by scale factor. This was a major bug that caused the second monitor to show as 480x1146 instead of 1440x3440.

**Config cache:** `~/.config/cosmicsnip/monitors.json` — written atomically (`.tmp` → rename). Validated on load: rejects symlinks, invalid JSON, out-of-range values.

---

### 3.9 `overlay.py` — Selection Overlay

This module has three implementations:

#### `SelectionState` (line 73)
Mutable rectangle in combined-image coordinates. Shared across all per-monitor overlays.

| Method | Purpose |
|--------|---------|
| `begin(x, y)` | Start drag at point |
| `update(x, y)` | Update endpoint during drag |
| `finish()` | End drag |
| `rect()` | Returns `(x1, y1, x2, y2)` normalized |
| `size_ok()` | True if selection ≥ `MIN_SELECTION_SIZE` in both dimensions |

#### `MonitorOverlay(Gtk.Window)` (line 105)
Per-monitor layer-shell overlay. Each shows its portion of the combined screenshot.

**Layer-shell setup (line 136):**
```python
LayerShell.init_for_window(self)
LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
LayerShell.set_exclusive_zone(self, -1)  # cover panel area
LayerShell.set_anchor(self, edge, True)  # all 4 edges
LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.EXCLUSIVE)
LayerShell.set_monitor(self, gdk_mon)  # bind to specific monitor
```

**Coordinate mapping:**
- `_canvas_to_image(cx, cy)`: local canvas coords → combined image coords (adds monitor offset)
- `_image_to_canvas(ix, iy)`: combined image coords → local canvas coords (subtracts monitor offset)

**Draw function (`_draw`, line ~209):**
1. Paint black background
2. Paint this monitor's portion of the screenshot
3. Dim with `OVERLAY_DIM_ALPHA` (0.45)
4. If selection exists: clear selection area (show original brightness), draw blue border
5. If drag endpoint is on this monitor: draw size label

**Hint pill:** "Drag to select · Esc to cancel" — only shown on primary monitor.

#### `OverlayController` (line 295)
Manages multiple `MonitorOverlay` windows with shared `SelectionState`.

| Method | Line | Purpose |
|--------|------|---------|
| `present()` | 315 | Show all overlay windows |
| `redraw_all()` | 319 | Queue draw on all canvases |
| `reconfigure()` | ~335 | Reuse existing overlay windows for a new capture, adapting to monitor topology changes |
| `hide_all()` | 332 | Hidden-state repaint + BACKGROUND layer + opacity 0 |
| `finalise()` | 349 | Hide overlays, call `_on_selected` callback |
| `cancel()` | 356 | Hide overlays, call `_on_cancelled` callback |

**`hide_all()` detail (line 332):**
```python
# Can't destroy() — causes Wayland broken pipe
# Can't set_visible(False) — same broken pipe
# Solution: mark hidden so draw paints transparent, then drop layer + opacity 0
for ov in self._overlays:
    ov._is_hidden = True                  # draw path paints transparent
    ov._canvas.queue_draw()
    LayerShell.set_layer(ov, BACKGROUND)  # drop below everything
    ov.set_opacity(0)                     # invisible
```

#### `FallbackOverlay(Gtk.Window)` (line 361)
Single-window fallback when layer-shell isn't available. Scales the combined screenshot to fit one screen. Converts screen coords back to image coords on release.

#### `SelectionOverlay` (line 512)
Public API / factory. Uses `OverlayController` whenever monitor geometry is available (including single-monitor). Falls back to `FallbackOverlay` only when monitor data is unavailable.

---

### 3.10 `security.py` — Security Hardening

| Function | Line | Purpose |
|----------|------|---------|
| `refuse_root()` | ~10 | `sys.exit(1)` if running as UID 0 |
| `validate_path_within(path, parent)` | ~20 | Resolves path, rejects traversal outside parent |
| `open_no_follow(path)` | ~40 | `os.open()` with `O_NOFOLLOW \| O_RDONLY` — rejects symlinks |
| `validate_png_magic(fd)` | ~55 | Reads first 8 bytes, checks PNG magic `\x89PNG\r\n\x1a\n` |
| `fchmod_safe(fd, mode)` | ~70 | fd-based chmod (TOCTOU-safe, immune to race conditions) |

**Blocked save paths** (in `security.py`, used by `editor.py`):
`/etc`, `/usr`, `/bin`, `/sbin`, `/lib`, `/boot`, `/dev`, `/proc`, `/sys`, `/var/lib`, `/var/log`

---

### 3.11 `tray.py` — System Tray Icon

**Class: `TrayIcon`** (line 80)

Implements the **StatusNotifierItem** DBus protocol so COSMIC's panel tray applet shows an icon.

| Method | Line | Purpose |
|--------|------|---------|
| `register()` | 91 | Connect to session bus, register SNI + menu objects, call StatusNotifierWatcher |
| `_handle_sni_call(...)` | 133 | Handles `Activate` (left-click → new snip) and `SecondaryActivate` |
| `_handle_sni_get(...)` | 143 | Returns SNI properties: Id, Title, IconName, ToolTip, etc. |
| `_handle_menu_call(...)` | 160 | Handles `GetLayout` (right-click menu) and `Event` (menu item clicked) |
| `_build_menu_layout()` | 188 | Returns dbusmenu layout: "New Screenshot" (id=1) + "Quit" (id=2) |

**DBus interfaces registered:**
- `org.kde.StatusNotifierItem` at `/StatusNotifierItem`
- `com.canonical.dbusmenu` at `/StatusNotifierMenu`

**Icon:** `io.github.itssoup.CosmicSnip` — resolves to the installed SVG at `/usr/share/icons/hicolor/scalable/apps/`.

**Menu items:**
| ID | Label | Action |
|----|-------|--------|
| 1 | New Screenshot | `GLib.idle_add(self._on_activate)` |
| 2 | Quit | `GLib.idle_add(self._app.quit)` |

---

## 4. Signal & Callback Chains

### Chain 1: Full capture → edit → copy

```
User presses Super+Shift+S
  → cosmicsnip CLI runs
  → main() → _ensure_layer_shell_preload() → re-exec with LD_PRELOAD
  → Adw.Application.run()
  → "activate" signal → _on_activate()
  → hold() [first time] + TrayIcon.register()
  → _start_capture()
  → capture.capture_screen()
    → subprocess: cosmic-screenshot --interactive=false
    → glob for Screenshot_*.png
    → validate: path, symlink, magic bytes, dimensions
    → return path
  → monitors.get_monitors()
    → GDK monitor enumeration
    → cache to ~/.config/cosmicsnip/monitors.json
  → SelectionOverlay(app, path, on_selected, on_cancelled, monitors)
    → OverlayController.__init__()
      → GdkPixbuf.new_from_file(path) — combined screenshot
      → for each monitor: MonitorOverlay(pixbuf.new_subpixbuf(...))
        → LayerShell.init_for_window()
        → LayerShell.set_layer(OVERLAY)
        → LayerShell.set_exclusive_zone(-1)
        → LayerShell.set_anchor(all 4 edges)
        → LayerShell.set_keyboard_mode(EXCLUSIVE)
        → LayerShell.set_monitor(gdk_mon)
  → overlay.present() — shows all overlays

User drags to select region
  → GestureClick "pressed" → MonitorOverlay._on_press()
    → state.begin(canvas_to_image(x, y))
    → controller.redraw_all() — all overlays repaint
  → GestureDrag "drag-update" → MonitorOverlay._on_drag_update()
    → state.update(canvas_to_image(ox+dx, oy+dy))
    → controller.redraw_all()
  → GestureClick "released" → MonitorOverlay._on_release()
    → state.update(), state.finish()
    → if state.size_ok(): controller.finalise()

controller.finalise()
  → hide_all() — transparent hidden-state draw, BACKGROUND layer, opacity 0
  → _on_selected(image_path, x1, y1, x2, y2)
    → app._on_region_selected()
      → GdkPixbuf.Pixbuf.new_from_file(path).new_subpixbuf(x1,y1,w,h)
      → save to ~/Pictures/screenshots/snip-YYYYMMDD-HHMMSS.png
      → cleanup_file(temp_path)
      → SnipEditor(app, crop_path)
      → editor.present()

Editor "map" signal → _on_first_map()
  → GLib.idle_add(_copy_to_clipboard)
    → _render_to_surface() — image + annotations as Cairo surface
    → surface.write_to_png(BytesIO)
    → Gdk.ContentProvider.new_for_bytes("image/png", bytes)
    → Gdk.Display.get_clipboard().set_content(provider)
    → toast "Copied WxH to clipboard"
```

### Chain 2: Annotation drawing

```
Mouse press on canvas
  → GestureClick "pressed" → _on_press()
  → if tool is pen/highlighter:
      _current_stroke = [{"type": tool, "color": rgba, "width": w, "points": [(x,y)]}]
  → if tool is arrow/rect:
      _shape_start = (x, y)

Mouse move
  → EventControllerMotion "motion" → _on_motion()
  → if pen/highlighter: append (x,y) to _current_stroke["points"]
    → cap at MAX_STROKE_POINTS
  → if arrow/rect: update end point
  → canvas.queue_draw() → _draw_canvas() repaints everything

Mouse release
  → GestureClick "released" → _on_release()
  → append completed annotation to self._annotations
  → cap _annotations at MAX_UNDO_HISTORY (drop oldest)
  → clear _current_stroke / _shape_start
  → canvas.queue_draw()
```

### Chain 3: Cancel / Escape

```
Esc key during overlay
  → EventControllerKey → MonitorOverlay._on_key()
  → controller.cancel()
  → _release_keyboard()
  → hide_all() — blank + background + transparent
  → _on_cancelled() → app._on_cancelled()
  → self._overlay = None
  → app sits idle (held alive by hold() + tray)
```

### Chain 4: Tray icon interaction

```
Left-click on tray icon
  → DBus method call: Activate(x, y)
  → _handle_sni_call() → GLib.idle_add(self._on_activate)
  → app._start_capture() [same as UC-1]

Right-click → "New Screenshot"
  → DBus: GetLayout → returns menu
  → DBus: Event(id=1, "clicked") → GLib.idle_add(self._on_activate)

Right-click → "Quit"
  → DBus: Event(id=2, "clicked") → GLib.idle_add(self._app.quit)
```

---

## 5. Code Navigation Index

Quick lookup for where core behavior lives.

### App Lifecycle
| File | Key Entry Points |
|------|------------------|
| `app.py` | `CosmicSnipApp.__init__()`, `_on_activate()`, `_start_capture()`, `_on_region_selected()`, `_on_cancelled()`, `main()` |
| `tray.py` | `TrayIcon.register()`, `_handle_sni_call()`, `_handle_menu_call()`, `_build_menu_layout()` |

### Capture and Overlay
| File | Key Entry Points |
|------|------------------|
| `capture.py` | `capture_screen()`, `_capture_cosmic()`, `cleanup_temp_files()`, `cleanup_file()` |
| `overlay.py` | `SelectionState`, `MonitorOverlay._draw()`, `OverlayController.reconfigure()`, `OverlayController.hide_all()`, `SelectionOverlay` |
| `monitors.py` | `detect_monitors()`, `get_monitors()`, `save_config()`, `load_config()`, `get_gdk_monitor()` |

### Editor and Output
| File | Key Entry Points |
|------|------------------|
| `editor.py` | `SnipEditor.__init__()`, `_on_draw()`, `_annotation_bounds()`, `_render_to_surface()`, `_copy_to_clipboard()`, `_save_as_dialog()`, `_on_key()` |
| `clipboard.py` | `send_notification()` |

### Configuration and Security
| File | Key Entry Points |
|------|------------------|
| `config.py` | Constants for save paths, tool defaults, palette, and rendering limits |
| `security.py` | `refuse_root()`, `validate_path_within()`, `open_no_follow()`, `validate_png_magic_fd()`, `fchmod_safe()` |

---

## 6. Packaging & Distribution

### pyproject.toml
- Name: `cosmicsnip`
- Version: `1.0.2`
- Python: `>=3.10`
- Dependencies: `PyGObject>=3.42`, `dbus-python>=1.3`
- Entry point: `cosmicsnip = cosmicsnip.app:main`

### build-deb.sh
Builds a standalone `.deb` at `dist/cosmicsnip_1.0.2-1_all.deb`.

**Package tree:**
```
/usr/bin/cosmicsnip                          # Bash launcher (LD_PRELOAD + exec python)
/usr/lib/python3/dist-packages/cosmicsnip/   # Python package
/usr/share/applications/io.github.itssoup.CosmicSnip.desktop
/usr/share/metainfo/io.github.itssoup.CosmicSnip.metainfo.xml
/usr/share/icons/hicolor/scalable/apps/io.github.itssoup.CosmicSnip.svg
/etc/xdg/autostart/io.github.itssoup.CosmicSnip-autostart.desktop
/usr/share/doc/cosmicsnip/{README.md, LICENSE, changelog.gz}
```

**Launcher script** (`/usr/bin/cosmicsnip`):
```bash
#!/bin/bash
for lib in /usr/local/lib/x86_64-linux-gnu/libgtk4-layer-shell.so \
           /usr/local/lib/aarch64-linux-gnu/libgtk4-layer-shell.so \
           /usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so \
           /usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so; do
    if [ -f "$lib" ]; then
        export LD_PRELOAD="${lib}${LD_PRELOAD:+:$LD_PRELOAD}"
        break
    fi
done
exec python3 -m cosmicsnip.app "$@"
```

### Desktop entries

**Main** (`io.github.itssoup.CosmicSnip.desktop`):
- `Exec=cosmicsnip`
- `Icon=io.github.itssoup.CosmicSnip`
- Shows in app launcher

**Autostart** (`io.github.itssoup.CosmicSnip-autostart.desktop`):
- `Exec=cosmicsnip --tray`
- `NoDisplay=true`
- Starts tray icon on login

### Debian metadata

**debian/control**: Dependencies include `python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `python3-dbus`, `python3-cairo`, `libnotify-bin`.

---

## 7. Known Issues & Constraints

### Wayland surface lifecycle
- **Cannot `destroy()` or `set_visible(False)` on layer-shell windows** — COSMIC drops the Wayland connection ("Error 32: Broken pipe"). Workaround: blank the pixbuf, move to BACKGROUND layer, set opacity 0.
- **Overlay ghosting**: If `hide_all()` doesn't fully clear the surface, the captured screenshot image persists on screen. Current fix blanks the pixbuf data before hiding.

### Monitor coordinates
- **GDK on COSMIC reports logical coordinates** — do NOT divide by scale factor. This was a bug where a 3440px-wide monitor at scale 3 showed as 1147px.

### GTK4 + AppIndicator3 conflict
- `AppIndicator3` internally calls `gi.require_version("Gtk", "3.0")` which conflicts with GTK 4.0 already loaded. Solution: pure DBus StatusNotifierItem implementation in `tray.py`.

### Single-instance behavior
- `Adw.Application` with a fixed `application_id` handles this. Second launch sends `activate` signal to the running instance.
- The `hold()` call keeps the app alive even with no windows. Tray icon provides the visual indicator.

### LD_PRELOAD requirement
- `gtk4-layer-shell` must be loaded before GTK initializes. The launcher script and `_ensure_layer_shell_preload()` both handle this. If neither catches it, overlays fall back to `fullscreen()` (no multi-monitor support).

### Out-of-bounds annotations
- Canvas is padded by 25% of image size (minimum 100px) on each side. Annotations in the margin render on transparent background in the output PNG. The `_annotation_bounds()` function computes the tight crop so the output isn't padded with empty space.

### Blocked save paths
- Hardcoded in `editor.py`: `/etc`, `/usr`, `/bin`, `/sbin`, `/lib`, `/boot`, `/dev`, `/proc`, `/sys`, `/var/lib`, `/var/log`. Should be moved to `config.py` or `security.py` in a future refactor.
