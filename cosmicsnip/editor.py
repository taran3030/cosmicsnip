"""Annotation editor — cropped screenshot with drawing tools.

Tools: pen, highlighter, arrow, rectangle. Supports undo, clipboard copy,
save-as, and starting a new snip. Uses libadwaita for a polished look.
"""

import io
import math
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_foreign("cairo")

import cairo
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Gio, Adw

from cosmicsnip.config import (
    SAVE_DIR, TOOLS, PALETTE, DEFAULT_COLOR,
    DEFAULT_PEN_WIDTH, DEFAULT_HIGHLIGHT_WIDTH,
    DEFAULT_ARROW_HEAD_ANGLE, DEFAULT_ARROW_HEAD_RATIO,
    MAX_UNDO_HISTORY, MAX_STROKE_POINTS,
)
from cosmicsnip.clipboard import send_notification
from cosmicsnip.log import get_logger

log = get_logger("editor")


class SnipEditor(Adw.ApplicationWindow):

    def __init__(self, app, image_path: str):
        super().__init__(application=app, title="CosmicSnip")
        self._app = app
        self._image_path = image_path

        try:
            self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
        except Exception as exc:
            log.exception("Failed to load image: %s", exc)
            raise

        self._img_w = self._pixbuf.get_width()
        self._img_h = self._pixbuf.get_height()
        log.info("Editor opened: %dx%d px  path=%s", self._img_w, self._img_h, image_path)

        # Size to 80% of largest monitor
        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        max_w, max_h = 1400, 900
        for i in range(monitors.get_n_items()):
            mon = monitors.get_item(i)
            geom = mon.get_geometry()
            cw, ch = int(geom.width * 0.8), int(geom.height * 0.8)
            if cw * ch > max_w * max_h:
                max_w, max_h = cw, ch

        self.set_default_size(
            min(self._img_w + 200, max_w),
            min(self._img_h + 300, max_h),
        )

        # Margin around image (fraction of image size) for out-of-bounds drawing.
        # Stored in image-space pixels — the canvas scales everything to fit.
        self._margin_frac = 0.25  # 25% of image dimensions
        self._margin_x = int(self._img_w * self._margin_frac)
        self._margin_y = int(self._img_h * self._margin_frac)

        # Logical canvas size in image-space coords
        self._canvas_w = self._img_w + self._margin_x * 2
        self._canvas_h = self._img_h + self._margin_y * 2

        # Scale/offset get computed on each draw to fit the widget
        self._scale = 1.0
        self._ox = 0.0
        self._oy = 0.0

        # Annotation state (all coordinates in logical canvas space)
        self._annotations: list[dict] = []
        self._current_stroke: list[tuple[float, float]] = []
        self._drawing = False
        self._shape_start: tuple[float, float] | None = None
        self._shape_end: tuple[float, float] = (0, 0)

        # Tool state
        self._active_tool = TOOLS[0].tool_id
        self._color = DEFAULT_COLOR
        self._pen_width = DEFAULT_PEN_WIDTH
        self._highlight_width = DEFAULT_HIGHLIGHT_WIDTH
        self._toggling = False
        self._auto_copied = False

        # Build UI with Adw.ToolbarView
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(self._build_headerbar())
        toolbar_view.set_content(self._build_canvas())
        toolbar_view.add_bottom_bar(self._build_statusbar())

        # Toast overlay wraps the whole thing for notifications
        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(toolbar_view)
        self.set_content(self._toast_overlay)

        # Load CSS
        css = Gtk.CssProvider()
        css.load_from_string(_EDITOR_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Keyboard
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)
        self.connect("map", self._on_first_map)
        self.connect("close-request", self._on_close_request)

    def _on_close_request(self, _w):
        """Hide editor — app stays alive in the dock for quick re-snip."""
        log.info("Editor closed — app stays in background.")
        return False  # let GTK handle the close

    def _on_first_map(self, _w):
        if not self._auto_copied:
            self._auto_copied = True
            GLib.idle_add(self._copy_to_clipboard)

    def _toast(self, message: str, timeout: int = 2):
        """Show a brief toast notification."""
        t = Adw.Toast.new(message)
        t.set_timeout(timeout)
        self._toast_overlay.add_toast(t)

    # ── Header bar ───────────────────────────────────────────────────────

    def _build_headerbar(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(
            label=f"{self._img_w} × {self._img_h}",
            css_classes=["dim-label"],
        ))

        # Tool toggles
        tool_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tool_box.add_css_class("linked")
        self._tool_buttons: dict[str, Gtk.ToggleButton] = {}

        for tdef in TOOLS:
            btn = Gtk.ToggleButton()
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            inner.append(Gtk.Image.new_from_icon_name(tdef.icon_name))
            inner.append(Gtk.Label(label=tdef.label))
            btn.set_child(inner)
            btn.set_tooltip_text(tdef.tooltip)
            if tdef.tool_id == self._active_tool:
                btn.set_active(True)
            tool_box.append(btn)
            self._tool_buttons[tdef.tool_id] = btn
        # Connect signals after all widgets exist to avoid early callbacks
        for tdef in TOOLS:
            self._tool_buttons[tdef.tool_id].connect(
                "toggled", self._on_tool_toggled, tdef.tool_id)
        header.pack_start(tool_box)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_margin_start(6)
        sep.set_margin_end(6)
        header.pack_start(sep)

        # Color swatches
        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        self._color_buttons: dict[str, Gtk.Button] = {}

        for tc in PALETTE:
            btn = Gtk.Button()
            btn.set_size_request(26, 26)
            btn.set_tooltip_text(tc.label)
            btn.add_css_class("color-swatch")
            swatch = Gtk.DrawingArea()
            swatch.set_content_width(16)
            swatch.set_content_height(16)
            swatch.set_draw_func(self._make_swatch_draw(tc.rgba))
            btn.set_child(swatch)
            btn.connect("clicked", self._on_color_clicked, tc)
            color_box.append(btn)
            self._color_buttons[tc.name] = btn

        self._color_buttons[self._color.name].add_css_class("color-active")
        header.pack_start(color_box)

        # Separator
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep2.set_margin_start(6)
        sep2.set_margin_end(6)
        header.pack_start(sep2)

        # Stroke width
        width_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        width_box.add_css_class("linked")
        thin_btn = Gtk.Button(child=Gtk.Label(label="╌"))
        thin_btn.set_tooltip_text("Thinner")
        thin_btn.connect("clicked", lambda _: self._adjust_width(-1))
        width_box.append(thin_btn)
        self._width_label = Gtk.Label(label=f"{self._pen_width}px")
        self._width_label.set_size_request(36, -1)
        self._width_label.add_css_class("monospace")
        width_box.append(self._width_label)
        thick_btn = Gtk.Button(child=Gtk.Label(label="━"))
        thick_btn.set_tooltip_text("Thicker")
        thick_btn.connect("clicked", lambda _: self._adjust_width(1))
        width_box.append(thick_btn)
        header.pack_start(width_box)

        # Right side (pack_end adds right-to-left)
        save_btn = Gtk.Button(icon_name="document-save-symbolic")
        save_btn.set_tooltip_text("Save (Ctrl+S)")
        save_btn.connect("clicked", lambda _: self._save_as_dialog())
        header.pack_end(save_btn)

        copy_btn = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_btn.set_tooltip_text("Copy (Ctrl+C)")
        copy_btn.add_css_class("suggested-action")
        copy_btn.connect("clicked", lambda _: self._copy_to_clipboard())
        header.pack_end(copy_btn)

        new_btn = Gtk.Button(icon_name="camera-photo-symbolic")
        new_btn.set_tooltip_text("New snip (Ctrl+N)")
        new_btn.connect("clicked", lambda _: self._new_snip())
        header.pack_end(new_btn)

        undo_btn = Gtk.Button(icon_name="edit-undo-symbolic")
        undo_btn.set_tooltip_text("Undo (Ctrl+Z)")
        undo_btn.connect("clicked", lambda _: self._undo())
        header.pack_end(undo_btn)

        return header

    # ── Canvas ───────────────────────────────────────────────────────────

    def _build_canvas(self) -> Gtk.DrawingArea:
        self._canvas = Gtk.DrawingArea()
        self._canvas.set_hexpand(True)
        self._canvas.set_vexpand(True)
        self._canvas.set_draw_func(self._on_draw)
        self._canvas.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self._canvas.add_controller(drag)

        return self._canvas

    def _build_statusbar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.set_margin_start(12)
        bar.set_margin_end(12)
        bar.set_margin_top(4)
        bar.set_margin_bottom(4)
        self._status = Gtk.Label(label=f"{self._img_w} × {self._img_h} px")
        self._status.set_halign(Gtk.Align.START)
        self._status.add_css_class("dim-label")
        bar.append(self._status)
        return bar

    # ── Drawing ──────────────────────────────────────────────────────────

    def _widget_to_canvas(self, wx: float, wy: float) -> tuple[float, float]:
        """Convert widget pixel coords to logical canvas coords."""
        return ((wx - self._ox) / self._scale,
                (wy - self._oy) / self._scale)

    def _on_draw(self, _area, cr, w, h):
        mx, my = self._margin_x, self._margin_y

        # Compute scale so the full canvas fits in the widget
        sx = w / self._canvas_w if self._canvas_w else 1
        sy = h / self._canvas_h if self._canvas_h else 1
        self._scale = min(sx, sy)
        # Center the scaled canvas in the widget
        scaled_w = self._canvas_w * self._scale
        scaled_h = self._canvas_h * self._scale
        self._ox = (w - scaled_w) / 2
        self._oy = (h - scaled_h) / 2

        # Dark background outside the canvas
        cr.set_source_rgba(0.12, 0.12, 0.12, 1.0)
        cr.paint()

        # Apply transform: translate to center, then scale
        cr.save()
        cr.translate(self._ox, self._oy)
        cr.scale(self._scale, self._scale)

        # Canvas background
        cr.set_source_rgba(0.18, 0.18, 0.18, 1.0)
        cr.rectangle(0, 0, self._canvas_w, self._canvas_h)
        cr.fill()

        # Image area (slightly lighter to distinguish from margin)
        cr.set_source_rgba(0.22, 0.22, 0.22, 1.0)
        cr.rectangle(mx, my, self._img_w, self._img_h)
        cr.fill()

        # Draw image at (margin_x, margin_y) in canvas coords
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, mx, my)
        cr.paint()

        # Thin border around the image
        cr.set_source_rgba(0.4, 0.4, 0.4, 0.5)
        cr.set_line_width(1.0 / self._scale)  # 1px regardless of zoom
        cr.rectangle(mx - 0.5, my - 0.5, self._img_w + 1, self._img_h + 1)
        cr.stroke()

        # Annotations (stored in canvas coords)
        for ann in self._annotations:
            _render_annotation(cr, ann)
        if self._drawing:
            preview = self._build_preview()
            if preview:
                _render_annotation(cr, preview)

        cr.restore()

    def _build_preview(self) -> dict | None:
        t = self._active_tool
        color = self._color.rgba
        if t == "pen" and len(self._current_stroke) > 1:
            return {"type": "pen", "points": list(self._current_stroke),
                    "color": color, "width": self._pen_width}
        if t == "highlighter" and len(self._current_stroke) > 1:
            return {"type": "highlighter", "points": list(self._current_stroke),
                    "color": (color[0], color[1], color[2], 0.35),
                    "width": self._highlight_width}
        if t == "arrow" and self._shape_start:
            return {"type": "arrow", "start": self._shape_start,
                    "end": self._shape_end, "color": color, "width": self._pen_width}
        if t == "rectangle" and self._shape_start:
            return {"type": "rect", "start": self._shape_start,
                    "end": self._shape_end, "color": color, "width": self._pen_width}
        return None

    # ── Input ────────────────────────────────────────────────────────────

    def _on_drag_begin(self, gesture, x, y):
        cx, cy = self._widget_to_canvas(x, y)
        self._drawing = True
        if self._active_tool in ("pen", "highlighter"):
            self._current_stroke = [(cx, cy)]
        else:
            self._shape_start = (cx, cy)
            self._shape_end = (cx, cy)

    def _on_drag_update(self, gesture, dx, dy):
        if not self._drawing:
            return
        ok, ox, oy = gesture.get_start_point()
        if not ok:
            return
        cx, cy = self._widget_to_canvas(ox + dx, oy + dy)
        if self._active_tool in ("pen", "highlighter"):
            if len(self._current_stroke) < MAX_STROKE_POINTS:
                self._current_stroke.append((cx, cy))
        else:
            self._shape_end = (cx, cy)
        self._canvas.queue_draw()

    def _on_drag_end(self, gesture, dx, dy):
        if not self._drawing:
            return
        self._drawing = False
        ann = self._build_preview()
        if ann:
            self._annotations.append(ann)
            if len(self._annotations) > MAX_UNDO_HISTORY:
                self._annotations = self._annotations[-MAX_UNDO_HISTORY:]
        self._current_stroke = []
        self._shape_start = None
        self._canvas.queue_draw()

    # ── Tool / color callbacks ───────────────────────────────────────────

    def _on_tool_toggled(self, button, tool_id):
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
        if self._color.name in self._color_buttons:
            self._color_buttons[self._color.name].remove_css_class("color-active")
        self._color = tc
        self._color_buttons[tc.name].add_css_class("color-active")

    def _adjust_width(self, delta):
        if self._active_tool == "highlighter":
            self._highlight_width = max(4, min(60, self._highlight_width + delta * 2))
        else:
            self._pen_width = max(1, min(20, self._pen_width + delta))
        self._update_width_display()

    def _update_width_display(self):
        w = self._highlight_width if self._active_tool == "highlighter" else self._pen_width
        self._width_label.set_label(f"{w}px")

    @staticmethod
    def _make_swatch_draw(rgba):
        def draw(_area, cr, w, h):
            # Rounded swatch with border
            radius = min(w, h) / 2
            cr.arc(w / 2, h / 2, radius - 1, 0, 2 * math.pi)
            cr.set_source_rgba(*rgba)
            cr.fill_preserve()
            cr.set_source_rgba(0.4, 0.4, 0.4, 0.5)
            cr.set_line_width(1)
            cr.stroke()
        return draw

    # ── Actions ──────────────────────────────────────────────────────────

    def _undo(self):
        if self._annotations:
            self._annotations.pop()
            self._canvas.queue_draw()
            n = len(self._annotations)
            self._toast(f"Undo — {n} annotation{'s' if n != 1 else ''} left")

    def _new_snip(self):
        """Hide editor (keep surface alive), start fresh capture."""
        log.info("New snip requested.")
        self._app.hold()
        self.set_visible(False)
        GLib.idle_add(self._restart_capture)

    def _restart_capture(self):
        self._app.activate()
        GLib.timeout_add(500, self._deferred_close)

    def _deferred_close(self):
        self._app.release()
        self.close()
        return GLib.SOURCE_REMOVE

    def _annotation_bounds(self) -> tuple[int, int, int, int]:
        """Bounding box of image + annotations in canvas coords. Returns (x1,y1,x2,y2)."""
        mx, my = self._margin_x, self._margin_y

        if not self._annotations:
            return (mx, my, mx + self._img_w, my + self._img_h)

        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')

        for ann in self._annotations:
            w = ann.get("width", 3)
            pad = w / 2 + 2
            atype = ann.get("type")

            if atype in ("pen", "highlighter"):
                for px, py in ann.get("points", []):
                    min_x = min(min_x, px - pad)
                    min_y = min(min_y, py - pad)
                    max_x = max(max_x, px + pad)
                    max_y = max(max_y, py + pad)
            elif atype == "arrow":
                for pt in (ann["start"], ann["end"]):
                    min_x = min(min_x, pt[0] - pad - 20)
                    min_y = min(min_y, pt[1] - pad - 20)
                    max_x = max(max_x, pt[0] + pad + 20)
                    max_y = max(max_y, pt[1] + pad + 20)
            elif atype == "rect":
                for pt in (ann["start"], ann["end"]):
                    min_x = min(min_x, pt[0] - pad)
                    min_y = min(min_y, pt[1] - pad)
                    max_x = max(max_x, pt[0] + pad)
                    max_y = max(max_y, pt[1] + pad)

        # Union with image bounds
        min_x = min(min_x, mx)
        min_y = min(min_y, my)
        max_x = max(max_x, mx + self._img_w)
        max_y = max(max_y, my + self._img_h)

        # Clamp to canvas
        min_x = max(0, int(min_x))
        min_y = max(0, int(min_y))
        max_x = min(self._canvas_w, int(math.ceil(max_x)))
        max_y = min(self._canvas_h, int(math.ceil(max_y)))

        return (min_x, min_y, max_x, max_y)

    def _render_to_surface(self) -> cairo.ImageSurface:
        """Render image + annotations, trimmed to content bounds. Transparent PNG."""
        bx1, by1, bx2, by2 = self._annotation_bounds()
        out_w, out_h = bx2 - bx1, by2 - by1

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, out_w, out_h)
        cr = cairo.Context(surface)
        # Shift so content starts at (0,0)
        cr.translate(-bx1, -by1)
        # Draw image at its canvas position — transparent outside
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, self._margin_x, self._margin_y)
        cr.paint()
        for ann in self._annotations:
            _render_annotation(cr, ann)
        return surface

    def _copy_to_clipboard(self):
        try:
            surface = self._render_to_surface()
            sw, sh = surface.get_width(), surface.get_height()
            buf = io.BytesIO()
            surface.write_to_png(buf)
            png_bytes = GLib.Bytes.new(buf.getvalue())
            provider = Gdk.ContentProvider.new_for_bytes("image/png", png_bytes)
            Gdk.Display.get_default().get_clipboard().set_content(provider)
            self._toast("Copied to clipboard")
            log.info("Copied to clipboard: %dx%d", sw, sh)
        except Exception as exc:
            log.exception("Copy failed: %s", exc)
            self._toast(f"Copy failed: {exc}")

    def _save_as_dialog(self):
        ts = time.strftime("%Y%m%d-%H%M%S")
        dialog = Gtk.FileDialog()
        dialog.set_title("Save Screenshot As")
        dialog.set_initial_name(f"snip-{ts}.png")
        dialog.set_initial_folder(Gio.File.new_for_path(str(SAVE_DIR)))

        f = Gtk.FileFilter()
        f.set_name("PNG images (*.png)")
        f.add_mime_type("image/png")
        f.add_pattern("*.png")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)
        dialog.set_default_filter(f)
        dialog.save(self, None, self._on_save_response)

    def _on_save_response(self, dialog, result):
        try:
            file = dialog.save_finish(result)
        except GLib.GError:
            return
        if not file:
            return
        path = file.get_path()
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"

        resolved = Path(path).resolve()
        blocked = ("/etc", "/usr", "/bin", "/sbin", "/boot",
                   "/proc", "/sys", "/dev", "/var/run", "/run",
                   "/lib", "/lib64", "/root")
        for prefix in blocked:
            if str(resolved).startswith(prefix + "/") or str(resolved) == prefix:
                log.warning("Save blocked — sensitive path: %s", resolved)
                self._toast("Cannot save to system directories")
                return

        try:
            surface = self._render_to_surface()
            surface.write_to_png(path)
            name = Path(path).name
            log.info("Saved: %s", path)
            self._toast(f"Saved → {name}")
            send_notification("CosmicSnip", f"Saved {name}")
        except Exception as exc:
            log.exception("Save failed: %s", exc)
            self._toast(f"Save failed: {exc}")

    # ── Keyboard shortcuts ───────────────────────────────────────────────

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
            if keyval in (Gdk.KEY_q, Gdk.KEY_Q):
                self._app.quit()
                return True
        hotkeys = {"p": "pen", "h": "highlighter", "a": "arrow", "r": "rectangle"}
        char = chr(keyval).lower() if 32 < keyval < 127 else ""
        if char in hotkeys:
            self._tool_buttons[hotkeys[char]].set_active(True)
            return True
        return False


# ── Annotation renderer ──────────────────────────────────────────────────────

def _render_annotation(cr, ann: dict) -> None:
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


# ── CSS ──────────────────────────────────────────────────────────────────────

_EDITOR_CSS = """
.dim-label {
    opacity: 0.5;
    font-size: 12px;
}
.monospace {
    font-family: monospace;
    font-size: 11px;
}

button.color-swatch {
    border-radius: 50%;
    min-width: 26px;
    min-height: 26px;
    padding: 2px;
    border: 2px solid transparent;
    background: none;
    box-shadow: none;
}
button.color-swatch:hover {
    border-color: alpha(white, 0.3);
}
button.color-active {
    border-color: alpha(white, 0.7);
    box-shadow: 0 0 0 1px alpha(white, 0.3);
}
"""
