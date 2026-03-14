"""
app.py — Application lifecycle orchestrator.

Manages the linear flow: capture → region selection → annotation editor.
Each stage is a separate module; this file wires them together and handles
error recovery and GTK application lifecycle housekeeping.

Changes:
    - CSS provider registered once per process (not on every activation).
    - hold()/release() bracketing extended to the New Snip flow.
    - release() called in crop-failure path to prevent hold count leak.
    - Removed multi-overlay logic; overlay.py now handles multi-monitor
      by showing the full combined image scaled to fit one window.
"""

import sys
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gtk, Gdk, GLib

from cosmicsnip import __app_id__
from cosmicsnip.log import setup_logging, get_logger
from cosmicsnip.security import refuse_root, validate_path_within
from cosmicsnip.config import ensure_directories, SAVE_DIR
from cosmicsnip.capture import capture_screen, cleanup_temp_files, CaptureError
from cosmicsnip.overlay import SelectionOverlay
from cosmicsnip.editor import SnipEditor

from PIL import Image

log = get_logger("app")


class CosmicSnipApp(Gtk.Application):
    """
    Top-level GTK application.

    Lifecycle:
        activate → _on_activate → capture → SelectionOverlay
                                           → _on_region_selected → SnipEditor
                                           → _on_cancelled → quit
    """

    def __init__(self):
        super().__init__(application_id=__app_id__)
        self._css_loaded = False
        self.connect("activate", self._on_activate)

    # ── Activation ────────────────────────────────────────────────────────

    def _on_activate(self, _app):
        """Entry point for each capture session (initial launch and New Snip)."""
        log.info("App activated.")
        ensure_directories()
        cleanup_temp_files()

        if not self._css_loaded:
            css = Gtk.CssProvider()
            css.load_from_string(_APP_CSS)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            self._css_loaded = True

        log.info("Starting screen capture...")
        try:
            image_path = capture_screen()
            log.info("Capture succeeded: %s", image_path)
        except CaptureError as exc:
            log.error("Capture failed: %s", exc)
            self._show_error(str(exc))
            return

        log.info("Presenting selection overlay.")
        overlay = SelectionOverlay(
            app=self,
            image_path=image_path,
            on_selected=self._on_region_selected,
            on_cancelled=self._on_cancelled,
        )
        overlay.present()

    # ── Selection callbacks ───────────────────────────────────────────────

    def _on_region_selected(
        self, image_path: str, x1: int, y1: int, x2: int, y2: int
    ):
        """
        Crop the selected region from the full screenshot and open the editor.

        hold() is called before the overlay closes so GTK does not begin
        shutdown while zero windows exist. release() is called once the
        editor window is registered with the application.
        """
        self.hold()
        log.info(
            "Region selected: (%d,%d)→(%d,%d)  size=%dx%d",
            x1, y1, x2, y2, x2 - x1, y2 - y1,
        )
        try:
            img = Image.open(image_path)
            cropped = img.crop((x1, y1, x2, y2))

            ts = time.strftime("%Y%m%d-%H%M%S")
            crop_path = str(SAVE_DIR / f"snip-{ts}.png")
            validate_path_within(crop_path, SAVE_DIR)
            cropped.save(crop_path, "PNG")
            log.info("Cropped image saved: %s", crop_path)

            GLib.idle_add(self._open_editor, crop_path)
        except Exception as exc:
            log.exception("Failed to crop/open image: %s", exc)
            self.release()
            self._show_error(f"Failed to crop image: {exc}")

    def _open_editor(self, crop_path: str):
        """
        Instantiate and present the editor window.

        Called via idle_add so the overlay has fully closed before the editor
        window is created. release() is called after present() so the editor
        window is registered before the hold count drops to zero.
        """
        log.info("Opening editor: %s", crop_path)
        editor = SnipEditor(app=self, image_path=crop_path)
        editor.present()
        self.release()

    def _on_cancelled(self):
        """User pressed Escape — exit the application."""
        log.info("Selection cancelled by user.")
        self.quit()

    # ── Error display ─────────────────────────────────────────────────────

    def _show_error(self, message: str):
        """
        Display a modal error dialog, then quit.

        A hidden parent window is required by Gtk.AlertDialog to suppress
        the 'GtkDialog mapped without a transient parent' warning.
        """
        parent = Gtk.Window(application=self)
        parent.set_visible(False)

        dialog = Gtk.AlertDialog()
        dialog.set_message("CosmicSnip Error")
        dialog.set_detail(message)
        dialog.set_buttons(["OK"])
        dialog.choose(parent, None, lambda _d, _r: self.quit())


# ── Application CSS ───────────────────────────────────────────────────────────

_APP_CSS = """
    .snip-pill {
        background: rgba(0, 0, 0, 0.78);
        color: white;
        border-radius: 12px;
        padding: 10px 24px;
        font-size: 14px;
        font-weight: 600;
        letter-spacing: 0.3px;
    }
    .dim-label {
        opacity: 0.55;
        font-size: 12px;
    }
    .monospace {
        font-family: monospace;
        font-size: 12px;
    }
"""


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    """CLI entry point — called by the cosmicsnip launcher script."""
    setup_logging(debug="--debug" in sys.argv)
    refuse_root()
    app = CosmicSnipApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
