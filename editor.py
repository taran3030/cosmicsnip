"""
Snip editor window.

Displays the cropped screenshot in a scrollable canvas and provides
annotation tools (pen, highlighter, arrow, rectangle) with undo,
copy-to-clipboard, and save.

Architecture:
  - Annotations are stored as an append-only list of dicts.
  - Each draw cycle replays the base image + all annotations.
  - Undo pops the last annotation and redraws.
  - Copy/Save renders to an off-screen cairo surface.
"""

import math
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

import cairo
from gi.repository import Gtk, Gdk, GdkPixbuf
from PIL import Image

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
from cosmicsnip.clipboard import copy_image_to_clipboard, send_notification, ClipboardError


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

        # Load image
        self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
        self._img_w = self._pixbuf.get_width()
        self._img_h = self._pixbuf.get_height()

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

        # ── State ────────────────────────────────────────────────────────
        self._annotations: list[dict] = []
        self._current_stroke: list[tuple[float, float]] = []
        self._drawing = False
        self._shape_start: tuple[float, float] | None = None
        self._shape_end: tuple[float, float] = (0, 0)

        self._active_tool = TOOLS[0].tool_id  # pen
        self._color = DEFAULT_COLOR
        self._pen_width = DEFAULT_PEN_WIDTH
        self._highlight_width = DEFAULT_HIGHLIGHT_WIDTH

        # ── Build UI ─────────────────────────────────────────────────────
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)

        root.append(self._build_headerbar())
        root.append(Gtk.Separator())
        root.append(self._build_canvas_area())
        root.append(self._build_statusbar())

        # ── CSS ──────────────────────────────────────────────────────────
        css = Gtk.CssProvider()
        css.load_from_string(self._get_css())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # ── Keyboard ────────────────────────────────────────────────────
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)

        # Auto-copy on open
        self._copy_to_clipboard()

    # ━━ UI BUILDERS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_headerbar(self) -> Gtk.Box:
        """Toolbar with tool toggles, color swatches, and action buttons."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_margin_start(10)
        bar.set_margin_end(10)
        bar.set_margin_top(8)
        bar.set_margin_bottom(8)

        # ── Tool toggles ────────────────────────────────────────────────
        tool_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        tool_box.add_css_class("linked")  # visually groups buttons

        self._tool_buttons: dict[str, Gtk.ToggleButton] = {}
        for tdef in TOOLS:
            btn = Gtk.ToggleButton()
            icon = Gtk.Image.new_from_icon_name(tdef.icon_name)
            label = Gtk.Label(label=f" {tdef.label}")
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            inner.append(icon)
            inner.append(label)
            btn.set_child(inner)
            btn.set_tooltip_text(tdef.tooltip)
            btn.connect("toggled", self._on_tool_toggled, tdef.tool_id)
            if tdef.tool_id == self._active_tool:
                btn.set_active(True)
            tool_box.append(btn)
            self._tool_buttons[tdef.tool_id] = btn

        bar.append(tool_box)

        # ── Separator ────────────────────────────────────────────────────
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep1.set_margin_start(8)
        sep1.set_margin_end(8)
        bar.append(sep1)

        # ── Color swatches ───────────────────────────────────────────────
        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for tc in PALETTE:
            btn = Gtk.Button()
            btn.set_size_request(26, 26)
            btn.set_tooltip_text(tc.label)
            swatch = Gtk.DrawingArea()
            swatch.set_content_width(18)
            swatch.set_content_height(18)
            swatch.set_draw_func(self._swatch_draw_func(tc.rgba))
            btn.set_child(swatch)
            btn.connect("clicked", self._on_color_clicked, tc)
            color_box.append(btn)
        bar.append(color_box)

        # ── Spacer ───────────────────────────────────────────────────────
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)

        # ── Width control ────────────────────────────────────────────────
        thin_btn = Gtk.Button()
        thin_btn.set_child(Gtk.Label(label="╌"))
        thin_btn.set_tooltip_text("Thinner stroke")
        thin_btn.connect("clicked", lambda _: self._adjust_width(-1))
        bar.append(thin_btn)

        self._width_label = Gtk.Label(label=f" {self._pen_width}px ")
        self._width_label.add_css_class("monospace")
        bar.append(self._width_label)

        thick_btn = Gtk.Button()
        thick_btn.set_child(Gtk.Label(label="━"))
        thick_btn.set_tooltip_text("Thicker stroke")
        thick_btn.connect("clicked", lambda _: self._adjust_width(1))
        bar.append(thick_btn)

        # ── Separator ────────────────────────────────────────────────────
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep2.set_margin_start(8)
        sep2.set_margin_end(8)
        bar.append(sep2)

        # ── Action buttons ───────────────────────────────────────────────
        undo_btn = Gtk.Button()
        undo_icon = Gtk.Image.new_from_icon_name("edit-undo-symbolic")
        undo_btn.set_child(undo_icon)
        undo_btn.set_tooltip_text("Undo (Ctrl+Z)")
        undo_btn.connect("clicked", lambda _: self._undo())
        bar.append(undo_btn)

        copy_btn = Gtk.Button()
        copy_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        copy_inner.append(Gtk.Image.new_from_icon_name("edit-copy-symbolic"))
        copy_inner.append(Gtk.Label(label="Copy"))
        copy_btn.set_child(copy_inner)
        copy_btn.set_tooltip_text("Copy to clipboard (Ctrl+C)")
        copy_btn.add_css_class("suggested-action")
        copy_btn.connect("clicked", lambda _: self._copy_to_clipboard())
        bar.append(copy_btn)

        save_btn = Gtk.Button()
        save_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        save_inner.append(Gtk.Image.new_from_icon_name("document-save-symbolic"))
        save_inner.append(Gtk.Label(label="Save"))
        save_btn.set_child(save_inner)
        save_btn.set_tooltip_text("Save as… (Ctrl+S)")
        save_btn.connect("clicked", lambda _: self._save())
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

        # Mouse input
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self._canvas.add_controller(drag)

        scroll.set_child(self._canvas)
        return scroll

    def _build_statusbar(self) -> Gtk.Box:
        """Bottom status strip."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.set_margin_start(12)
        bar.set_margin_end(12)
        bar.set_margin_top(6)
        bar.set_margin_bottom(6)

        self._status = Gtk.Label(
            label=f"{self._img_w} × {self._img_h}  ·  Copied to clipboard"
        )
        self._status.set_halign(Gtk.Align.START)
        self._status.add_css_class("dim-label")
        bar.append(self._status)

        return bar

    # ━━ CSS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _get_css() -> str:
        return """
            .snip-pill {
                background: rgba(0, 0, 0, 0.75);
                color: white;
                border-radius: 10px;
                padding: 10px 22px;
                font-size: 14px;
                font-weight: 600;
            }
            .dim-label { opacity: 0.6; font-size: 12px; }
            .monospace { font-family: monospace; font-size: 12px; }
        """

    # ━━ DRAWING ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_draw(self, _area, cr, w, h):
        """Replay base image + all annotations + in-progress stroke."""
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()

        for ann in self._annotations:
            _render_annotation(cr, ann)

        # In-progress preview
        if self._drawing:
            preview = self._build_current_annotation()
            if preview:
                _render_annotation(cr, preview)

    def _build_current_annotation(self) -> dict | None:
        """Build an annotation dict for the in-progress stroke/shape."""
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
            # Enforce undo cap
            if len(self._annotations) > MAX_UNDO_HISTORY:
                self._annotations = self._annotations[-MAX_UNDO_HISTORY:]

        self._current_stroke = []
        self._shape_start = None
        self._canvas.queue_draw()

    # ━━ TOOL CALLBACKS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_tool_toggled(self, button: Gtk.ToggleButton, tool_id: str):
        if button.get_active():
            self._active_tool = tool_id
            for tid, btn in self._tool_buttons.items():
                if tid != tool_id:
                    btn.set_active(False)
            self._update_width_display()
        elif all(not b.get_active() for b in self._tool_buttons.values()):
            button.set_active(True)  # prevent zero selection

    def _on_color_clicked(self, _btn, tc):
        self._color = tc

    def _adjust_width(self, delta: int):
        if self._active_tool == "highlighter":
            self._highlight_width = max(4, min(60, self._highlight_width + delta * 2))
        else:
            self._pen_width = max(1, min(20, self._pen_width + delta))
        self._update_width_display()

    def _update_width_display(self):
        w = self._highlight_width if self._active_tool == "highlighter" else self._pen_width
        self._width_label.set_label(f" {w}px ")

    @staticmethod
    def _swatch_draw_func(rgba):
        def draw(_area, cr, w, h):
            # Border
            cr.set_source_rgba(0.4, 0.4, 0.4, 0.6)
            cr.set_line_width(1)
            cr.rectangle(0.5, 0.5, w - 1, h - 1)
            cr.stroke()
            # Fill
            cr.set_source_rgba(*rgba)
            cr.rectangle(2, 2, w - 4, h - 4)
            cr.fill()
        return draw

    # ━━ ACTIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _undo(self):
        if self._annotations:
            self._annotations.pop()
            self._canvas.queue_draw()
            self._status.set_label("Annotation removed")

    def _render_to_surface(self) -> cairo.ImageSurface:
        """Render the annotated image to an off-screen surface."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self._img_w, self._img_h)
        cr = cairo.Context(surface)
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()
        for ann in self._annotations:
            _render_annotation(cr, ann)
        return surface

    def _save(self) -> str:
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = SAVE_DIR / f"snip-{ts}.png"
        surface = self._render_to_surface()
        surface.write_to_png(str(path))
        self._status.set_label(f"Saved → {path.name}")
        return str(path)

    def _copy_to_clipboard(self):
        path = self._save()
        try:
            copy_image_to_clipboard(path)
            self._status.set_label(f"Copied to clipboard  ·  {self._img_w} × {self._img_h}")
            send_notification("CosmicSnip", "Screenshot copied to clipboard")
        except ClipboardError as exc:
            self._status.set_label(f"Copy failed: {exc}")

    # ━━ KEYBOARD ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_key(self, _ctl, keyval, _keycode, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK

        if keyval == Gdk.KEY_Escape:
            self.close()
            return True

        # Ctrl shortcuts
        if ctrl:
            if keyval in (Gdk.KEY_c, Gdk.KEY_C):
                self._copy_to_clipboard()
                return True
            if keyval in (Gdk.KEY_z, Gdk.KEY_Z):
                self._undo()
                return True
            if keyval in (Gdk.KEY_s, Gdk.KEY_S):
                self._save()
                return True

        # Tool hotkeys
        hotkeys = {"p": "pen", "h": "highlighter", "a": "arrow", "r": "rectangle"}
        char = chr(keyval).lower() if 32 < keyval < 127 else ""
        if char in hotkeys:
            tid = hotkeys[char]
            self._tool_buttons[tid].set_active(True)
            return True

        return False


# ━━ ANNOTATION RENDERER (pure function) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _render_annotation(cr, ann: dict) -> None:
    """Draw a single annotation onto a cairo context. Stateless."""
    atype = ann["type"]
    color = ann["color"]
    width = ann["width"]

    cr.set_source_rgba(*color)
    cr.set_line_width(width)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)

    if atype in ("pen", "highlighter"):
        pts = ann["points"]
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
        # Arrowhead
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
