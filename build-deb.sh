#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# build-deb.sh  —  Build a standalone .deb package for CosmicSnip
#
# Usage:
#   chmod +x build-deb.sh
#   ./build-deb.sh
#
# Output:
#   dist/cosmicsnip_0.1.0-1_all.deb
#
# Install with:
#   sudo apt install ./dist/cosmicsnip_0.1.0-1_all.deb
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VERSION="0.1.0"
PACKAGE="cosmicsnip"
PKG_DIR="dist/${PACKAGE}_${VERSION}-1_all"

echo "╔══════════════════════════════════════╗"
echo "║     CosmicSnip  —  .deb Builder      ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. Check build dependencies ──────────────────────────────────────────────
echo "[1/5] Checking build dependencies..."
for cmd in python3 dpkg-deb; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "  ERROR: '$cmd' not found."
        echo "  Install with: sudo apt install dpkg python3"
        exit 1
    fi
done
echo "  OK"

# ── 2. Create package tree ────────────────────────────────────────────────────
echo "[2/5] Creating package tree at $PKG_DIR ..."
rm -rf "$PKG_DIR"

# Python package — exclude __pycache__ and compiled bytecode
SITE="$PKG_DIR/usr/lib/python3/dist-packages"
mkdir -p "$SITE"
cp -r cosmicsnip "$SITE/"
find "$SITE/cosmicsnip" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$SITE/cosmicsnip" -name "*.pyc" -delete 2>/dev/null || true

# Launcher script
mkdir -p "$PKG_DIR/usr/bin"
cat > "$PKG_DIR/usr/bin/cosmicsnip" << 'LAUNCHER'
#!/bin/bash
exec python3 -m cosmicsnip.app "$@"
LAUNCHER
chmod 755 "$PKG_DIR/usr/bin/cosmicsnip"

# Desktop entry
mkdir -p "$PKG_DIR/usr/share/applications"
cp data/io.github.itssoup.CosmicSnip.desktop \
   "$PKG_DIR/usr/share/applications/"

# AppStream metadata
mkdir -p "$PKG_DIR/usr/share/metainfo"
cp data/io.github.itssoup.CosmicSnip.metainfo.xml \
   "$PKG_DIR/usr/share/metainfo/"

# Doc files
mkdir -p "$PKG_DIR/usr/share/doc/$PACKAGE"
cp README.md  "$PKG_DIR/usr/share/doc/$PACKAGE/" 2>/dev/null || true
cp LICENSE    "$PKG_DIR/usr/share/doc/$PACKAGE/" 2>/dev/null || true
gzip -9 -c debian/changelog > "$PKG_DIR/usr/share/doc/$PACKAGE/changelog.gz"

# ── 3. Write DEBIAN control files ────────────────────────────────────────────
echo "[3/5] Writing DEBIAN control..."
mkdir -p "$PKG_DIR/DEBIAN"

cat > "$PKG_DIR/DEBIAN/control" << EOF
Package: $PACKAGE
Version: ${VERSION}-1
Section: graphics
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-adw-1, python3-pil, python3-dbus, python3-cairo, wl-clipboard, libnotify-bin
Maintainer: itssoup <itssoup@users.noreply.github.com>
Homepage: https://github.com/itssoup/cosmicsnip
Description: Screenshot snipping tool for COSMIC Desktop / Wayland
 CosmicSnip is a Windows Snipping Tool clone for COSMIC Desktop (Pop!_OS 24.04).
 Captures the screen, lets you drag-select a region, and opens an editor with
 pen, highlighter, arrow, and rectangle annotation tools. Uses the GTK4 native
 Wayland clipboard and the XDG Desktop Portal for capture.
EOF

# Post-install: update desktop database
cat > "$PKG_DIR/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
set -e
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database /usr/share/applications/ 2>/dev/null || true
fi
POSTINST
chmod 755 "$PKG_DIR/DEBIAN/postinst"

# ── 4. Set permissions ────────────────────────────────────────────────────────
echo "[4/5] Setting permissions..."
find "$PKG_DIR" -type d -exec chmod 755 {} \;
find "$PKG_DIR" -type f -exec chmod 644 {} \;
chmod 755 "$PKG_DIR/usr/bin/cosmicsnip"
chmod 755 "$PKG_DIR/DEBIAN/postinst"

# ── 5. Build .deb ─────────────────────────────────────────────────────────────
echo "[5/5] Building .deb..."
mkdir -p dist
dpkg-deb --build --root-owner-group "$PKG_DIR" \
    "dist/${PACKAGE}_${VERSION}-1_all.deb"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║         Build complete!              ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "  Package:  dist/${PACKAGE}_${VERSION}-1_all.deb"
echo ""
echo "  Install:"
echo "    sudo apt install ./dist/${PACKAGE}_${VERSION}-1_all.deb"
echo ""
echo "  Uninstall:"
echo "    sudo apt remove cosmicsnip"
echo ""
