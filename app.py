#!/usr/bin/env python3
"""
CosmicSnip — application entry point.

Orchestrates the capture → select → edit flow.
"""

import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gtk, Gdk

from cosmicsnip import __app_id__
from cosmicsnip.config import ensure_directories
from cosmicsnip.capture import capture_screen, cleanup_temp_files, CaptureError
from cosmicsnip.overlay import SelectionOverlay
from cosmicsnip.editor import SnipEditor

from PIL import Image


class CosmicSnipApp(Gtk.Application):
    """Top-level application managing the capture → select → edit lifecycle."""

    def __init__(self):
        super().__init__(application_id=__app_id__)
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app):
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
        try:
            image_path = capture_screen()
        except CaptureError as exc:
            self._show_error(str(exc))
            return

        # Show selection overlay
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
        try:
            img = Image.open(image_path)
            cropped = img.crop((x1, y1, x2, y2))

            # Save cropped image (reuse path to keep it simple)
            import time
            from cosmicsnip.config import SAVE_DIR
            ts = time.strftime("%Y%m%d-%H%M%S")
            crop_path = str(SAVE_DIR / f"snip-{ts}.png")
            cropped.save(crop_path, "PNG")

            editor = SnipEditor(app=self, image_path=crop_path)
            editor.present()
        except Exception as exc:
            self._show_error(f"Failed to crop image: {exc}")

    def _on_cancelled(self):
        """User pressed Escape during selection."""
        self.quit()

    def _show_error(self, message: str):
        """Display an error dialog and quit."""
        dialog = Gtk.AlertDialog()
        dialog.set_message("CosmicSnip Error")
        dialog.set_detail(message)
        dialog.set_buttons(["OK"])
        dialog.choose(None, None, lambda _d, _r: self.quit())


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
    app = CosmicSnipApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
