#!/bin/bash
set -euo pipefail

echo "╔══════════════════════════════════════╗"
echo "║       CosmicSnip  —  Installer       ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. System dependencies ───────────────────────────────────────────────────
echo "[1/5] Installing system dependencies..."
sudo apt install -y \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-4.0 \
    gir1.2-adw-1 \
    python3-pil \
    python3-dbus \
    python3-cairo \
    libnotify-bin

# ── 2. Directories ───────────────────────────────────────────────────────────
echo "[2/5] Creating directories..."
mkdir -p ~/.local/bin
mkdir -p ~/.local/share/applications
mkdir -p ~/.local/share/icons/hicolor/scalable/apps
mkdir -p ~/Pictures/screenshots

# ── 3. Install package ───────────────────────────────────────────────────────
echo "[3/5] Installing CosmicSnip..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Copy the package
INSTALL_DIR="$HOME/.local/share/cosmicsnip"
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/cosmicsnip" "$INSTALL_DIR/"

# Create launcher script
cat > ~/.local/bin/cosmicsnip << LAUNCHER
#!/bin/bash
export PYTHONPATH="\$HOME/.local/share/cosmicsnip:\$PYTHONPATH"
# Preload gtk4-layer-shell for per-monitor overlay support on Wayland
for lib in /usr/local/lib/x86_64-linux-gnu/libgtk4-layer-shell.so \
           /usr/local/lib/aarch64-linux-gnu/libgtk4-layer-shell.so \
           /usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so \
           /usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so; do
    if [ -f "\$lib" ]; then
        export LD_PRELOAD="\${lib}\${LD_PRELOAD:+:\$LD_PRELOAD}"
        break
    fi
done
exec python3 -m cosmicsnip.app "\$@"
LAUNCHER
chmod +x ~/.local/bin/cosmicsnip

# Install app icon
cp "$SCRIPT_DIR/data/icons/hicolor/scalable/apps/io.github.itssoup.CosmicSnip.svg" \
   ~/.local/share/icons/hicolor/scalable/apps/

# Autostart entry — tray icon on login
mkdir -p ~/.config/autostart
cp "$SCRIPT_DIR/data/io.github.itssoup.CosmicSnip-autostart.desktop" \
   ~/.config/autostart/
# Fix path for local install
sed -i "s|Exec=cosmicsnip|Exec=$HOME/.local/bin/cosmicsnip|" \
   ~/.config/autostart/io.github.itssoup.CosmicSnip-autostart.desktop

# ── 4. Desktop entry ────────────────────────────────────────────────────────
echo "[4/5] Creating desktop entry..."
cat > ~/.local/share/applications/io.github.itssoup.CosmicSnip.desktop << EOF
[Desktop Entry]
Name=CosmicSnip
GenericName=Screenshot Tool
Comment=Capture, annotate, and copy screenshots
Exec=$HOME/.local/bin/cosmicsnip
Icon=io.github.itssoup.CosmicSnip
Type=Application
Categories=Utility;Graphics;GTK;
Keywords=screenshot;snip;capture;annotate;clip;
StartupNotify=false
Actions=capture

[Desktop Action capture]
Name=Take Screenshot
Exec=$HOME/.local/bin/cosmicsnip
EOF

# ── 5. Refresh desktop database & PATH ──────────────────────────────────────
echo "[5/5] Verifying PATH and refreshing app launcher..."
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true
gtk-update-icon-cache -f ~/.local/share/icons/hicolor/ 2>/dev/null || true
if ! grep -qF '.local/bin' ~/.bashrc 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    echo "  → Added ~/.local/bin to PATH (run: source ~/.bashrc)"
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║         Installation complete        ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "  Run:          cosmicsnip"
echo "  App menu:     Super → CosmicSnip"
echo ""
echo "  Keyboard shortcut (recommended):"
echo "    COSMIC Settings → Keyboard → Shortcuts"
echo "    Command:  cosmicsnip"
echo "    Bind to:  Super+Shift+S"
echo ""
echo "  Controls:"
echo "    Drag       Select area"
echo "    P/H/A/R    Switch tool (Pen/Highlighter/Arrow/Rectangle)"
echo "    Ctrl+C     Copy to clipboard"
echo "    Ctrl+Z     Undo annotation"
echo "    Ctrl+S     Save to ~/Pictures/screenshots/"
echo "    Escape     Close"
echo ""
