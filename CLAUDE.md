# CosmicSnip — Project Specification & Architecture

## Vision

CosmicSnip is a **Windows Snipping Tool clone** built natively for the **COSMIC Desktop Environment** (Pop!_OS 24.04 / Wayland). It replicates the exact workflow Windows users expect:

1. Press **Super+Shift+S**
2. Screen freezes with a dim overlay
3. **Drag to select** a rectangular region
4. An **editor window** opens with the cropped screenshot
5. **Annotate** with pen, highlighter, arrows, rectangles
6. **Ctrl+C** copies annotated image to clipboard — paste anywhere
7. **Ctrl+S** saves to `~/Pictures/screenshots/`

The app should feel native to COSMIC, use GTK4 conventions, and be publishable as an open-source tool on GitHub and eventually as a `.deb` package.

---

## Target Environment

| Component | Detail |
|-----------|--------|
| OS | Pop!_OS 24.04 LTS |
| Desktop | COSMIC Epoch 1 (Rust-based, Wayland-native) |
| Display server | Wayland (no X11 fallback needed) |
| GPU | NVIDIA RTX 4090, driver 580.x |
| Compositor | cosmic-comp |
| Screenshot backend | `cosmic-screenshot` CLI (uses XDG Desktop Portal internally) |
| Clipboard | `wl-copy` from wl-clipboard |
| Python | 3.12 |
| UI toolkit | GTK4 via PyGObject |
| Drawing | Cairo 2D |

### Important Wayland constraints

- **`grim` / `slurp` do NOT work** — COSMIC's compositor does not support `wlr-screencopy-unstable-v1`
- **`flameshot` is broken** on COSMIC Wayland
- **XDG Desktop Portal** is the correct capture API — `cosmic-screenshot` wraps this
- Clipboard must use `wl-copy` (not `xclip` or `xsel`)

---

## Current State

The project has a working skeleton with the following modules. There are bugs to fix and polish to add.

### Known Issues

1. **Capture filename mismatch** — `cosmic-screenshot` saves files as `Screenshot_YYYY-MM-DD_HH-MM-SS.png` but the code globs for `screenshot-*.png`. The glob pattern in `capture.py` needs to match both formats: `[Ss]creenshot*.png`
2. **GTK dialog warning** — `GtkDialog mapped without a transient parent` — the error dialog in `app.py` needs a parent window reference or should use a different pattern
3. **No libadwaita integration yet** — the app uses raw GTK4 but should use `libadwaita` (`Adw.Application`, `Adw.ApplicationWindow`, `Adw.HeaderBar`, `Adw.ToolbarView`) for native COSMIC look and feel including automatic dark/light theme support
4. **Editor should open instantly** — after drag-selecting, the editor should appear with zero perceived delay
5. **Copy-on-release** — ideally, releasing the mouse after selection should auto-copy to clipboard immediately (before the editor even opens), so the user can paste right away
6. **Annotation rendering** needs testing — pen smoothing, arrow heads, rectangle drawing may have edge cases

---

## Architecture

### Project Structure

```
cosmicsnip/
├── pyproject.toml           # Package metadata, dependencies
├── install.sh               # System installer script
├── README.md                # User-facing documentation
├── CONTRIBUTING.md          # Developer guide
├── SECURITY.md              # Threat model and vuln reporting
├── LICENSE                  # MIT
├── .gitignore
└── cosmicsnip/              # Python package
    ├── __init__.py          # Version, app ID
    ├── app.py               # Entry point — lifecycle orchestration
    ├── config.py            # ALL constants, paths, limits, tool/color defs
    ├── capture.py           # Screen capture backends
    ├── clipboard.py         # Clipboard operations (wl-copy)
    ├── overlay.py           # Fullscreen region selection UI
    └── editor.py            # Annotation editor window + cairo rendering
```

### Module Responsibilities

#### `config.py` — Single source of truth
- All file paths (XDG-compliant)
- Security limits (max image dimensions, max undo history, temp file permissions)
- UI constants (colors, border widths, overlay alpha)
- Tool definitions (id, label, icon name, tooltip) as frozen dataclasses
- Color palette definitions as frozen dataclasses
- `ensure_directories()` — creates required dirs with safe permissions

