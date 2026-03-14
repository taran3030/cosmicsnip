# CosmicSnip

A polished screenshot snipping tool for [COSMIC Desktop](https://system76.com/cosmic) and Wayland — built to replicate the Windows Snipping Tool workflow on Linux.

**Capture → Select → Annotate → Copy** — all in one smooth flow.

## Features

- **Area selection** — fullscreen overlay with drag-to-select and live dimension display
- **Annotation editor** — pen, highlighter, arrow, and rectangle tools with color picker
- **Instant clipboard** — auto-copies your snip on capture; Ctrl+C to re-copy after annotating
- **Keyboard-first** — tool hotkeys (P/H/A/R), Ctrl+Z undo, Ctrl+S save, Escape to close
- **Wayland-native** — uses XDG Desktop Portal via `cosmic-screenshot`; no X11 hacks
- **Secure by default** — temp files are permission-restricted and auto-cleaned; no shell injection vectors

## Install

### Pop!_OS 24.04 (recommended)

```bash
git clone https://github.com/itssoup/cosmicsnip.git
cd cosmicsnip
chmod +x install.sh
./install.sh
source ~/.bashrc
```

### Dependencies

Installed automatically by the script:

| Package | Purpose |
|---------|---------|
| `python3-gi` | GTK4 Python bindings |
| `gir1.2-gtk-4.0` | GTK4 introspection |
| `python3-pil` | Image cropping (Pillow) |
| `python3-cairo` | Off-screen rendering |
| `python3-dbus` | D-Bus (future portal support) |
| `wl-clipboard` | Wayland clipboard (`wl-copy`) |
| `libnotify-bin` | Desktop notifications |

### Keyboard Shortcut

For the true Windows Snip experience, bind it in COSMIC Settings:

**Settings → Keyboard → Shortcuts → Add Custom**
- Command: `cosmicsnip`  
- Shortcut: `Super+Shift+S`

## Usage

```bash
cosmicsnip
```

### Flow

1. Screen is captured automatically
2. Fullscreen overlay appears — **drag** to select a region
3. Editor window opens with your cropped snip (already on clipboard)
4. **Annotate** with pen, highlighter, arrows, or rectangles
5. **Ctrl+C** to copy, **Ctrl+S** to save, **Escape** to close

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `P` | Pen tool |
| `H` | Highlighter tool |
| `A` | Arrow tool |
| `R` | Rectangle tool |
| `Ctrl+C` | Copy to clipboard |
| `Ctrl+Z` | Undo last annotation |
| `Ctrl+S` | Save to ~/Pictures/screenshots/ |
| `Escape` | Close window |

## Architecture

```
cosmicsnip/
├── app.py           Lifecycle: capture → overlay → editor
├── capture.py       Screen capture via cosmic-screenshot
├── clipboard.py     Wayland clipboard via wl-copy
├── config.py        All constants, paths, limits, tool/color defs
├── editor.py        GTK4 annotation editor + cairo rendering
└── overlay.py       GTK4 fullscreen region selector
```

**Design principles:**
- Each module has a single responsibility
- All configuration is centralized in `config.py`
- Annotation rendering is a pure function (no side effects)
- Subprocess calls never use `shell=True`
- Temp files use restrictive permissions (`0600`)
- Image dimensions are validated before processing

## Tech Stack

| Layer | Technology |
|-------|-----------|
| UI framework | GTK4 (Python/PyGObject) |
| Drawing | Cairo 2D graphics |
| Image processing | Pillow |
| Clipboard | wl-clipboard (Wayland) |
| Screen capture | cosmic-screenshot (XDG Desktop Portal) |
| Notifications | libnotify |

## Compatibility

| Environment | Status |
|-------------|--------|
| Pop!_OS 24.04 + COSMIC | ✅ Primary target |
| Ubuntu 24.04 + GNOME on Wayland | Should work |
| Fedora + COSMIC | Should work |
| X11 desktops | ❌ Not supported |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and code style.

## Security

See [SECURITY.md](SECURITY.md) for threat model and vulnerability reporting.

## License

[MIT](LICENSE)
