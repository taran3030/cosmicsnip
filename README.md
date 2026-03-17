# CosmicSnip

A Windows Snipping Tool clone built natively for **COSMIC Desktop** on Pop!_OS 24.04.

If you've switched from Windows and miss `Win+Shift+S`, this is it.

---

## What it does

Press a keyboard shortcut → your screen freezes with a dim overlay → drag to select any region across one or both monitors → an editor opens with your crop already copied to clipboard.

From there you can annotate with pen, highlighter, arrow, and rectangle tools, then copy or save.

Annotations can extend outside the screenshot bounds — the output is auto-trimmed to content and saved as transparent PNG.

## Why it exists

No existing screenshot tool works well on COSMIC's Wayland compositor:

- `grim` / `slurp` — require `wlr-screencopy`, which COSMIC does not expose
- `flameshot` — broken on COSMIC Wayland
- COSMIC's built-in screenshot — captures only, no selection overlay or annotation

CosmicSnip uses the **XDG Desktop Portal** (via `cosmic-screenshot`) for capture, GTK4 + libadwaita for the UI, and Cairo for annotation rendering — the same stack COSMIC itself uses.

---

## Features

- Drag-to-select any region — works across multiple monitors
- Annotation tools: pen, highlighter, arrow, rectangle
- Colour palette + adjustable stroke width
- Out-of-bounds drawing — annotate beyond the screenshot edge
- Auto-copies to clipboard on capture
- Transparent PNG output (auto-trimmed to content)
- System tray icon — stays in the panel bar between snips
- New Snip button (Ctrl+N) without restarting the app
- Full undo support (Ctrl+Z)
- Save As dialog (Ctrl+S)
- Keyboard shortcuts: `P` `H` `A` `R` for tools, `Ctrl+C` `Ctrl+Z` `Ctrl+S` `Ctrl+N` `Ctrl+Q`
- Logs to `~/.local/share/cosmicsnip/cosmicsnip.log`

---

## Requirements

- Pop!_OS 24.04 / Ubuntu 24.04 Noble with COSMIC Desktop
- Wayland session
- `cosmic-screenshot` (ships with Pop!_OS 24.04)

All other dependencies are installed automatically.

---

## Install

Download the latest `.deb` from [Releases](https://github.com/taran3030/cosmicsnip/releases):

```bash
sudo apt install ./cosmicsnip_1.0.0-1_all.deb
```

Or install from source:

```bash
git clone https://github.com/taran3030/cosmicsnip.git
cd cosmicsnip
bash install.sh
```

### Keyboard shortcut (recommended)

**COSMIC Settings → Keyboard → Custom Shortcuts → +**
- Name: `CosmicSnip`
- Command: `cosmicsnip`
- Shortcut: `Super+Shift+S`

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

---

## Run without installing

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
                 python3-pil python3-dbus python3-cairo libnotify-bin
python3 -m cosmicsnip.app
```

---

## Tech stack

| Component | Detail |
|-----------|--------|
| Capture | `cosmic-screenshot` via XDG Desktop Portal |
| UI | GTK4 + libadwaita via PyGObject |
| Drawing | Cairo 2D via pycairo |
| Clipboard | GTK4 native `Gdk.ContentProvider` |
| Tray | DBus StatusNotifierItem protocol |
| Packaging | dpkg `.deb` |

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
