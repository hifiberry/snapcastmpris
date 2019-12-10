#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Author: Modul 9 <info@hifiberry.com>
# Based on mpDris2 by
#          Jean-Philippe Braun <eon@patapon.info>,
#          Mantas Mikulėnas <grawity@gmail.com>
# Based on mpDris by:
#          Erik Karlsson <pilo@ayeon.org>
# Some bits taken from quodlibet mpris plugin by:
#           <christoph.reiter@gmx.at>

#
# This creates an MPRIS service for Snapcast on the system bus
# Implements only a minimal MPRIS subset that is required by HiFiBerryOS
#

import sys
import logging
import time
import threading
import fcntl
import os

import subprocess

import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

try:
    from gi.repository import GLib
    using_gi_glib = True
except ImportError:
    import glib as GLib

identity = "Snapcast client"

PLAYBACK_STOPPED = "stopped"
PLAYBACK_PAUSED = "pause"
PLAYBACK_PLAYING = "playing"
PLAYBACK_UNKNOWN = "unkown"

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


def non_block_read(output):
    fd = output.fileno()
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    try:
        return output.read()
    except:
        return ""


class SnapcastWrapper(threading.Thread):
    """ Wrapper to handle snapcastclient
    """

    def __init__(self, snapcastserver):
        super().__init__()
        self.playerid = None
        self.playback_status = "stopped"
        self.metadata = {}
        self.server = snapcastserver

        self.dbus_service = None

        self.bus = dbus.SessionBus()
        self.received_data = False

        self.snapcastclient = None

    def run(self):
        try:
            self.dbus_service = MPRISInterface()

            self.mainloop()

        except Exception as e:
            logging.error("Snapcastwrapper thread exception: %s", e)
            sys.exit(1)

        logging.error("Snapcastwrapper thread died - this should not happen")
        sys.exit(1)

    def mainloop(self):
        current_playback_status = None
        while True:
            if self.playback_status != current_playback_status:
                current_playback_status = self.playback_status

                # Changed - do something

                if self.playback_status == PLAYBACK_PLAYING:
                    if self.snapcastclient is None:
                        logging.info("pausing other players")
                        # TODO: system pause-all
                        logging.info("starting snapcastclient")
                        self.snapcastclient = \
                            subprocess.Popen("/bin/snapclient -h {} -e".format(self.server),
                                              stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE,
                                              shell=True)
                        logging.info("snapcastclient now running in background")

                    else:
                        logging.error("snapcast process seems to be running already")

                else:
                    # Not playing: kill client
                    if self.snapcastclient is None:
                        logging.info("No snapcast client running, doing nothing")
                    else:
                        logging.info("Killing snapcast client, doing nothing")
                        self.snapcastclient.kill()
                        # Wait until it died
                        _outs, _errs = self.snapcastclient.communicate()
                        self.snapcastclient = None

            # Check if snapcast is still running
            if self.snapcastclient:
                if self.snapcastclient.poll() is not None:
                    logging.warning("snapclient died")
                    self.playback_status = PLAYBACK_STOPPED
                    self.snapcastclient = None

            if self.snapcastclient:
                stdout = non_block_read(self.snapcastclient.stdout)
                if stdout:
                    logging.debug("stdout: %s", stdout)

                stderr = non_block_read(self.snapcastclient.stderr)
                if stderr:
                    logging.info("stderr: %s", stderr)

            time.sleep(0.2)

    def notify_status(self):
        """
        No metadata support at the moment
        """

    def last_status(self):
        if time.time() - self._time >= 2:
            self.timer_callback()
        return self._status.copy()

    def _update_properties(self, force=False):
        pass

        #   self._dbus_service.update_property('org.mpris.MediaPlayer2.Player',
        #                                      'PlaybackStatus')