#### `capture.py` — Screen capture
- `capture_screen() -> str` — returns path to temp PNG
- Uses `cosmic-screenshot --interactive=false` as primary backend
- Validates image dimensions before returning (prevents memory bombs)
- `cleanup_temp_files()` — removes stale captures older than 1 hour
- Temp files written to `$XDG_RUNTIME_DIR/cosmicsnip/` with `0600` permissions

#### `clipboard.py` — Wayland clipboard
- `copy_image_to_clipboard(path)` — pipes PNG bytes to `wl-copy --type image/png`
- `send_notification(title, body)` — best-effort desktop notification via `notify-send`
- No `shell=True` anywhere — all subprocess calls use argument lists
- Only allows `image/png` MIME type

#### `overlay.py` — Region selection
- `SelectionOverlay(app, image_path, on_selected, on_cancelled)`
- Frameless fullscreen GTK4 window with crosshair cursor
- Draws captured screenshot as background with semi-transparent dim layer
- Drag interaction highlights selected region with bright cutout + blue border
- Shows live pixel dimensions badge below selection
- Calls `on_selected(image_path, x1, y1, x2, y2)` in image coordinates on mouse release
- Calls `on_cancelled()` on Escape
- Converts screen coordinates to image coordinates accounting for display scaling

#### `editor.py` — Annotation editor
- `SnipEditor(app, image_path)` — main editing window
- Toolbar with:
  - Tool toggles: Pen, Highlighter, Arrow, Rectangle (using Adwaita symbolic icons)
  - Color swatches with visual preview
  - Stroke width +/- controls
  - Undo, Copy, Save buttons
- Canvas: `Gtk.DrawingArea` with cairo drawing
- Annotation storage: append-only list of dicts (type, points/start/end, color, width)
- `_render_annotation(cr, ann)` — **pure stateless function** that draws one annotation
- In-progress preview: current stroke/shape rendered live during drag
- Keyboard shortcuts: P/H/A/R for tools, Ctrl+C/Z/S for actions
- Auto-copies to clipboard when editor opens
- Saves annotated image by rendering to off-screen cairo surface

#### `app.py` — Lifecycle orchestrator
- `CosmicSnipApp(Gtk.Application)` — manages capture → overlay → editor flow
- `_on_activate()` — ensures directories, cleans temp files, captures screen, shows overlay
- `_on_region_selected()` — crops image with Pillow, saves, opens editor
- `_on_cancelled()` — quits app
- Loads global CSS for the overlay pill badge and status labels

### Data Flow

```
[User presses Super+Shift+S]
    ↓
app.py: _on_activate()
    ↓
capture.py: capture_screen()
    → cosmic-screenshot --interactive=false --save-dir=$TEMP
    → validates image dimensions
    → returns /tmp/cosmicsnip/Screenshot_*.png
    ↓
overlay.py: SelectionOverlay
    → fullscreen window, dim overlay, drag to select
    → on mouse release: converts screen coords → image coords
    → calls on_selected(path, x1, y1, x2, y2)
    ↓
app.py: _on_region_selected()
    → Pillow crops image
    → saves to ~/Pictures/screenshots/snip-TIMESTAMP.png
    ↓
editor.py: SnipEditor
    → displays cropped image in scrollable canvas
    → auto-copies to clipboard via wl-copy
    → user annotates with tools
    → Ctrl+C renders annotations to cairo surface → wl-copy
    → Ctrl+S saves annotated PNG
```

---

## Design System

### GTK4 + Libadwaita (target)

The app should migrate from raw GTK4 to **libadwaita** for:
- `Adw.Application` / `Adw.ApplicationWindow` — automatic COSMIC theme integration
- `Adw.HeaderBar` — native-looking title bar with integrated controls
- `Adw.ToolbarView` — proper toolbar layout
- `Adw.StatusPage` — error states
- Automatic dark/light mode support
- Proper COSMIC system font and spacing

Python imports:
```python
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Adw, GdkPixbuf
```

System dependency: `gir1.2-adw-1`

### Icons

