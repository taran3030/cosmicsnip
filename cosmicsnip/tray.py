"""System tray icon via DBus StatusNotifierItem protocol.

Registers with org.kde.StatusNotifierWatcher so COSMIC's panel tray
applet picks it up. Left-click triggers Activate (new snip),
right-click shows a minimal menu.
"""

import os
from gi.repository import Gio, GLib

from cosmicsnip.log import get_logger

log = get_logger("tray")

# SNI DBus interface XMLs
_SNI_NODE = Gio.DBusNodeInfo.new_for_xml("""
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <signal name="NewIcon"/>
    <signal name="NewTitle"/>
    <signal name="NewStatus">
      <arg name="status" type="s"/>
    </signal>
  </interface>
</node>
""")

_MENU_NODE = Gio.DBusNodeInfo.new_for_xml("""
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
  </interface>
</node>
""")

_OBJ_PATH = "/StatusNotifierItem"
_MENU_PATH = "/StatusNotifierMenu"


class TrayIcon:
    """Minimal StatusNotifierItem that shows in COSMIC's system tray."""

    def __init__(self, app, on_activate):
        self._app = app
        self._on_activate = on_activate
        self._bus = None
        self._sni_reg_id = 0
        self._menu_reg_id = 0
        self._menu_revision = 1

    def register(self):
        """Register the tray icon on the session bus."""
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        if not self._bus:
            log.warning("Could not connect to session bus for tray icon.")
            return

        # Register SNI object
        self._sni_reg_id = self._bus.register_object(
            _OBJ_PATH,
            _SNI_NODE.interfaces[0],
            self._handle_sni_call,
            self._handle_sni_get,
            None,
        )

        # Register menu object
        self._menu_reg_id = self._bus.register_object(
            _MENU_PATH,
            _MENU_NODE.interfaces[0],
            self._handle_menu_call,
            self._handle_menu_get,
            None,
        )

        # Register with the StatusNotifierWatcher
        try:
            bus_name = self._bus.get_unique_name()
            self._bus.call_sync(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (bus_name,)),
                None, Gio.DBusCallFlags.NONE, -1, None,
            )
            log.info("Tray icon registered with StatusNotifierWatcher.")
        except GLib.Error as exc:
            log.warning("StatusNotifierWatcher not available: %s", exc.message)

    # ── SNI handlers ─────────────────────────────────────────────────────

    def _handle_sni_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method == "Activate":
            log.info("Tray icon activated — starting new snip.")
            GLib.idle_add(self._on_activate)
            invocation.return_value(None)
        elif method == "SecondaryActivate":
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", "")

    def _handle_sni_get(self, _conn, _sender, _path, _iface, prop):
        props = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "cosmicsnip"),
            "Title": GLib.Variant("s", "CosmicSnip"),
            "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", "camera-photo-symbolic"),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", _MENU_PATH),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", (
                "camera-photo-symbolic", [], "CosmicSnip", "Click to take a screenshot"
            )),
        }
        return props.get(prop)

    # ── Menu handlers ────────────────────────────────────────────────────

    def _handle_menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "GetLayout":
            layout = self._build_menu_layout()
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (
                self._menu_revision, layout
            )))
        elif method == "Event":
            item_id, event_id, _data, _ts = params.unpack()
            if event_id == "clicked":
                if item_id == 1:
                    GLib.idle_add(self._on_activate)
                elif item_id == 2:
                    GLib.idle_add(self._app.quit)
            invocation.return_value(None)
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", "")

    def _handle_menu_get(self, _conn, _sender, _path, _iface, prop):
        props = {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }
        return props.get(prop)

    def _build_menu_layout(self):
        """Build the dbusmenu layout: root → [New Snip, Quit]."""
        new_snip = GLib.Variant("(ia{sv}av)", (1, {
            "label": GLib.Variant("s", "New Screenshot"),
            "icon-name": GLib.Variant("s", "camera-photo-symbolic"),
        }, []))
        quit_item = GLib.Variant("(ia{sv}av)", (2, {
            "label": GLib.Variant("s", "Quit"),
            "icon-name": GLib.Variant("s", "application-exit-symbolic"),
        }, []))
        root = (0, {
            "children-display": GLib.Variant("s", "submenu"),
        }, [new_snip, quit_item])
        return root
