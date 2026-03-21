"""App lifecycle — persistent tray-style app with capture → overlay → editor flow.

The app stays alive between snips. Re-activate via dock icon, keyboard shortcut,
or the New Snip button in the editor.
"""

import os
import sys
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, GLib, Adw

from cosmicsnip import __app_id__
from cosmicsnip.log import setup_logging, get_logger
from cosmicsnip.security import refuse_root, validate_path_within
from cosmicsnip.config import ensure_directories, SAVE_DIR
from cosmicsnip.capture import capture_screen, cleanup_temp_files, cleanup_file, CaptureError
from cosmicsnip.overlay import SelectionOverlay
from cosmicsnip.monitors import get_monitors
from cosmicsnip.editor import SnipEditor
from cosmicsnip.tray import TrayIcon

from PIL import Image

log = get_logger("app")


class CosmicSnipApp(Adw.Application):
    """Persistent screenshot app. Stays alive between snips.

    First activate: hold() + start capture.
    Dock click / Ctrl+N: re-activate → new capture.
    Ctrl+Q: quit for real.
    """

    def __init__(self, tray_only=False):
        super().__init__(application_id=__app_id__)
        self._css_loaded = False
        self._overlay = None
        self._held = False
        self._tray = None
        self._tray_only = tray_only
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app):
        log.info("App activated.")
        ensure_directories()
        cleanup_temp_files()

        # Keep the app alive between snips
        if not self._held:
            self.hold()
            self._held = True
            self._tray = TrayIcon(app=self, on_activate=self._start_capture)
            self._tray.register()

        if not self._css_loaded:
            css = Gtk.CssProvider()
            css.load_from_string(_APP_CSS)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            self._css_loaded = True

        # --tray: first launch sits idle with tray icon only
        if self._tray_only:
            log.info("Started in tray-only mode — waiting for activation.")
            self._tray_only = False  # subsequent activations start capture
            return

        self._start_capture()

    def _start_capture(self):
        # Clean up any existing overlay before starting a new one
        if self._overlay:
            self._overlay.hide_all()
            self._overlay = None

        log.info("Starting screen capture...")
        try:
            image_path = capture_screen()
            log.info("Capture succeeded: %s", image_path)
        except CaptureError as exc:
            log.error("Capture failed: %s", exc)
            self._show_error(str(exc))
            return

        monitors = get_monitors()
        log.info("Monitor layout: %d monitor(s) — %s", len(monitors),
                 ", ".join(f"{m.name}:{m.width}x{m.height}+{m.x}+{m.y}" for m in monitors))

        log.info("Presenting selection overlay.")
        self._overlay = SelectionOverlay(
            app=self, image_path=image_path,
            on_selected=self._on_region_selected,
            on_cancelled=self._on_cancelled,
            monitors=monitors,
        )
        self._overlay.present()

    # ── Callbacks ────────────────────────────────────────────────────────

    def _on_region_selected(self, image_path, x1, y1, x2, y2):
        log.info("Region selected: (%d,%d)→(%d,%d)  size=%dx%d",
                 x1, y1, x2, y2, x2 - x1, y2 - y1)
        try:
            img = Image.open(image_path)
            cropped = img.crop((x1, y1, x2, y2))

            ts = time.strftime("%Y%m%d-%H%M%S")
            crop_path = str(SAVE_DIR / f"snip-{ts}.png")
            validate_path_within(crop_path, SAVE_DIR)
            cropped.save(crop_path, "PNG")
            log.info("Cropped image saved: %s", crop_path)
            cleanup_file(image_path)

            log.info("Opening editor: %s", crop_path)
            editor = SnipEditor(app=self, image_path=crop_path)

            # Hide overlays only after editor has a live Wayland surface
            overlay_ref = self._overlay
            self._overlay = None

            def _on_editor_mapped(_widget):
                if overlay_ref:
                    log.info("Editor mapped — hiding overlays.")
                    overlay_ref.hide_all()

            editor.connect("map", _on_editor_mapped)
            editor.present()

        except Exception as exc:
            log.exception("Failed to crop/open: %s", exc)
            self._overlay = None
            self._show_error(f"Failed to crop image: {exc}")

    def _on_cancelled(self):
        """Selection cancelled — go idle, don't quit. App stays in dock."""
        log.info("Selection cancelled — waiting in background.")
        if self._overlay:
            self._overlay.hide_all()
        self._overlay = None

    def _show_error(self, message):
        parent = Gtk.Window(application=self)
        parent.set_visible(False)
        dialog = Gtk.AlertDialog()
        dialog.set_message("CosmicSnip Error")
        dialog.set_detail(message)
        dialog.set_buttons(["OK"])
        dialog.choose(parent, None, lambda _d, _r: None)


# ── CSS ──────────────────────────────────────────────────────────────────────

_APP_CSS = """
.snip-pill {
    background: rgba(30, 30, 46, 0.85);
    color: rgba(255, 255, 255, 0.95);
    border-radius: 16px;
    padding: 12px 28px;
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.5px;
    border: 1px solid rgba(255, 255, 255, 0.08);
}
"""


# ── Entry point ──────────────────────────────────────────────────────────────

_LAYER_SHELL_PATHS = [
    "/usr/local/lib/x86_64-linux-gnu/libgtk4-layer-shell.so",
    "/usr/local/lib/aarch64-linux-gnu/libgtk4-layer-shell.so",
    "/usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so",
    "/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so",
]


def _ensure_layer_shell_preload():
    """Re-exec with LD_PRELOAD if needed for gtk4-layer-shell."""
    current = os.environ.get("LD_PRELOAD", "")
    if "libgtk4-layer-shell" in current:
        return
    lib = next((p for p in _LAYER_SHELL_PATHS if os.path.isfile(p)), None)
    if not lib:
        return
    os.environ["LD_PRELOAD"] = f"{lib}:{current}" if current else lib
    os.execv(sys.executable, [sys.executable, "-m", "cosmicsnip.app"] +
             [a for a in sys.argv[1:] if a != sys.argv[0]])


def main():
    _ensure_layer_shell_preload()
    os.umask(0o077)
    setup_logging(debug="--debug" in sys.argv)
    refuse_root()
    tray_only = "--tray" in sys.argv
    gtk_argv = [a for a in sys.argv if a not in ("--debug", "--tray")]
    app = CosmicSnipApp(tray_only=tray_only)
    app.run(gtk_argv)


if __name__ == "__main__":
    main()