Use **Adwaita symbolic icons** (built into GTK4, no extra library needed):
- `edit-symbolic` — pen tool
- `format-text-highlight-symbolic` — highlighter
- `go-next-symbolic` — arrow tool
- `checkbox-symbolic` — rectangle tool
- `edit-copy-symbolic` — copy button
- `document-save-symbolic` — save button
- `edit-undo-symbolic` — undo button
- `accessories-screenshot` — app icon

Browse available icons: `gtk4-icon-browser` (install with `sudo apt install gtk-4-examples`)

### CSS Theming

GTK4 uses real CSS (subset). Load via `Gtk.CssProvider`:
```python
css = Gtk.CssProvider()
css.load_from_string("...")
Gtk.StyleContext.add_provider_for_display(display, css, priority)
```

Use CSS classes like `.suggested-action` (blue accent), `.destructive-action` (red), `.linked` (grouped buttons), `.dim-label`, `.title`, etc.

---

## Security Model

| Threat | Mitigation |
|--------|-----------|
| Temp files with sensitive screenshot data | `$XDG_RUNTIME_DIR/cosmicsnip/` with `0700` dir, `0600` files; auto-cleaned after 1 hour |
| Memory bomb via crafted image | Max dimensions enforced: 15360×8640 |
| Unbounded memory via annotations | Undo history capped at 200 |
| Shell injection | All subprocess calls use argument lists, never `shell=True` |
| Clipboard exfiltration | Only `image/png` MIME type written |
| Dependency supply chain | System packages only via `apt`; no PyPI runtime downloads |

---

## Development Conventions

### Code Style
- **Type hints** on all function signatures
- **Docstrings** on all public classes and functions
- **No magic numbers** — all constants in `config.py`
- **No `shell=True`** in subprocess calls
- **Pure functions** where possible (e.g., `_render_annotation`)
- **Single responsibility** per module
- **Frozen dataclasses** for immutable configuration objects

### Git Conventions
- Branch: `main`
- Commit style: [Conventional Commits](https://conventionalcommits.org)
  - `feat:` new feature
  - `fix:` bug fix
  - `docs:` documentation
  - `refactor:` code restructure
  - `security:` security improvement

### Testing
- Run from source: `python3 -m cosmicsnip.app`
- The dev launcher at `~/.local/bin/cosmicsnip` points to `~/Projects/cosmicsnip` so changes are live

---

## TODO / Roadmap

### P0 — Must fix
- [ ] Fix capture filename glob to match `[Ss]creenshot*.png`
- [ ] Fix transient parent warning on error dialog
- [ ] Test full flow: capture → select → edit → copy → paste into browser

### P1 — Polish
- [ ] Migrate to libadwaita (`Adw.Application`, `Adw.ApplicationWindow`, `Adw.HeaderBar`)
- [ ] Auto-copy to clipboard on selection release (before editor opens)
- [ ] Smooth pen strokes (line interpolation / bezier curves)
- [ ] Delay overlay appearance until screenshot capture completes (no flash)
- [ ] Window should center on the monitor where the selection was made
- [ ] Add a "New Snip" button in the editor to start over
- [ ] Add text annotation tool

### P2 — Distribution
- [ ] Create `debian/` packaging for `.deb` distribution
- [ ] Add Flatpak manifest
- [ ] Add app icon (SVG)
- [ ] Submit to Flathub
- [ ] Create GitHub Actions CI for linting

### P3 — Future
- [ ] Record GIF/video clips
- [ ] OCR text extraction from selection
- [ ] Direct upload to Imgur/clipboard history
- [ ] Multi-monitor awareness (capture specific monitor)

---

## System Dependencies

```bash
sudo apt install -y \
    python3-gi \
    gir1.2-gtk-4.0 \
    gir1.2-adw-1 \
    python3-pil \
    python3-dbus \
    python3-cairo \
    wl-clipboard \
    libnotify-bin
```

---

## How to Run

```bash
cd ~/Projects/cosmicsnip
python3 -m cosmicsnip.app
```

## How to Install System-Wide

```bash
chmod +x install.sh
./install.sh
source ~/.bashrc
cosmicsnip
```

Then bind `cosmicsnip` to **Super+Shift+S** in COSMIC Settings → Keyboard → Shortcuts.
