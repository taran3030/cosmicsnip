"""
editor.py — Annotation editor window.

Displays the cropped screenshot in a scrollable canvas and provides
annotation tools (pen, highlighter, arrow, rectangle) with undo,
clipboard copy, and save-as.

Architecture:
    Annotations are stored as an append-only list of dicts. Each draw
    cycle replays the base image followed by all committed annotations,
    plus an in-progress preview during an active drag. Undo pops the last
    annotation. Copy and Save render all annotations to an off-screen
    cairo surface before writing output.

Changes:
    - Replaced wl-copy subprocess clipboard with GTK4 native clipboard API
      (Gdk.ContentProvider) to prevent Wayland compositor disconnects.
    - Added _auto_copied guard to prevent double clipboard copy when the
      map signal fires more than once.
    - Added Save As dialog (Gtk.FileDialog) replacing fixed-path auto-save.
    - Added New Snip button and Ctrl+N shortcut with hold()/release()
      bracketing to prevent GTK shutdown during the editor→overlay transition.
    - Added transient status bar messages that revert to dimensions after 3s.
    - Added active colour indicator on toolbar swatches.
"""

import io
import math
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_foreign("cairo")

import cairo
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Gio

from cosmicsnip.config import (
    SAVE_DIR,
    TOOLS,
    PALETTE,
    DEFAULT_COLOR,
    DEFAULT_PEN_WIDTH,
    DEFAULT_HIGHLIGHT_WIDTH,
    DEFAULT_ARROW_HEAD_ANGLE,
    DEFAULT_ARROW_HEAD_RATIO,
    MAX_UNDO_HISTORY,
)
from cosmicsnip.clipboard import send_notification
from cosmicsnip.log import get_logger
from cosmicsnip.security import validate_path_within

log = get_logger("editor")

_STATUS_REVERT_MS = 3000


