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
    gir1.2-gtk-4.0 \
    python3-pil \
    python3-dbus \
    python3-cairo \
    wl-clipboard \
    libnotify-bin

# ── 2. Directories ───────────────────────────────────────────────────────────
echo "[2/5] Creating directories..."
mkdir -p ~/.local/bin
mkdir -p ~/.local/share/applications
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
cat > ~/.local/bin/cosmicsnip << 'LAUNCHER'
#!/bin/bash
exec python3 -m cosmicsnip.app "$@"
LAUNCHER
chmod +x ~/.local/bin/cosmicsnip

# Add the install dir to PYTHONPATH in the launcher
sed -i "1a export PYTHONPATH=\"\$HOME/.local/share/cosmicsnip:\$PYTHONPATH\"" ~/.local/bin/cosmicsnip

# ── 4. Desktop entry ────────────────────────────────────────────────────────
echo "[4/5] Creating desktop entry..."
cat > ~/.local/share/applications/io.github.itssoup.CosmicSnip.desktop << EOF
[Desktop Entry]
Name=CosmicSnip
GenericName=Screenshot Tool
Comment=Capture, annotate, and copy screenshots
Exec=$HOME/.local/bin/cosmicsnip
Icon=accessories-screenshot
Type=Application
Categories=Utility;Graphics;GTK;
Keywords=screenshot;snip;capture;annotate;clip;
StartupNotify=false
Actions=

[Desktop Action capture]
Name=Take Screenshot
Exec=$HOME/.local/bin/cosmicsnip
EOF

# ── 5. PATH check ───────────────────────────────────────────────────────────
echo "[5/5] Verifying PATH..."
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
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
