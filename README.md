# CosmicSnip

A Windows Snipping Tool clone built natively for **COSMIC Desktop** on Pop!_OS 24.04.

If you've switched from Windows and miss `Win+Shift+S`, this is it.

---

## What it does

Press a keyboard shortcut → your screen freezes with a dim overlay → drag to select any region across one or both monitors → an editor opens with your crop already copied to clipboard.

From there you can annotate with pen, highlighter, arrow, and rectangle tools, then paste or save.

## Why it exists

No existing screenshot tool works well on COSMIC's Wayland compositor:

- `grim` / `slurp` — require `wlr-screencopy`, which COSMIC does not expose
- `flameshot` — broken on COSMIC Wayland
- COSMIC's built-in screenshot — captures only, no selection overlay or annotation

CosmicSnip uses the **XDG Desktop Portal** (via `cosmic-screenshot`) for capture, GTK4 for the UI, and Cairo for annotation rendering — the same stack COSMIC itself uses.

---

## Features

- Drag-to-select any region — works across multiple monitors in a single overlay
- Annotation tools: pen, highlighter, arrow, rectangle
- Colour palette + adjustable stroke width
- Auto-copies to clipboard on capture — paste immediately without opening the editor
- Save As dialog with PNG output
- New Snip button (Ctrl+N) to start a fresh capture without restarting the app
- Full undo support
- Keyboard shortcuts: `P` `H` `A` `R` for tools, `Ctrl+C` `Ctrl+Z` `Ctrl+S` `Ctrl+N`
- Logs to `~/.local/share/cosmicsnip/cosmicsnip.log` for debugging

---

## Requirements

- Pop!_OS 24.04 / Ubuntu 24.04 Noble with COSMIC Desktop
- Wayland session
- `cosmic-screenshot` (ships with Pop!_OS 24.04)

All other dependencies are installed automatically with the `.deb`.

---

## Install

Download the latest `.deb` from [Releases](https://github.com/taran3030/cosmicsnip/releases):

```bash
sudo apt install ./cosmicsnip_0.1.0-1_all.deb
```

### Keyboard shortcut

Bind `cosmicsnip` to a shortcut in:

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

## Build from source

```bash
git clone https://github.com/taran3030/cosmicsnip.git
cd cosmicsnip
./build-deb.sh
sudo apt install ./dist/cosmicsnip_0.1.0-1_all.deb
```

**Build dependencies:**
```bash
sudo apt install python3 dpkg
```

---

## Run without installing

```bash
git clone https://github.com/taran3030/cosmicsnip.git
cd cosmicsnip
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
                 python3-pil python3-dbus python3-cairo wl-clipboard libnotify-bin
python3 -m cosmicsnip.app
```

---

## Tech stack

| Component | Detail |
|-----------|--------|
| Capture | `cosmic-screenshot` → XDG Desktop Portal |
| UI | GTK4 via PyGObject |
| Drawing | Cairo 2D via pycairo |
| Clipboard | GTK4 native (`Gdk.ContentProvider`) |
| Packaging | dpkg `.deb` |

---

## Contributing

Issues and pull requests welcome. If something is broken on your COSMIC setup, open an issue and include the log:

```bash
cat ~/.local/share/cosmicsnip/cosmicsnip.log
```

---

## License

MIT