class SnipEditor(Gtk.Window):
    """
    The main editor window shown after a region is selected.

    Args:
        app: Parent Gtk.Application.
        image_path: Path to the cropped PNG file.
    """

    def __init__(self, app: Gtk.Application, image_path: str):
        super().__init__(application=app, title="CosmicSnip")
        self._app = app
        self._image_path = image_path

        # Load image — wrap in try/except in case file was deleted in transit
        try:
            self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
        except Exception as exc:
            log.exception("Failed to load image for editor: %s", exc)
            raise

        self._img_w = self._pixbuf.get_width()
        self._img_h = self._pixbuf.get_height()
        log.info("Editor opened: %dx%d px  path=%s", self._img_w, self._img_h, image_path)

        # Window sizing: fit image but don't exceed 80% of screen
        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        if monitors.get_n_items() > 0:
            mon = monitors.get_item(0)
            geom = mon.get_geometry()
            max_w = int(geom.width * 0.8)
            max_h = int(geom.height * 0.8)
        else:
            max_w, max_h = 1400, 900

        win_w = min(self._img_w + 40, max_w)
        win_h = min(self._img_h + 140, max_h)  # extra for toolbar + status
        self.set_default_size(win_w, win_h)
        self.set_title(f"CosmicSnip  —  {self._img_w} × {self._img_h}")

        # ── Annotation state ──────────────────────────────────────────────
        self._annotations: list[dict] = []
        self._current_stroke: list[tuple[float, float]] = []
        self._drawing = False
        self._shape_start: tuple[float, float] | None = None
        self._shape_end: tuple[float, float] = (0, 0)

        # ── Tool / colour state ───────────────────────────────────────────
        self._active_tool = TOOLS[0].tool_id
        self._color = DEFAULT_COLOR
        self._pen_width = DEFAULT_PEN_WIDTH
        self._highlight_width = DEFAULT_HIGHLIGHT_WIDTH
        self._toggling = False
        self._status_timer_id = 0
        self._auto_copied = False

        # ── Widget tree ───────────────────────────────────────────────────
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)

        root.append(self._build_toolbar())
        root.append(Gtk.Separator())
        root.append(self._build_canvas_area())
        root.append(self._build_statusbar())

        css = Gtk.CssProvider()
        css.load_from_string(_EDITOR_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # ── Keyboard controller ───────────────────────────────────────────
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)

        self.connect("map", self._on_first_map)

    def _on_first_map(self, _w):
        if not self._auto_copied:
            self._auto_copied = True
            GLib.idle_add(self._copy_to_clipboard)

    # ━━ UI BUILDERS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_toolbar(self) -> Gtk.Box:
        """
        Build the horizontal toolbar.

        Layout: tool toggles | colour swatches | stroke width | spacer | actions.
        """
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_margin_start(10)
        bar.set_margin_end(10)
        bar.set_margin_top(8)
        bar.set_margin_bottom(8)

        # ── Tool toggles ──────────────────────────────────────────────────
        tool_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        tool_box.add_css_class("linked")

        self._tool_buttons: dict[str, Gtk.ToggleButton] = {}
        for tdef in TOOLS:
            btn = Gtk.ToggleButton()
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            inner.append(Gtk.Image.new_from_icon_name(tdef.icon_name))
            inner.append(Gtk.Label(label=f" {tdef.label}"))
            btn.set_child(inner)
            btn.set_tooltip_text(tdef.tooltip)
            btn.connect("toggled", self._on_tool_toggled, tdef.tool_id)
            if tdef.tool_id == self._active_tool:
                btn.set_active(True)
            tool_box.append(btn)
            self._tool_buttons[tdef.tool_id] = btn

        bar.append(tool_box)
        bar.append(_vsep())

        # ── Colour swatches ───────────────────────────────────────────────
        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._color_buttons: dict[str, Gtk.Button] = {}

        for tc in PALETTE:
            btn = Gtk.Button()
            btn.set_size_request(30, 30)
            btn.set_tooltip_text(tc.label)
            btn.add_css_class("color-swatch")
            swatch = Gtk.DrawingArea()
            swatch.set_content_width(20)
            swatch.set_content_height(20)
            swatch.set_draw_func(self._make_swatch_draw(tc.rgba))
            btn.set_child(swatch)
            btn.connect("clicked", self._on_color_clicked, tc)
            color_box.append(btn)
            self._color_buttons[tc.name] = btn

        self._color_buttons[self._color.name].add_css_class("color-active")
        bar.append(color_box)
        bar.append(_vsep())

        # ── Stroke width ──────────────────────────────────────────────────
        thin_btn = Gtk.Button(child=Gtk.Label(label="╌"))
        thin_btn.set_tooltip_text("Thinner stroke  [ –  ]")
        thin_btn.connect("clicked", lambda _: self._adjust_width(-1))
        bar.append(thin_btn)

        self._width_label = Gtk.Label(label=f" {self._pen_width}px ")
        self._width_label.add_css_class("monospace")
        bar.append(self._width_label)

        thick_btn = Gtk.Button(child=Gtk.Label(label="━"))
        thick_btn.set_tooltip_text("Thicker stroke  [ +  ]")
        thick_btn.connect("clicked", lambda _: self._adjust_width(1))
        bar.append(thick_btn)

        # ── Spacer ────────────────────────────────────────────────────────
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)

        # ── Actions ───────────────────────────────────────────────────────
        undo_btn = Gtk.Button(child=Gtk.Image.new_from_icon_name("edit-undo-symbolic"))
        undo_btn.set_tooltip_text("Undo last annotation  (Ctrl+Z)")
        undo_btn.connect("clicked", lambda _: self._undo())
        bar.append(undo_btn)

        new_btn = Gtk.Button()
        new_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        new_inner.append(Gtk.Image.new_from_icon_name("camera-photo-symbolic"))
        new_inner.append(Gtk.Label(label="New"))
        new_btn.set_child(new_inner)
        new_btn.set_tooltip_text("Start a new snip  (Ctrl+N)")
        new_btn.connect("clicked", lambda _: self._new_snip())
        bar.append(new_btn)

        copy_btn = Gtk.Button()
        copy_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        copy_inner.append(Gtk.Image.new_from_icon_name("edit-copy-symbolic"))
        copy_inner.append(Gtk.Label(label="Copy"))
        copy_btn.set_child(copy_inner)
        copy_btn.set_tooltip_text("Copy annotated image to clipboard  (Ctrl+C)")
        copy_btn.add_css_class("suggested-action")
        copy_btn.connect("clicked", lambda _: self._copy_to_clipboard())
        bar.append(copy_btn)

        save_btn = Gtk.Button()
        save_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        save_inner.append(Gtk.Image.new_from_icon_name("document-save-symbolic"))
        save_inner.append(Gtk.Label(label="Save"))
        save_btn.set_child(save_inner)
        save_btn.set_tooltip_text("Save annotated image  (Ctrl+S)")
        save_btn.connect("clicked", lambda _: self._save_as_dialog())
        bar.append(save_btn)

        return bar

    def _build_canvas_area(self) -> Gtk.ScrolledWindow:
        """Scrollable drawing canvas sized to the image."""
        scroll = Gtk.ScrolledWindow()
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._canvas = Gtk.DrawingArea()
        self._canvas.set_content_width(self._img_w)
        self._canvas.set_content_height(self._img_h)
        self._canvas.set_draw_func(self._on_draw)
        self._canvas.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self._canvas.add_controller(drag)

        scroll.set_child(self._canvas)
        return scroll

    def _build_statusbar(self) -> Gtk.Box:
        """Bottom status strip showing image dimensions and action feedback."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.set_margin_start(12)
        bar.set_margin_end(12)
        bar.set_margin_top(6)
        bar.set_margin_bottom(6)

        # Initial text shows dimensions only — "Copied" appears after auto-copy fires
        self._status = Gtk.Label(label=f"{self._img_w} × {self._img_h} px")
        self._status.set_halign(Gtk.Align.START)
        self._status.add_css_class("dim-label")
        bar.append(self._status)

        return bar

    # ━━ DRAWING ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_draw(self, _area, cr, w, h):
        """
        Render the canvas: base image → committed annotations → live preview.
        """
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()

        for ann in self._annotations:
            _render_annotation(cr, ann)

        if self._drawing:
            preview = self._build_current_annotation()
            if preview:
                _render_annotation(cr, preview)

    def _build_current_annotation(self) -> dict | None:
        """Build a preview annotation dict for the in-progress stroke/shape."""
        t = self._active_tool
        color = self._color.rgba
        if t == "pen" and len(self._current_stroke) > 1:
            return {"type": "pen", "points": list(self._current_stroke),
                    "color": color, "width": self._pen_width}
        if t == "highlighter" and len(self._current_stroke) > 1:
            hc = (color[0], color[1], color[2], 0.35)
            return {"type": "highlighter", "points": list(self._current_stroke),
                    "color": hc, "width": self._highlight_width}
        if t == "arrow" and self._shape_start:
            return {"type": "arrow", "start": self._shape_start,
                    "end": self._shape_end, "color": color, "width": self._pen_width}
        if t == "rectangle" and self._shape_start:
            return {"type": "rect", "start": self._shape_start,
                    "end": self._shape_end, "color": color, "width": self._pen_width}
        return None

    # ━━ INPUT HANDLERS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_drag_begin(self, gesture, x, y):
        self._drawing = True
        t = self._active_tool
        if t in ("pen", "highlighter"):
            self._current_stroke = [(x, y)]
        else:
            self._shape_start = (x, y)
            self._shape_end = (x, y)

    def _on_drag_update(self, gesture, dx, dy):
        if not self._drawing:
            return
        ok, ox, oy = gesture.get_start_point()
        if not ok:
            return
        px, py = ox + dx, oy + dy
        t = self._active_tool
        if t in ("pen", "highlighter"):
            self._current_stroke.append((px, py))
        else:
            self._shape_end = (px, py)
        self._canvas.queue_draw()

    def _on_drag_end(self, gesture, dx, dy):
        if not self._drawing:
            return
        self._drawing = False
        ann = self._build_current_annotation()
        if ann:
            self._annotations.append(ann)
            if len(self._annotations) > MAX_UNDO_HISTORY:
                self._annotations = self._annotations[-MAX_UNDO_HISTORY:]
                log.debug("Undo history capped at %d", MAX_UNDO_HISTORY)
        self._current_stroke = []
        self._shape_start = None
        self._canvas.queue_draw()

    # ━━ TOOL / COLOUR CALLBACKS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_tool_toggled(self, button: Gtk.ToggleButton, tool_id: str):
        """
        Switch the active tool.

        _toggling guards against re-entrancy: set_active(False) on the
        previously active button would otherwise re-fire this handler and
        create an infinite loop.

        Prevents zero-selection by re-activating the button when the user
        clicks an already-active tool toggle (GTK would otherwise deactivate it).
        """
        if self._toggling:
            return
        self._toggling = True
        try:
            if button.get_active():
                self._active_tool = tool_id
                for tid, btn in self._tool_buttons.items():
                    if tid != tool_id:
                        btn.set_active(False)
                self._update_width_display()
            else:
                button.set_active(True)
        finally:
            self._toggling = False

    def _on_color_clicked(self, _btn, tc):
        # Remove active marker from old selection
        if self._color.name in self._color_buttons:
            self._color_buttons[self._color.name].remove_css_class("color-active")
        self._color = tc
        # Apply active marker to new selection
        self._color_buttons[tc.name].add_css_class("color-active")

    def _adjust_width(self, delta: int):
        if self._active_tool == "highlighter":
            self._highlight_width = max(4, min(60, self._highlight_width + delta * 2))
        else:
            self._pen_width = max(1, min(20, self._pen_width + delta))
        self._update_width_display()

    def _update_width_display(self):
        if not hasattr(self, "_width_label"):
            return
        w = self._highlight_width if self._active_tool == "highlighter" else self._pen_width
        self._width_label.set_label(f" {w}px ")

    @staticmethod
    def _make_swatch_draw(rgba):
        def draw(_area, cr, w, h):
            cr.set_source_rgba(0.3, 0.3, 0.3, 0.7)
            cr.set_line_width(1)
            cr.rectangle(0.5, 0.5, w - 1, h - 1)
            cr.stroke()
            cr.set_source_rgba(*rgba)
            cr.rectangle(2, 2, w - 4, h - 4)
            cr.fill()
        return draw

    # ━━ ACTIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #
    # _undo, _new_snip, _copy_to_clipboard, _save_as_dialog

    def _undo(self):
        if self._annotations:
            self._annotations.pop()
            self._canvas.queue_draw()
            remaining = len(self._annotations)
            self._set_transient_status(
                f"Undo  ·  {remaining} annotation{'s' if remaining != 1 else ''} remaining"
            )

    def _new_snip(self):
        """
        Close the editor and start a fresh capture session.

        hold() is called before close() so GTK does not begin shutdown
        while zero windows exist. _restart_capture() releases the hold
        immediately before activate() creates the new overlay window.
        """
        log.info("New snip requested — closing editor and re-activating.")
        self._app.hold()
        self.close()
        GLib.idle_add(self._restart_capture)

    def _restart_capture(self):
        """Release the app hold and trigger a new capture (via idle_add)."""
        self._app.release()
        self._app.activate()

    def _render_to_surface(self) -> cairo.ImageSurface:
        """Render the annotated image to an off-screen cairo surface."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self._img_w, self._img_h)
        cr = cairo.Context(surface)
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()
        for ann in self._annotations:
            _render_annotation(cr, ann)
        return surface

    def _copy_to_clipboard(self):
        """
        Render the annotated image and write it to the GTK4 native clipboard.

        Uses Gdk.ContentProvider with MIME type 'image/png'. This replaces
        the previous wl-copy subprocess, which blocked the GTK main loop and
        caused the Wayland compositor to drop the connection after ~5 seconds.
        """
        try:
            surface = self._render_to_surface()

            buf = io.BytesIO()
            surface.write_to_png(buf)
            png_bytes = GLib.Bytes.new(buf.getvalue())

            provider = Gdk.ContentProvider.new_for_bytes("image/png", png_bytes)
            Gdk.Display.get_default().get_clipboard().set_content(provider)

            self._status.set_label(
                f"Copied to clipboard  ·  {self._img_w} × {self._img_h} px"
            )
            send_notification("CosmicSnip", "Screenshot copied to clipboard")
            log.info("Copied to clipboard (%dx%d)", self._img_w, self._img_h)
        except Exception as exc:
            log.exception("Copy to clipboard failed: %s", exc)
            self._status.set_label(f"Copy failed: {exc}")

    def _save_as_dialog(self):
        """Open a Save As file dialog so the user controls the save destination."""
        ts = time.strftime("%Y%m%d-%H%M%S")
        dialog = Gtk.FileDialog()
        dialog.set_title("Save Screenshot As")
        dialog.set_initial_name(f"snip-{ts}.png")
        dialog.set_initial_folder(Gio.File.new_for_path(str(SAVE_DIR)))

        filter_png = Gtk.FileFilter()
        filter_png.set_name("PNG images (*.png)")
        filter_png.add_mime_type("image/png")
        filter_png.add_pattern("*.png")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_png)
        dialog.set_filters(filters)
        dialog.set_default_filter(filter_png)

        dialog.save(self, None, self._on_save_dialog_response)

    def _on_save_dialog_response(self, dialog, result):
        """Handle the Save As dialog result."""
        try:
            file = dialog.save_finish(result)
        except GLib.GError:
            return  # user cancelled — no action needed

        if not file:
            return

        path = file.get_path()
        if not path:
            return

        # Ensure .png extension
        if not path.lower().endswith(".png"):
            path += ".png"

        try:
            surface = self._render_to_surface()
            surface.write_to_png(path)
            name = Path(path).name
            log.info("Saved via dialog: %s", path)
            self._set_transient_status(f"Saved → {name}")
            send_notification("CosmicSnip", f"Saved {name}")
        except Exception as exc:
            log.exception("Save failed: %s", exc)
            self._status.set_label(f"Save failed: {exc}")

    # ━━ STATUS HELPERS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #
    # Status messages for transient feedback (undo, save, copy). After
    # _STATUS_REVERT_MS milliseconds, the status bar reverts to showing
    # the image dimensions.

    def _set_transient_status(self, message: str):
        """Show a status message that reverts to image dimensions after a timeout."""
        # Cancel any existing revert timer
        if self._status_timer_id:
            GLib.source_remove(self._status_timer_id)
            self._status_timer_id = 0
        self._status.set_label(message)
        self._status_timer_id = GLib.timeout_add(
            _STATUS_REVERT_MS, self._revert_status
        )

    def _revert_status(self) -> bool:
        """Reset status bar to the default dimensions display."""
        self._status.set_label(f"{self._img_w} × {self._img_h} px")
        self._status_timer_id = 0
        return GLib.SOURCE_REMOVE

    # ━━ KEYBOARD ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #
    # Ctrl+C copy · Ctrl+Z undo · Ctrl+S save · Ctrl+N new snip · Escape close
    # P pen · H highlighter · A arrow · R rectangle

    def _on_key(self, _ctl, keyval, _keycode, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK

        if keyval == Gdk.KEY_Escape:
            self.close()
            return True

        if ctrl:
            if keyval in (Gdk.KEY_c, Gdk.KEY_C):
                self._copy_to_clipboard()
                return True
            if keyval in (Gdk.KEY_z, Gdk.KEY_Z):
                self._undo()
                return True
            if keyval in (Gdk.KEY_s, Gdk.KEY_S):
                self._save_as_dialog()
                return True
            if keyval in (Gdk.KEY_n, Gdk.KEY_N):
                self._new_snip()
                return True

        # Tool hotkeys (P / H / A / R)
        hotkeys = {"p": "pen", "h": "highlighter", "a": "arrow", "r": "rectangle"}
        char = chr(keyval).lower() if 32 < keyval < 127 else ""
        if char in hotkeys:
            self._tool_buttons[hotkeys[char]].set_active(True)
            return True

        return False


# ━━ ANNOTATION RENDERER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Pure stateless function — no side effects, no reference to SnipEditor.
# Called from both the live canvas draw loop and the off-screen render
# used by copy-to-clipboard and save.

def _render_annotation(cr, ann: dict) -> None:
    """Draw a single annotation onto a cairo context. Stateless."""
    atype = ann.get("type")
    color = ann.get("color", (1, 0, 0, 1))
    width = ann.get("width", 3)

    cr.set_source_rgba(*color)
    cr.set_line_width(width)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)

    if atype in ("pen", "highlighter"):
        pts = ann.get("points", [])
        if len(pts) < 2:
            return
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.stroke()

    elif atype == "arrow":
        sx, sy = ann["start"]
        ex, ey = ann["end"]
        cr.move_to(sx, sy)
        cr.line_to(ex, ey)
        cr.stroke()
        angle = math.atan2(ey - sy, ex - sx)
        head = max(14, width * DEFAULT_ARROW_HEAD_RATIO)
        ha = DEFAULT_ARROW_HEAD_ANGLE
        cr.move_to(ex, ey)
        cr.line_to(ex - head * math.cos(angle - ha), ey - head * math.sin(angle - ha))
        cr.move_to(ex, ey)
        cr.line_to(ex - head * math.cos(angle + ha), ey - head * math.sin(angle + ha))
        cr.stroke()

    elif atype == "rect":
        sx, sy = ann["start"]
        ex, ey = ann["end"]
        cr.rectangle(min(sx, ex), min(sy, ey), abs(ex - sx), abs(ey - sy))
        cr.stroke()


# ━━ HELPERS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _vsep() -> Gtk.Separator:
    """Vertical toolbar separator with standard margins."""
    sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
    sep.set_margin_start(8)
    sep.set_margin_end(8)
    return sep


# ━━ CSS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Scoped to the editor window. The .color-active class marks the currently
# selected colour swatch with a white outline ring.

_EDITOR_CSS = """
    .snip-pill {
        background: rgba(0, 0, 0, 0.75);
        color: white;
        border-radius: 10px;
        padding: 10px 22px;
        font-size: 14px;
        font-weight: 600;
    }
    .dim-label    { opacity: 0.6; font-size: 12px; }
    .monospace    { font-family: monospace; font-size: 12px; }

    /* Highlight the active color swatch with a white ring */
    button.color-active {
        outline: 2px solid white;
        outline-offset: -2px;
    }
"""
