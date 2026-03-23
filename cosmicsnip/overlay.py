"""Multi-monitor selection overlay using layer-shell.

One fullscreen overlay per monitor, each showing its portion of the combined
screenshot at native resolution. Selection state is shared so a drag can
span monitors. Esc or right-click cancels.

If gtk4-layer-shell isn't available, falls back to a single scaled window.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_foreign("cairo")

import cairo
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
from typing import Callable

from cosmicsnip.log import get_logger
from cosmicsnip.monitors import MonitorInfo, get_gdk_monitor
from cosmicsnip.config import (
    OVERLAY_DIM_ALPHA, SELECTION_BORDER_COLOR,
    SELECTION_BORDER_WIDTH, MIN_SELECTION_SIZE,
)

log = get_logger("overlay")
SIZE_LABEL_FONT_SIZE = 12
SIZE_LABEL_Y_OFFSET = 8
SIZE_LABEL_BOTTOM_MARGIN = 28
SIZE_LABEL_PADDING_X = 8
SIZE_LABEL_BOX_HEIGHT = 24
SIZE_LABEL_BASELINE = 17
FALLBACK_MAP_RETRY_MS = 50

# ── Layer-shell setup ────────────────────────────────────────────────────────

_layer_shell_checked = False
_LAYER_SHELL_AVAILABLE = False
LayerShell = None
_LS = None

try:
    gi.require_version('Gtk4LayerShell', '1.0')
    from gi.repository import Gtk4LayerShell as _LS
    log.info("gtk4-layer-shell GIR bindings loaded.")
except (OSError, ValueError, ImportError) as exc:
    log.warning("gtk4-layer-shell not available: %s", exc)


def _check_layer_shell():
    """Lazy init — must run after GTK display is connected."""
    global _layer_shell_checked, _LAYER_SHELL_AVAILABLE, LayerShell
    if _layer_shell_checked:
        return
    _layer_shell_checked = True
    if _LS is None:
        return
    try:
        supported = _LS.is_supported()
        log.info("gtk4-layer-shell is_supported() = %s", supported)
        if supported:
            LayerShell = _LS
            _LAYER_SHELL_AVAILABLE = True
            log.info("gtk4-layer-shell ready (protocol v%d).", _LS.get_protocol_version())
        else:
            # COSMIC may report False but still work
            log.warning("gtk4-layer-shell reports unsupported, proceeding (expected on COSMIC).")
            LayerShell = _LS
            _LAYER_SHELL_AVAILABLE = True
    except Exception as exc:
        log.warning("Layer-shell check failed: %s", exc)


def layer_shell_available() -> bool:
    _check_layer_shell()
    return _LAYER_SHELL_AVAILABLE


# ── Shared selection state ───────────────────────────────────────────────────

class SelectionState:
    """Mutable rectangle in combined-image coordinates."""

    def __init__(self):
        self.dragging = False
        self.has_selection = False
        self.sx = self.sy = self.ex = self.ey = 0

    def begin(self, x: int, y: int):
        self.dragging = True
        self.has_selection = True
        self.sx = self.ex = x
        self.sy = self.ey = y

    def update(self, x: int, y: int):
        if self.dragging:
            self.ex, self.ey = x, y

    def finish(self):
        self.dragging = False

    def rect(self) -> tuple[int, int, int, int]:
        return (min(self.sx, self.ex), min(self.sy, self.ey),
                max(self.sx, self.ex), max(self.sy, self.ey))

    def size_ok(self) -> bool:
        x1, y1, x2, y2 = self.rect()
        return (x2 - x1) >= MIN_SELECTION_SIZE and (y2 - y1) >= MIN_SELECTION_SIZE


# ── Per-monitor overlay window ───────────────────────────────────────────────

class MonitorOverlay(Gtk.Window):
    """Layer-shell window covering a single monitor for region selection."""

    def __init__(self, app, monitor_info, pixbuf, state, controller,
                 origin_x=0, origin_y=0):
        super().__init__(application=app)
        self._info = monitor_info
        self._state = state
        self._controller = controller
        self._is_hidden = False
        self._px = 0
        self._py = 0
        self._local_pixbuf = None
        self._local_w = 1
        self._local_h = 1
        self._load_local_pixbuf(pixbuf, monitor_info, origin_x, origin_y)

        self.set_decorated(False)
        gdk_mon = get_gdk_monitor(monitor_info.gdk_index)

        # Attach to layer-shell overlay layer
        if _LAYER_SHELL_AVAILABLE and LayerShell is not None:
            try:
                LayerShell.init_for_window(self)
                LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
                LayerShell.set_namespace(self, "cosmicsnip-overlay")
                LayerShell.set_exclusive_zone(self, 0)
                for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM,
                             LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
                    LayerShell.set_anchor(self, edge, True)
                LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.EXCLUSIVE)
                if gdk_mon:
                    LayerShell.set_monitor(self, gdk_mon)
                log.info("MonitorOverlay[%s]: layer-shell attached.", monitor_info.name)
            except Exception as exc:
                log.warning("Layer-shell failed for %s: %s", monitor_info.name, exc)
                if gdk_mon:
                    self.fullscreen_on_monitor(gdk_mon)
                else:
                    self.fullscreen()
        elif gdk_mon:
            self.fullscreen_on_monitor(gdk_mon)
        else:
            self.fullscreen()

        self.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))

        # Widget tree
        root = Gtk.Overlay()
        self._canvas = Gtk.DrawingArea()
        self._canvas.set_hexpand(True)
        self._canvas.set_vexpand(True)
        self._canvas.set_draw_func(self._draw)
        root.set_child(self._canvas)

        # Hint pill on primary monitor
        if monitor_info.gdk_index == controller.primary_index:
            pill = Gtk.Label(label="  Drag to select  ·  Esc to cancel  ")
            pill.set_halign(Gtk.Align.CENTER)
            pill.set_valign(Gtk.Align.START)
            pill.set_margin_top(24)
            pill.add_css_class("snip-pill")
            root.add_overlay(pill)

        self.set_child(root)

        # Input: left-click to select, right-click to cancel
        click = Gtk.GestureClick(button=1)
        click.connect("pressed", self._on_press)
        click.connect("released", self._on_release)
        self._canvas.add_controller(click)

        rclick = Gtk.GestureClick(button=3)
        rclick.connect("pressed", lambda *_: self._controller.cancel())
        self._canvas.add_controller(rclick)

        drag = Gtk.GestureDrag()
        drag.connect("drag-update", self._on_drag_update)
        self._canvas.add_controller(drag)

        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)

    def _load_local_pixbuf(self, pixbuf, monitor_info, origin_x, origin_y):
        """Load and cache a GdkPixbuf from the capture file for this monitor's region."""
        self._info = monitor_info
        self._px = monitor_info.x - origin_x
        self._py = monitor_info.y - origin_y

        img_w, img_h = pixbuf.get_width(), pixbuf.get_height()
        cx = max(0, min(self._px, img_w))
        cy = max(0, min(self._py, img_h))
        cw = min(monitor_info.width, img_w - cx)
        ch = min(monitor_info.height, img_h - cy)

        if cw > 0 and ch > 0:
            self._local_pixbuf = pixbuf.new_subpixbuf(cx, cy, cw, ch)
        else:
            self._local_pixbuf = GdkPixbuf.Pixbuf.new(
                GdkPixbuf.Colorspace.RGB, False, 8,
                monitor_info.width, monitor_info.height)
            self._local_pixbuf.fill(0x000000FF)

        self._local_w = self._local_pixbuf.get_width()
        self._local_h = self._local_pixbuf.get_height()

    # ── Coordinate mapping ───────────────────────────────────────────────

    def _canvas_to_image(self, cx, cy):
        """Convert canvas-local pixel coordinates to full-image coordinates."""
        return (int(max(0, min(cx, self._local_w - 1))) + self._px,
                int(max(0, min(cy, self._local_h - 1))) + self._py)

    def _image_to_canvas(self, ix, iy):
        """Convert full-image coordinates to canvas-local pixel coordinates."""
        return float(ix - self._px), float(iy - self._py)

    # ── Drawing ──────────────────────────────────────────────────────────

    def _draw(self, _area, cr, w, h):
        """Cairo draw handler: renders capture image, dim overlay, and selection rectangle."""
        if self._is_hidden:
            cr.set_source_rgba(0, 0, 0, 0)
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.paint()
            return
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        Gdk.cairo_set_source_pixbuf(cr, self._local_pixbuf, 0, 0)
        cr.paint()
        cr.set_source_rgba(0, 0, 0, OVERLAY_DIM_ALPHA)
        cr.rectangle(0, 0, self._local_w, self._local_h)
        cr.fill()

        if not self._state.has_selection:
            return

        x1, y1, x2, y2 = self._state.rect()
        lx1, ly1 = self._image_to_canvas(x1, y1)
        lx2, ly2 = self._image_to_canvas(x2, y2)
        lx1 = max(0, min(lx1, self._local_w))
        ly1 = max(0, min(ly1, self._local_h))
        lx2 = max(0, min(lx2, self._local_w))
        ly2 = max(0, min(ly2, self._local_h))
        sw, sh = lx2 - lx1, ly2 - ly1
        if sw < 1 or sh < 1:
            return

        cr.save()
        cr.rectangle(lx1, ly1, sw, sh)
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, self._local_pixbuf, 0, 0)
        cr.paint()
        cr.restore()

        r, g, b, a = SELECTION_BORDER_COLOR
        cr.set_source_rgba(r, g, b, a)
        cr.set_line_width(SELECTION_BORDER_WIDTH)
        cr.rectangle(lx1, ly1, sw, sh)
        cr.stroke()

        end_here = (self._px <= self._state.ex < self._px + self._info.width and
                    self._py <= self._state.ey < self._py + self._info.height)
        if end_here:
            dim = f"{x2 - x1} × {y2 - y1}"
            # Match the editor/status typography for quick visual parsing.
            cr.set_font_size(SIZE_LABEL_FONT_SIZE)
            ext = cr.text_extents(dim)
            # Keep badge adjacent to selection while preventing bottom clipping.
            bx, by = lx1, min(ly2 + SIZE_LABEL_Y_OFFSET, h - SIZE_LABEL_BOTTOM_MARGIN)
            cr.set_source_rgba(0, 0, 0, 0.8)
            cr.rectangle(bx, by, ext.width + (SIZE_LABEL_PADDING_X * 2), SIZE_LABEL_BOX_HEIGHT)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 1)
            cr.move_to(bx + SIZE_LABEL_PADDING_X, by + SIZE_LABEL_BASELINE)
            cr.show_text(dim)

    # ── Input handlers ───────────────────────────────────────────────────

    def _on_press(self, _g, _n, x, y):
        self._state.begin(*self._canvas_to_image(x, y))
        self._controller.redraw_all()

    def _on_drag_update(self, gesture, dx, dy):
        if not self._state.dragging:
            return
        ok, ox, oy = gesture.get_start_point()
        if ok:
            self._state.update(*self._canvas_to_image(ox + dx, oy + dy))
            self._controller.redraw_all()

    def _on_release(self, _g, _n, x, y):
        if not self._state.dragging:
            return
        self._state.update(*self._canvas_to_image(x, y))
        self._state.finish()
        # Immediate redraw on release (bypass coalescing)
        for ov in self._controller.active_overlays():
            ov._canvas.queue_draw()
        if self._state.size_ok():
            self._controller.finalise()

    def _on_key(self, _ctl, keyval, _kc, _st):
        if keyval == Gdk.KEY_Escape:
            self._controller.cancel()
            return True
        return False


