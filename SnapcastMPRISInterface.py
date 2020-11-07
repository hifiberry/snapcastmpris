import sys
import logging
import time
import os
import subprocess
import json
import signal
import dbus.service
import SnapcastWrapper


class SnapcastMPRISInterface(dbus.service.Object):
    ''' The base object of an MPRIS player '''

    PATH = "/org/mpris/MediaPlayer2"
    INTROSPECT_INTERFACE = "org.freedesktop.DBus.Introspectable"
    PROP_INTERFACE = dbus.PROPERTIES_IFACE
    PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"
    ROOT_INTERFACE = "org.mpris.MediaPlayer2"

    IDENTITY = "Snapcast client"

    # python dbus bindings don't include annotations and properties
    MPRIS2_INTROSPECTION = """<node name="/org/mpris/MediaPlayer2">
      <interface name="org.freedesktop.DBus.Introspectable">
        <method name="Introspect">
          <arg direction="out" name="xml_data" type="s"/>
        </method>
      </interface>
      <interface name="org.freedesktop.DBus.Properties">
        <method name="Get">
          <arg direction="in" name="interface_name" type="s"/>
          <arg direction="in" name="property_name" type="s"/>
          <arg direction="out" name="value" type="v"/>
        </method>
        <method name="GetAll">
          <arg direction="in" name="interface_name" type="s"/>
          <arg direction="out" name="properties" type="a{sv}"/>
        </method>
        <method name="Set">
          <arg direction="in" name="interface_name" type="s"/>
          <arg direction="in" name="property_name" type="s"/>
          <arg direction="in" name="value" type="v"/>
        </method>
        <signal name="PropertiesChanged">
          <arg name="interface_name" type="s"/>
          <arg name="changed_properties" type="a{sv}"/>
          <arg name="invalidated_properties" type="as"/>
        </signal>
      </interface>
      <interface name="org.mpris.MediaPlayer2">
        <method name="Raise"/>
        <method name="Quit"/>
        <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
        <property name="CanQuit" type="b" access="read"/>
        <property name="CanRaise" type="b" access="read"/>
        <property name="HasTrackList" type="b" access="read"/>
        <property name="Identity" type="s" access="read"/>
        <property name="DesktopEntry" type="s" access="read"/>
        <property name="SupportedUriSchemes" type="as" access="read"/>
        <property name="SupportedMimeTypes" type="as" access="read"/>
      </interface>
      <interface name="org.mpris.MediaPlayer2.Player">
        <method name="Next"/>
        <method name="Previous"/>
        <method name="Pause"/>
        <method name="PlayPause"/>
        <method name="Stop"/>
        <method name="Play"/>
        <method name="Seek">
          <arg direction="in" name="Offset" type="x"/>
        </method>
        <method name="SetPosition">
          <arg direction="in" name="TrackId" type="o"/>
          <arg direction="in" name="Position" type="x"/>
        </method>
        <method name="OpenUri">
          <arg direction="in" name="Uri" type="s"/>
        </method>
        <signal name="Seeked">
          <arg name="Position" type="x"/>
        </signal>
        <property name="PlaybackStatus" type="s" access="read">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="LoopStatus" type="s" access="readwrite">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="Rate" type="d" access="readwrite">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="Shuffle" type="b" access="readwrite">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="Metadata" type="a{sv}" access="read">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="Volume" type="d" access="readwrite">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
        </property>
        <property name="Position" type="x" access="read">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
        </property>
        <property name="MinimumRate" type="d" access="read">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="MaximumRate" type="d" access="read">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="CanGoNext" type="b" access="read">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="CanGoPrevious" type="b" access="read">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="CanPlay" type="b" access="read">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="CanPause" type="b" access="read">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="CanSeek" type="b" access="read">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
        </property>
        <property name="CanControl" type="b" access="read">
          <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
        </property>
      </interface>
    </node>"""

    def __init__(self, wrapper_instance, glib_loop):
        dbus.service.Object.__init__(self, dbus.SystemBus(),
                                     SnapcastMPRISInterface.PATH)
        self.name = "org.mpris.MediaPlayer2.snapcast"
        self.wrapper_instance = wrapper_instance
        self.glib_loop = glib_loop
        self.bus = dbus.SystemBus()
        self.uname = self.bus.get_unique_name()
        self.dbus_obj = self.bus.get_object("org.freedesktop.DBus",
                                            "/org/freedesktop/DBus")
        self.dbus_obj.connect_to_signal("NameOwnerChanged",
                                        self.name_owner_changed_callback,
                                        arg0=self.name)

        self.bus_name = self.acquire_name()
        logging.info("name on DBus aqcuired")

    def name_owner_changed_callback(self, name, old_owner, new_owner):
        if name == self.name and old_owner == self.uname and new_owner != "":
            try:
                pid = self._dbus_obj.GetConnectionUnixProcessID(new_owner)
            except:
                pid = None
            logging.info("Replaced by %s (PID %s)" %
                         (new_owner, pid or "unknown"))
            self.glib_loop.quit()

    def acquire_name(self):
        return dbus.service.BusName(self.name,
                                    bus=self.bus,
                                    allow_replacement=True,
                                    replace_existing=True)

    def release_name(self):
        if hasattr(self, "_bus_name"):
            del self.bus_name

    @dbus.service.method(INTROSPECT_INTERFACE)
    def Introspect(self):
        return SnapcastMPRISInterface.MPRIS2_INTROSPECTION

    def get_metadata(self):
        return dbus.Dictionary(self.wrapper_instance.metadata, signature='sv')

    def get_dbus_playback_status(self):
        status = self.wrapper_instance.playback_status
        return {SnapcastWrapper.PLAYBACK_PLAYING: 'Playing',
                SnapcastWrapper.PLAYBACK_PAUSED: 'Paused',
                SnapcastWrapper.PLAYBACK_STOPPED: 'Stopped',
                SnapcastWrapper.PLAYBACK_UNKNOWN: 'Unknown'}[status]

    def get_prop_mapping(self):
        player_props = {
            "PlaybackStatus": (self.get_dbus_playback_status, None),
            "Rate": (1.0, None),
            "Metadata": (self.get_metadata, None),
            "MinimumRate": (1.0, None),
            "MaximumRate": (1.0, None),
            "CanGoNext": (False, None),
            "CanGoPrevious": (False, None),
            "CanPlay": (True, None),
            "CanPause": (True, None),
            "CanSeek": (False, None),
            "CanControl": (False, None),
        }

        root_props = {
            "CanQuit": (False, None),
            "CanRaise": (False, None),
            "DesktopEntry": ("snapcastmpris", None),
            "HasTrackList": (False, None),
            "Identity": (SnapcastMPRISInterface.IDENTITY, None),
            "SupportedUriSchemes": (dbus.Array(signature="s"), None),
            "SupportedMimeTypes": (dbus.Array(signature="s"), None)
        }

        return {
            SnapcastMPRISInterface.PLAYER_INTERFACE: player_props,
            SnapcastMPRISInterface.ROOT_INTERFACE: root_props,
        }

    @dbus.service.signal(PROP_INTERFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed_properties,
                          invalidated_properties):
        pass

    @dbus.service.method(PROP_INTERFACE,
                         in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        getter, _setter = self.get_prop_mapping()[interface][prop]
        if callable(getter):
            return getter()
        return getter

    @dbus.service.method(PROP_INTERFACE,
                         in_signature="ssv", out_signature="")
    def Set(self, interface, prop, value):
        _getter, setter = self.get_prop_mapping()[interface][prop]
        if setter is not None:
            setter(value)

    @dbus.service.method(PROP_INTERFACE,
                         in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        read_props = {}
        props = self.get_prop_mapping()[interface]
        for key, (getter, _setter) in props.items():
            if callable(getter):
                getter = getter()
            read_props[key] = getter
        return read_props

    def update_property(self, interface, prop):
        getter, _setter = self.get_prop_mapping()[interface][prop]
        if callable(getter):
            value = getter()
        else:
            value = getter
        logging.debug('Updated property: %s = %s' % (prop, value))
        self.PropertiesChanged(interface, {prop: value}, [])
        return value

    # Player methods
    @dbus.service.method(PLAYER_INTERFACE, in_signature='', out_signature='')
    def Pause(self):
        logging.debug("received DBUS pause")
        self.wrapper_instance.pause_playback()

    @dbus.service.method(PLAYER_INTERFACE, in_signature='', out_signature='')
    def PlayPause(self):
        logging.debug("received DBUS play/pause")
        status = self.wrapper_instance.playback_status

        if status == SnapcastWrapper.PLAYBACK_PLAYING:
            self.wrapper_instance.pause_playback()
        else:
            self.wrapper_instance.start_playback()

    @dbus.service.method(PLAYER_INTERFACE, in_signature='', out_signature='')
    def Stop(self):
        logging.debug("received DBUS stop")
        self.wrapper_instance.stop_playback()

    @dbus.service.method(PLAYER_INTERFACE, in_signature='', out_signature='')
    def Play(self):
        logging.debug("received DBUS play")
        self.wrapper_instance.start_playback()
