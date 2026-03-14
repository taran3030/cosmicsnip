#!/usr/bin/env python3
"""
CosmicSnip — application entry point.

Orchestrates the capture → select → edit flow.
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
    """Top-level application managing the capture → select → edit lifecycle."""

    def __init__(self):
        super().__init__(application_id=__app_id__)
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app):
        log.info("App activated.")
        # Housekeeping
        ensure_directories()
        cleanup_temp_files()

        # Load global CSS
        css = Gtk.CssProvider()
        css.load_from_string(_APP_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Capture
        log.info("Starting screen capture...")
        try:
            image_path = capture_screen()
            log.info("Capture succeeded: %s", image_path)
        except CaptureError as exc:
            log.error("Capture failed: %s", exc)
            self._show_error(str(exc))
            return

        # Show selection overlay
        log.info("Presenting selection overlay.")
        overlay = SelectionOverlay(
            app=self,
            image_path=image_path,
            on_selected=self._on_region_selected,
            on_cancelled=self._on_cancelled,
        )
        overlay.present()

    def _on_region_selected(
        self, image_path: str, x1: int, y1: int, x2: int, y2: int
    ):
        """Crop the region and open the editor."""
        log.info("Region selected: (%d,%d)→(%d,%d)  size=%dx%d", x1, y1, x2, y2, x2-x1, y2-y1)
        try:
            img = Image.open(image_path)
            cropped = img.crop((x1, y1, x2, y2))

            ts = time.strftime("%Y%m%d-%H%M%S")
            crop_path = str(SAVE_DIR / f"snip-{ts}.png")
            validate_path_within(crop_path, SAVE_DIR)  # guard against traversal
            cropped.save(crop_path, "PNG")
            log.info("Cropped image saved: %s", crop_path)

            # hold() prevents GTK from starting app shutdown when the overlay
            # closes and there are temporarily zero windows.  release() is
            # called inside _open_editor once the editor window is registered.
            self.hold()
            GLib.idle_add(self._open_editor, crop_path)
        except Exception as exc:
            log.exception("Failed to crop/open image: %s", exc)
            self._show_error(f"Failed to crop image: {exc}")

    def _open_editor(self, crop_path: str):
        """Open the editor window (called via idle_add after overlay closes)."""
        log.info("Opening editor: %s", crop_path)
        editor = SnipEditor(app=self, image_path=crop_path)
        editor.present()
        self.release()  # editor window is now registered — safe to release hold

    def _on_cancelled(self):
        """User pressed Escape during selection."""
        log.info("Selection cancelled by user.")
        self.quit()

    def _show_error(self, message: str):
        """Display an error dialog and quit."""
        # AlertDialog requires a parent window; create a hidden one to avoid
        # the 'GtkDialog mapped without a transient parent' warning.
        parent = Gtk.Window(application=self)
        parent.set_visible(False)

        dialog = Gtk.AlertDialog()
        dialog.set_message("CosmicSnip Error")
        dialog.set_detail(message)
        dialog.set_buttons(["OK"])
        dialog.choose(parent, None, lambda _d, _r: self.quit())


# ── Global CSS ───────────────────────────────────────────────────────────────

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


def main():
    """CLI entry point."""
    setup_logging(debug="--debug" in sys.argv)
    refuse_root()  # hard exit if running as root — no elevated privileges needed
    app = CosmicSnipApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