# ── Overlay controller ───────────────────────────────────────────────────────

class OverlayController:
    """Manages per-monitor overlays with shared selection state."""

    def __init__(self, app, image_path, monitors, on_selected, on_cancelled):
        self._app = app
        self._image_path = image_path
        self._on_selected = on_selected
        self._on_cancelled = on_cancelled
        self._state = SelectionState()
        self._redraw_pending = False
        self._overlays: list[MonitorOverlay] = []
        self.primary_index = monitors[0].gdk_index if monitors else 0

        # Normalize monitor origins so top-left of combined layout is (0,0).
        # Screenshot pixels start at (0,0) regardless of compositor coords.
        self._origin_x = min(m.x for m in monitors)
        self._origin_y = min(m.y for m in monitors)

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
        log.info("Combined image: %dx%d px  layout origin=(%d,%d)",
                 pixbuf.get_width(), pixbuf.get_height(),
                 self._origin_x, self._origin_y)

        for mon in monitors:
            self._overlays.append(
                MonitorOverlay(app=app, monitor_info=mon, pixbuf=pixbuf,
                               origin_x=self._origin_x, origin_y=self._origin_y,
                               state=self._state, controller=self))

    def active_overlays(self):
        return self._overlays

    def present(self):
        for ov in self._overlays:
            ov.present()

    def redraw_all(self):
        """Coalesce redraws to max ~60fps. Updates state immediately, defers paint."""
        if self._redraw_pending:
            return  # a frame callback is already queued
        self._redraw_pending = True

        def _do_redraw():
            self._redraw_pending = False
            for ov in self.active_overlays():
                ov._canvas.queue_draw()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(16, _do_redraw)  # ~60fps

    def _release_keyboard(self):
        """Release exclusive keyboard grab."""
        for ov in self.active_overlays():
            if _LAYER_SHELL_AVAILABLE and LayerShell is not None:
                try:
                    LayerShell.set_keyboard_mode(ov, LayerShell.KeyboardMode.NONE)
                except Exception as exc:
                    log.debug("Layer-shell keyboard release failed: %s", exc)

    def hide_all(self):
        """Dismiss overlay windows — mark hidden, repaint transparent, drop layer."""
        self._release_keyboard()
        self._redraw_pending = False
        for ov in self._overlays:
            ov._is_hidden = True
            ov._canvas.queue_draw()
            if _LAYER_SHELL_AVAILABLE and LayerShell is not None:
                try:
                    LayerShell.set_layer(ov, LayerShell.Layer.BACKGROUND)
                except Exception as exc:
                    log.debug("Layer-shell hide transition failed: %s", exc)
            ov.set_opacity(0)
        log.info("Overlays dismissed.")

    def finalise(self):
        x1, y1, x2, y2 = self._state.rect()
        log.info("Selection finalised: (%d,%d)→(%d,%d) %dx%d",
                 x1, y1, x2, y2, x2 - x1, y2 - y1)
        self.hide_all()
        self._on_selected(self._image_path, x1, y1, x2, y2)

    def cancel(self):
        self._release_keyboard()
        self.hide_all()
        self._on_cancelled()


