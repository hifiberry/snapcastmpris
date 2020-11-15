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
import signal
import configparser
from SnapcastWrapper import SnapcastWrapper
from zeroconf import Zeroconf, IPVersion

import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

try:
    from gi.repository import GLib

    using_gi_glib = True
except ImportError:
    import glib as GLib


def stop_snapcast(signalNumber, frame):
    logging.info("received USR1, stopping snapcast")
    snapcast_wrapper.stop_playback()


def pause_snapcast(signalNumber, frame):
    logging.info("received USR2, pausing snapcast")
    snapcast_wrapper.pause_playback()


def read_config():
    config = configparser.ConfigParser()
    try:
        with open("/etc/snapcastmpris.conf") as f:
            config.read_string("[snapcast]\n" + f.read())
        logging.info("read /etc/snapcastclient.conf")
    except:
        logging.info("can't read /etc/snapcastclient.conf, using default configurations")
        config = {"general": {}}

    return config


def get_zeroconf_server_address():
    zerocfg = Zeroconf()
    service_info = zerocfg.get_service_info("_snapcast._tcp.local.", "Snapcast._snapcast._tcp.local.", 3000)
    if service_info is None:
        logging.error("Failed to obtain snapserver address through zeroconf!")
        return None
    logging.debug(service_info)
    address = service_info.parsed_addresses(IPVersion.All)[0]
    logging.info("Obtained snapserver address through zeroconf: " + address)
    return address


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
    glib_main_loop = GLib.MainLoop()
    signal.signal(signal.SIGUSR1, pause_snapcast)
    signal.signal(signal.SIGUSR2, stop_snapcast)

    # Create wrapper to handle connection failures with MPD more gracefully
    try:
        config = read_config()

        # Server to connect to
        server_address = None
        if config.has_option("snapcast", "server"):
            # Read the server address from the server if possible
            server_address = config.get("snapcast", "server")
        if server_address is None or len(server_address) < 2:
            # No server address defined, use zeroconf
            # Snapclient can do this as well when no host is specified, but we
            # need the server address as well to access the API
            # Getting it in one central place ensures we use the same address for
            # snapclient, the snapserver API, and the snapserver WS API
            server_address = get_zeroconf_server_address()
        if server_address is None:
            # If no address was defined, and zeroconf failed to get one, we can't launch
            logging.critical("Snapcast cannot be launched: failed to obtain snapcast server address.")
            exit(1)

        snapcast_wrapper = SnapcastWrapper(glib_main_loop, server_address)

        # Auto start for snapcast
        if config.getboolean("snapcast", "autostart", fallback=True):
            snapcast_wrapper.autostart_on_stream()

        # Start the wrapper
        snapcast_wrapper.start()
        logging.info("Snapcast wrapper thread started")
    except dbus.exceptions.DBusException as e:
        logging.error("DBUS error: %s", e)
        sys.exit(1)

    # Wait a few seconds so the thread can start
    time.sleep(2)
    if not (snapcast_wrapper.is_alive()):
        logging.error("Snapcast connector thread died, exiting")
        sys.exit(1)

    # Run idle loop
    try:
        logging.info("main loop started")
        glib_main_loop.run()
    except KeyboardInterrupt:
        logging.debug('Caught SIGINT, exiting.')
    snapcast_wrapper.stop()
    logging.info("Waiting for snapcast wrapper thread to exit")
    snapcast_wrapper.join()
    logging.info("All threads have exited")
    exit(0)
