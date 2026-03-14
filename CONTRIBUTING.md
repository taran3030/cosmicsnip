# Contributing to CosmicSnip

Thanks for your interest in contributing! This project follows a few conventions
to keep the codebase clean and maintainable.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/itssoup/cosmicsnip.git
cd cosmicsnip

# Install system dependencies
sudo apt install -y \
    python3-gi gir1.2-gtk-4.0 python3-pil \
    python3-dbus python3-cairo wl-clipboard libnotify-bin

# Run directly from source
python3 -m cosmicsnip.app
```

## Project Structure

```
cosmicsnip/
├── __init__.py      # Package metadata, version
├── app.py           # Application entry point, lifecycle orchestration
├── capture.py       # Screen capture backends
├── clipboard.py     # Clipboard operations (wl-copy)
├── config.py        # Constants, paths, security limits, tool/color defs
├── editor.py        # Annotation editor window + rendering
└── overlay.py       # Fullscreen region selection overlay
```

## Code Style

- **Type hints** on all function signatures.
- **Docstrings** on all public classes and functions.
- **No `shell=True`** in subprocess calls (security requirement).
- **Constants in `config.py`** — no magic numbers in other modules.
- **Stateless rendering** — `_render_annotation()` is a pure function.
- Keep modules focused: each file handles one responsibility.

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add circle annotation tool
fix: handle missing cosmic-screenshot gracefully
docs: update install instructions for Fedora
security: restrict temp file permissions
```

## Pull Request Process

1. Fork the repository and create a feature branch.
2. Run the app and verify your changes work on COSMIC/Wayland.
3. Update documentation if adding new features.
4. Keep PRs focused — one feature or fix per PR.
5. Add a description explaining *what* and *why*.

## Adding a New Drawing Tool

1. Add a `ToolDef` entry in `config.py → TOOLS`.
2. Handle the new tool type in `editor.py → _build_current_annotation()`.
3. Add rendering logic in `editor.py → _render_annotation()`.
4. Add a hotkey mapping in `editor.py → _on_key()`.

## Security Considerations

- Screenshots may contain sensitive data. See `SECURITY.md`.
- Always use `config.TEMP_FILE_MODE` when creating temp files.
- Never use `shell=True` in subprocess calls.
- Validate image dimensions before loading (see `capture.py`).
