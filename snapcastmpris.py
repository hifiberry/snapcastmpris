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
import argparse

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
    service_info = zerocfg.get_service_info("_snapcast._tcp.local.",
                                            "Snapcast._snapcast._tcp.local.",
                                            3000)
    if service_info is None:
        logging.error("Failed to obtain snapserver address through zeroconf!")
        return None
    logging.debug(service_info)
    snapserver_address = None
    all_addresses = service_info.parsed_addresses(IPVersion.V4Only)
    for address in all_addresses:
        if address != "0.0.0.0":
            snapserver_address = address
    if snapserver_address is None:
        logging.critical("Failed to obtain snapserver address through zeroconf, got 0.0.0.0 but expected real address!")
        logging.error(service_info)
        logging.error(all_addresses)
        return None
    if len(all_addresses) > 1:
        logging.warning("Got more than one zeroconf address, what's happening here?!")
        logging.warning(service_info)
        logging.warning(all_addresses)
    logging.info("Obtained snapserver address through zeroconf: " + snapserver_address)
    return snapserver_address


if __name__ == '__main__':
    DBusGMainLoop(set_as_default=True)

    # Parse arguments
    parser = argparse.ArgumentParser(
                    prog='snapcastmpris',
                    description='A wrapper around the Snapclient binary and the Snapserver RPC API. It exposes the current playing state on the desktop bus (D-BUS), and allows control through the DBUS play/pause/stop signals.')

    parser.add_argument(
        '-v', '--verbose',
                    action='store_true', 
                    help='enabled verbose logging')

    parser.add_argument(
        '-s', '--sync_alsa_volume', 
        action='store_true',
        help='enable synchronization with alsa volume')

    parser.add_argument(
        '-m', '--mixer', 
        default='Softvol',
        type=str,
        help='set custom mixer for alsa')

    args = parser.parse_args()

    # Set dubug logging
    if args.verbose == True:
        logging.basicConfig(format='%(levelname)s: %(name)s - %(message)s',
                            level=logging.DEBUG)
        logging.debug("enabled verbose logging via argv")
    else:
        logging.basicConfig(format='%(levelname)s: %(name)s - %(message)s',
                            level=logging.INFO)

    # Set alsa volume synchronization
    volume_sync_enabled = False
    if args.sync_alsa_volume == True:
        volume_sync_enabled = True
        logging.debug("volume sync flag set via argv to True")

    mixer = 'Softvol'
    # Debug output for alsa mixer
    if not args.mixer == 'Softvol':
        mixer = args.mixer;
        logging.debug("alsa mixer changed via argv to " + mixer)

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
        
        # Set alsa mixer
        if config.has_option("snapcast", "alsa-mixer"):
            mixer = config.get("snapcast", "alsa-mixer")
            logging.debug("alsa mixer set via config to " + mixer)

        # Set volume sync with alsa
        if not volume_sync_enabled == True and config.has_option("snapcast", "sync-alsa-volume"):
            volume_sync_enabled = config.getboolean("snapcast", "sync-alsa-volume", fallback=False);
            logging.debug("volume sync flag set via config to {}".format(volume_sync_enabled))

        snapcast_wrapper = SnapcastWrapper(glib_main_loop, server_address, sync_volume=volume_sync_enabled, alsa_mixer=args.mixer)

        # Auto start for snapcast
        if config.getboolean("snapcast", "autostart", fallback=True):
            snapcast_wrapper.autostart_on_stream()

        # Start the wrapper
        snapcast_wrapper.start()
        logging.info("Snapcast wrapper thread started")
    except dbus.exceptions.DBusException as e:
        logging.error("DBUS error: %s", e)
        sys.exit(1)

    # Wait a few seconds so the thread can start. Killing the application in
    # these 2 seconds may cause unspecified behaviour
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
