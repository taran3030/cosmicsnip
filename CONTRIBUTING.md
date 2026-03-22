# Contributing to CosmicSnip

Thanks for helping improve CosmicSnip.

## Development Setup

```bash
git clone https://github.com/itssoup/cosmicsnip.git
cd cosmicsnip
```

Install runtime dependencies (Pop!_OS / Ubuntu):

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
                 python3-dbus python3-cairo libnotify-bin
```

Run from source:

```bash
python3 -m cosmicsnip.app
```

## Debug Mode

Use debug logging during development or bug reports:

```bash
python3 -m cosmicsnip.app --debug
```

Logs are written to:

```bash
~/.local/share/cosmicsnip/cosmicsnip.log
```

## Commit Style

Use Conventional Commits where possible:

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation-only changes
- `refactor:` internal code cleanup without behavior change
- `chore:` maintenance and tooling updates

## Pull Request Process

1. Fork the repository.
2. Create a feature branch from `main`.
3. Keep each PR focused on one logical change.
4. Open the PR against `main` with a clear description and test notes.

## Code Style

- Python code should stay readable and consistent with the existing codebase.
- Prefer clear names and short functions where practical.
- No mandatory linter configuration is enforced yet, but clean code and minimal noise are expected.

## Testing Notes

There is no full automated test suite yet.

Before submitting a PR, run manual smoke tests on COSMIC Wayland:

1. Launch capture from app launcher/tray.
2. Drag-select on single and multi-monitor layouts.
3. Confirm editor tools draw correctly (pen/highlighter/arrow/rect).
4. Verify copy (`Ctrl+C`) and save (`Ctrl+S`) flows.
5. Verify cancel (`Esc`/right-click) and new snip (`Ctrl+N`).

## Security Reports

Please do not file public issues for security vulnerabilities.

Follow the private reporting process in [SECURITY.md](SECURITY.md).
