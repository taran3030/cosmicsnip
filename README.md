# CosmicSnip

Screenshot snipping tool with annotation for **COSMIC Desktop** on Pop!_OS 24.04.

The only capture + annotate tool that works natively on COSMIC's Wayland compositor.

---

## Why CosmicSnip?

COSMIC Desktop uses its own Wayland compositor, which breaks every existing screenshot tool:

| Tool | Problem on COSMIC |
|------|-------------------|
| `grim` / `slurp` | Requires `wlr-screencopy` — COSMIC doesn't expose it |
| `flameshot` | Crashes on COSMIC Wayland |
| `gnome-screenshot` | No Wayland support, X11 only |
| COSMIC built-in | Captures full screen only — no region select, no annotation |

CosmicSnip works because it uses the **XDG Desktop Portal** (`cosmic-screenshot`) for capture — the same protocol COSMIC itself uses. Everything else is native GTK4 + Cairo, no X11 compatibility layers.

---

## Features

**Capture**
- Drag-to-select any region across one or multiple monitors
- Per-monitor fullscreen overlays via `gtk4-layer-shell`
- Esc or right-click to cancel

**Annotate**
- Pen, highlighter, arrow, rectangle tools
- 6-colour palette + adjustable stroke width
- Draw beyond the screenshot edge — canvas extends past the image bounds
- Full undo (Ctrl+Z, unlimited)

**Output**
- Auto-copies to clipboard on capture (paste immediately)
- Transparent PNG — annotations outside the image are on a transparent background
- Auto-trims to content bounds (no wasted space)
- Save As dialog with path control (Ctrl+S)

**System integration**
- System tray icon in COSMIC's panel bar
- Stays alive between snips — re-activate from dock, tray, or Ctrl+N
- Single-instance: launching again brings back the running app
- Native libadwaita look matching COSMIC's dark theme

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `P` `H` `A` `R` | Switch tool (Pen / Highlighter / Arrow / Rectangle) |
| `Ctrl+C` | Copy to clipboard (with annotations) |
| `Ctrl+S` | Save as PNG |
| `Ctrl+Z` | Undo |
| `Ctrl+N` | New screenshot |
| `Ctrl+Q` | Quit |
| `Esc` | Close editor / cancel selection |

---

## Install

### From .deb (recommended)

Download from [Releases](https://github.com/taran3030/cosmicsnip/releases/latest):

```bash
sudo apt install ./cosmicsnip_1.0.0-1_all.deb
```

### From source

```bash
git clone https://github.com/taran3030/cosmicsnip.git
cd cosmicsnip
bash install.sh
```

### Set up a keyboard shortcut

**COSMIC Settings → Keyboard → Custom Shortcuts → +**

| Field | Value |
|-------|-------|
| Name | CosmicSnip |
| Command | `cosmicsnip` |
| Shortcut | `Super+Shift+S` |

---

## Uninstall

```bash
sudo apt remove cosmicsnip
```

---

## Build .deb from source

```bash
git clone https://github.com/taran3030/cosmicsnip.git
cd cosmicsnip
./build-deb.sh
sudo apt install ./dist/cosmicsnip_1.0.0-1_all.deb
```

Build requires: `python3`, `dpkg-deb`

---

## Run without installing

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
                 python3-pil python3-dbus python3-cairo libnotify-bin
python3 -m cosmicsnip.app
```

---

## Security

CosmicSnip is designed to handle screenshots safely. Screenshots are sensitive data — they can contain passwords, tokens, personal information.

### What we do

- **No root execution** — hard exit if run as root
- **No network access** — nothing leaves your machine. No telemetry, no cloud, no updates phoning home
- **Temp file hardening** — screenshots are written to `$XDG_RUNTIME_DIR/cosmicsnip/` with mode `0600`, owned by your user. Temp dir ownership is verified at startup
- **Symlink attack prevention** — all file operations use `O_NOFOLLOW` and reject symlinks. Config files that are symlinks are refused
- **Path traversal protection** — all paths are resolved and validated against allowed directories before any read/write
- **TOCTOU-safe file operations** — chmod uses fd-based `fchmod()`, not path-based, to prevent race conditions
- **PNG validation** — captured files are verified by magic bytes before processing
- **PIL decompression bomb limit** — prevents memory exhaustion from malformed images
- **Sandboxed XDG paths** — `XDG_RUNTIME_DIR`, `XDG_PICTURES_DIR` etc. are validated to be within `$HOME`, `/run`, or `/tmp`
- **Save path restrictions** — blocks saving to system directories (`/etc`, `/usr`, `/bin`, `/proc`, etc.)
- **Process umask `0077`** — all files created by the app are owner-only by default
- **Log file permissions** — `0600`, rotated with 512KB limit
- **Subprocess hardening** — `notify-send` calls are truncated and time-limited (5s)

### What we don't do

- We don't encrypt screenshots at rest. They're saved as standard PNGs in `~/Pictures/screenshots/`
- We don't clear clipboard after a timeout. Your screenshot stays on the clipboard until you copy something else
- We don't sandbox the Python process beyond standard user permissions

### Reporting vulnerabilities

If you find a security issue, please open a [GitHub issue](https://github.com/taran3030/cosmicsnip/issues) or email the maintainer directly. We take security seriously — this tool handles your screen content.

---

## Tech stack

| Component | Detail |
|-----------|--------|
| Capture | `cosmic-screenshot` via XDG Desktop Portal |
| UI | GTK4 + libadwaita (PyGObject) |
| Drawing | Cairo 2D (pycairo) |
| Clipboard | GTK4 native `Gdk.ContentProvider` |
| Overlay | `gtk4-layer-shell` per-monitor surfaces |
| Tray | DBus StatusNotifierItem protocol |
| Packaging | dpkg `.deb` |
| Language | Python 3.12 |

---

## Release history

### v1.0.0 — 2026-03-16

First stable release.

- Libadwaita UI (Adw.ApplicationWindow, HeaderBar, ToastOverlay)
- System tray icon via DBus StatusNotifierItem
- App persistence — stays alive between snips
- Out-of-bounds annotation with auto-trim transparent PNG output
- Multi-monitor layer-shell overlays with shared selection state
- Monitor detection with config caching
- Multi-arch layer-shell support (x86_64, aarch64)

### v0.2.0 — 2026-03-16

Security hardening and multi-monitor support.

- Per-monitor overlays via `gtk4-layer-shell`
- TOCTOU fix in temp file chmod
- PIL decompression bomb limit
- Removed dead `wl-copy` code (GTK4 native clipboard)
- Log/temp file permission hardening
- Save path validation
- XDG path sanitization

### v0.1.0 — 2026-03-13

Initial release.

- Screen capture via `cosmic-screenshot`
- Drag-to-select overlay
- Annotation editor with pen, highlighter, arrow, rectangle
- GTK4 native clipboard
- Basic security (root refusal, symlink checks)

---

## Contributing

Issues and PRs welcome. If something breaks on your COSMIC setup, open an issue with the log:

```bash
cosmicsnip --debug
cat ~/.local/share/cosmicsnip/cosmicsnip.log
```

---

## License

MIT