class MPRISInterface(dbus.service.Object):
    ''' The base object of an MPRIS player '''

    PATH = "/org/mpris/MediaPlayer2"
    INTROSPECT_INTERFACE = "org.freedesktop.DBus.Introspectable"
    PROP_INTERFACE = dbus.PROPERTIES_IFACE

    def __init__(self):
        dbus.service.Object.__init__(self, dbus.SystemBus(),
                                     MPRISInterface.PATH)
        self.name = "org.mpris.MediaPlayer2.snapcast"
        self.bus = dbus.SystemBus()
        self.uname = self.bus.get_unique_name()
        self.dbus_obj = self.bus.get_object("org.freedesktop.DBus",
                                            "/org/freedesktop/DBus")
        self.dbus_obj.connect_to_signal("NameOwnerChanged",
                                        self.name_owner_changed_callback,
                                        arg0=self.name)

        self.acquire_name()
        logging.info("name on DBus aqcuired")

    def name_owner_changed_callback(self, name, old_owner, new_owner):
        if name == self.name and old_owner == self.uname and new_owner != "":
            try:
                pid = self._dbus_obj.GetConnectionUnixProcessID(new_owner)
            except:
                pid = None
            logging.info("Replaced by %s (PID %s)" %
                         (new_owner, pid or "unknown"))
            loop.quit()

    def acquire_name(self):
        self.bus_name = dbus.service.BusName(self.name,
                                             bus=self.bus,
                                             allow_replacement=True,
                                             replace_existing=True)

    def release_name(self):
        if hasattr(self, "_bus_name"):
            del self.bus_name

    ROOT_INTERFACE = "org.mpris.MediaPlayer2"
    ROOT_PROPS = {
        "CanQuit": (False, None),
        "CanRaise": (False, None),
        "DesktopEntry": ("snapcastmpris", None),
        "HasTrackList": (False, None),
        "Identity": (identity, None),
        "SupportedUriSchemes": (dbus.Array(signature="s"), None),
        "SupportedMimeTypes": (dbus.Array(signature="s"), None)
    }

    @dbus.service.method(INTROSPECT_INTERFACE)
    def Introspect(self):
        return MPRIS2_INTROSPECTION

    def get_playback_status():
        status = snapcast_wrapper.playback_status
        return {PLAYBACK_PLAYING: 'Playing',
                PLAYBACK_PAUSED: 'Paused',
                PLAYBACK_STOPPED: 'Stopped',
                PLAYBACK_UNKNOWN: 'Unknown'}[status]

    def get_metadata():
        return dbus.Dictionary(snapcast_wrapper.metadata, signature='sv')

    PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"
    PLAYER_PROPS = {
        "PlaybackStatus": (get_playback_status, None),
        "Rate": (1.0, None),
        "Metadata": (get_metadata, None),
        "MinimumRate": (1.0, None),
        "MaximumRate": (1.0, None),
        "CanGoNext": (False, None),
        "CanGoPrevious": (False, None),
        "CanPlay": (True, None),
        "CanPause": (True, None),
        "CanSeek": (False, None),
        "CanControl": (False, None),
    }

    PROP_MAPPING = {
        PLAYER_INTERFACE: PLAYER_PROPS,
        ROOT_INTERFACE: ROOT_PROPS,
    }

    @dbus.service.signal(PROP_INTERFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed_properties,
                          invalidated_properties):
        pass

    @dbus.service.method(PROP_INTERFACE,
                         in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        getter, _setter = self.PROP_MAPPING[interface][prop]
        if callable(getter):
            return getter()
        return getter

    @dbus.service.method(PROP_INTERFACE,
                         in_signature="ssv", out_signature="")
    def Set(self, interface, prop, value):
        _getter, setter = self.PROP_MAPPING[interface][prop]
        if setter is not None:
            setter(value)

    @dbus.service.method(PROP_INTERFACE,
                         in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        read_props = {}
        props = self.PROP_MAPPING[interface]
        for key, (getter, _setter) in props.items():
            if callable(getter):
                getter = getter()
            read_props[key] = getter
        return read_props

    def update_property(self, interface, prop):
        getter, _setter = self.__prop_mapping[interface][prop]
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
        snapcast_wrapper.playback_status = PLAYBACK_STOPPED
        return

    @dbus.service.method(PLAYER_INTERFACE, in_signature='', out_signature='')
    def PlayPause(self):
        logging.debug("received DBUS play/pause")
        status = snapcast_wrapper.playback_status

        if status == PLAYBACK_PLAYING:
            snapcast_wrapper.playback_status = PLAYBACK_STOPPED
        else:
            snapcast_wrapper.playback_status = PLAYBACK_PLAYING
        return

    @dbus.service.method(PLAYER_INTERFACE, in_signature='', out_signature='')
    def Stop(self):
        logging.debug("received DBUS stop")
        snapcast_wrapper.playback_status = PLAYBACK_STOPPED
        return

    @dbus.service.method(PLAYER_INTERFACE, in_signature='', out_signature='')
    def Play(self):
        snapcast_wrapper.playback_status = PLAYBACK_PLAYING
        return


if __name__ == '__main__':
    DBusGMainLoop(set_as_default=True)

    if len(sys.argv) > 1:
        if "-v" in sys.argv:
            logging.basicConfig(format='%(levelname)s: %(name)s - %(message)s',
                                level=logging.DEBUG)
            logging.debug("enabled verbose logging")
    else:
        logging.basicConfig(format='%(levelname)s: %(name)s - %(message)s',
                            level=logging.INFO)

    # Set up the main loop
    loop = GLib.MainLoop()

    server = "192.168.30.110"

    # Create wrapper to handle connection failures with MPD more gracefully
    try:
        snapcast_wrapper = SnapcastWrapper(server)
        snapcast_wrapper.start()
        logging.info("Snapcast wrapper thread started")
    except dbus.exceptions.DBusException as e:
        logging.error("DBUS error: %s", e)
        sys.exit(1)

    time.sleep(2)
    if not (snapcast_wrapper.is_alive()):
        logging.error("Snapcast connector thread died, exiting")
        sys.exit(1)

    # Run idle loop
    try:
        logging.info("main loop started")
        loop.run()
    except KeyboardInterrupt:
        logging.debug('Caught SIGINT, exiting.')