# ── Fallback single-window overlay ───────────────────────────────────────────

class FallbackOverlay(Gtk.Window):
    """Scales the combined screenshot to fit one screen. Used without layer-shell."""

    def __init__(self, app, image_path, on_selected, on_cancelled):
        super().__init__(application=app)
        self._image_path = image_path
        self._on_selected = on_selected
        self._on_cancelled = on_cancelled
        self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
        self._img_w = self._pixbuf.get_width()
        self._img_h = self._pixbuf.get_height()
        self._display_pixbuf = None
        self._disp_x = self._disp_y = 0
        self._disp_w, self._disp_h = self._img_w, self._img_h
        self._disp_scale = 1.0
        self._dragging = False
        self._sx = self._sy = self._ex = self._ey = 0.0
        self._has_selection = False

        self.set_decorated(False)
        self.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))
        self.fullscreen()

        root = Gtk.Overlay()
        self._canvas = Gtk.DrawingArea()
        self._canvas.set_hexpand(True)
        self._canvas.set_vexpand(True)
        self._canvas.set_draw_func(self._draw)
        root.set_child(self._canvas)

        pill = Gtk.Label(label="  Drag to select  ·  Esc to cancel  ")
        pill.set_halign(Gtk.Align.CENTER)
        pill.set_valign(Gtk.Align.START)
        pill.set_margin_top(24)
        pill.add_css_class("snip-pill")
        root.add_overlay(pill)
        self.set_child(root)

        click = Gtk.GestureClick(button=1)
        click.connect("pressed", self._on_press)
        click.connect("released", self._on_release)
        self._canvas.add_controller(click)

        rclick = Gtk.GestureClick(button=3)
        rclick.connect("pressed", lambda *_: self._cancel())
        self._canvas.add_controller(rclick)

        drag = Gtk.GestureDrag()
        drag.connect("drag-update", self._on_drag_update)
        self._canvas.add_controller(drag)

        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)
        self.connect("map", lambda _w: GLib.idle_add(self._build_display_cache))

    def _build_display_cache(self):
        alloc = self._canvas.get_allocation()
        cw, ch = alloc.width, alloc.height
        if cw <= 0 or ch <= 0:
            # Allow the layer-shell window one extra compositor frame to map.
            GLib.timeout_add(FALLBACK_MAP_RETRY_MS, self._build_display_cache)
            return GLib.SOURCE_REMOVE
        scale = min(cw / self._img_w, ch / self._img_h)
        dw, dh = int(self._img_w * scale), int(self._img_h * scale)
        self._disp_x, self._disp_y = (cw - dw) // 2, (ch - dh) // 2
        self._disp_w, self._disp_h, self._disp_scale = dw, dh, scale
        try:
            self._display_pixbuf = self._pixbuf.scale_simple(dw, dh, GdkPixbuf.InterpType.BILINEAR)
        except Exception:
            self._display_pixbuf = self._pixbuf
        self._canvas.queue_draw()
        return GLib.SOURCE_REMOVE

    def _draw(self, _a, cr, w, h):
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        if not self._display_pixbuf:
            return
        Gdk.cairo_set_source_pixbuf(cr, self._display_pixbuf, self._disp_x, self._disp_y)
        cr.paint()
        cr.set_source_rgba(0, 0, 0, OVERLAY_DIM_ALPHA)
        cr.rectangle(self._disp_x, self._disp_y, self._disp_w, self._disp_h)
        cr.fill()
        if not self._has_selection:
            return
        x1, y1, x2, y2 = self._clamped()
        sw, sh = x2 - x1, y2 - y1
        if sw < 2 or sh < 2:
            return
        cr.save()
        cr.rectangle(x1, y1, sw, sh)
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, self._display_pixbuf, self._disp_x, self._disp_y)
        cr.paint()
        cr.restore()
        r, g, b, a = SELECTION_BORDER_COLOR
        cr.set_source_rgba(r, g, b, a)
        cr.set_line_width(SELECTION_BORDER_WIDTH)
        cr.rectangle(x1, y1, sw, sh)
        cr.stroke()

    def _clamped(self):
        return (max(self._disp_x, min(self._sx, self._ex)),
                max(self._disp_y, min(self._sy, self._ey)),
                min(self._disp_x + self._disp_w, max(self._sx, self._ex)),
                min(self._disp_y + self._disp_h, max(self._sy, self._ey)))

    def _on_press(self, _g, _n, x, y):
        x = max(self._disp_x, min(x, self._disp_x + self._disp_w))
        y = max(self._disp_y, min(y, self._disp_y + self._disp_h))
        self._dragging = True
        self._sx = self._ex = x
        self._sy = self._ey = y
        self._has_selection = True

    def _on_drag_update(self, gesture, dx, dy):
        if not self._dragging:
            return
        ok, ox, oy = gesture.get_start_point()
        if ok:
            self._ex = max(self._disp_x, min(ox + dx, self._disp_x + self._disp_w))
            self._ey = max(self._disp_y, min(oy + dy, self._disp_y + self._disp_h))
            self._canvas.queue_draw()

    def _on_release(self, _g, _n, x, y):
        self._dragging = False
        self._ex = max(self._disp_x, min(x, self._disp_x + self._disp_w))
        self._ey = max(self._disp_y, min(y, self._disp_y + self._disp_h))
        self._canvas.queue_draw()
        x1, y1, x2, y2 = self._clamped()
        if (x2 - x1) >= MIN_SELECTION_SIZE and (y2 - y1) >= MIN_SELECTION_SIZE:
            s = self._disp_scale
            ix1 = max(0, min(int((x1 - self._disp_x) / s), self._img_w))
            iy1 = max(0, min(int((y1 - self._disp_y) / s), self._img_h))
            ix2 = max(0, min(int((x2 - self._disp_x) / s), self._img_w))
            iy2 = max(0, min(int((y2 - self._disp_y) / s), self._img_h))
            self.close()
            self._on_selected(self._image_path, ix1, iy1, ix2, iy2)

    def hide_all(self):
        """Match OverlayController's API."""
        self._display_pixbuf = None
        self._canvas.queue_draw()
        self.set_opacity(0)

    def _cancel(self):
        self.hide_all()
        self._on_cancelled()

    def _on_key(self, _ctl, keyval, _kc, _st):
        if keyval == Gdk.KEY_Escape:
            self._cancel()
            return True
        return False


# ── Public API ───────────────────────────────────────────────────────────────

class SelectionOverlay:
    """Factory — picks the best overlay strategy for the current setup."""

    def __init__(self, app, image_path, on_selected, on_cancelled, monitors=None):
        _check_layer_shell()
        if monitors:
            mode = "layer-shell" if _LAYER_SHELL_AVAILABLE else "fullscreen_on_monitor"
            log.info("Using per-monitor overlay (%d monitors, mode=%s).", len(monitors), mode)
            self._impl = OverlayController(
                app=app, image_path=image_path, monitors=monitors,
                on_selected=on_selected, on_cancelled=on_cancelled)
        else:
            log.info("Using fallback single-window overlay.")
            self._impl = FallbackOverlay(
                app=app, image_path=image_path,
                on_selected=on_selected, on_cancelled=on_cancelled)

    def present(self):
        self._impl.present()

    def hide_all(self):
        """Dismiss overlays. Safe to call after another window is mapped."""
        if hasattr(self._impl, 'hide_all'):
            self._impl.hide_all()

