#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# (License and author information as in the original script)

import sys
import logging
import time
import signal
import configparser
import argparse

from snapcastmpris.SnapcastWrapper import SnapcastWrapper
from zeroconf import Zeroconf, IPVersion

import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

try:
    from gi.repository import GLib, GObject
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
        logging.info("read /etc/snapcastmpris.conf")
    except Exception:
        logging.info("can't read /etc/snapcastmpris.conf, using default configurations")

    return config


def get_zeroconf_server_address():
    zerocfg = Zeroconf()
    service_info = zerocfg.get_service_info("_snapcast._tcp.local.", "Snapcast._snapcast._tcp.local.", 3000)
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


def main():
    DBusGMainLoop(set_as_default=True)

    # Parse arguments
    parser = argparse.ArgumentParser(
        prog='snapcastmpris',
        description='A wrapper around the Snapclient binary and the Snapserver RPC API. It exposes the current playing state on the desktop bus (D-BUS), and allows control through the DBUS play/pause/stop signals.')

    parser.add_argument('-v', '--verbose', action='store_true', help='enable verbose logging')
    parser.add_argument('-s', '--sync_alsa_volume', action='store_true', help='enable synchronization with alsa volume')
    parser.add_argument('-m', '--mixer', default='Softvol', type=str, help='set custom mixer for alsa')

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        format='%(levelname)s: %(name)s - %(message)s',
        level=logging.DEBUG if args.verbose else logging.INFO)

    # Sync ALSA volume
    volume_sync_enabled = args.sync_alsa_volume
    mixer = args.mixer

    # Set up the main loop
    glib_main_loop = GLib.MainLoop()
    signal.signal(signal.SIGUSR1, pause_snapcast)
    signal.signal(signal.SIGUSR2, stop_snapcast)

    try:
        config = read_config()
        server_address = config.get("snapcast", "server", fallback=get_zeroconf_server_address())
        if not server_address:
            logging.critical("Snapcast cannot be launched: failed to obtain snapcast server address.")
            exit(1)

        if config.has_option("snapcast", "alsa-mixer"):
            mixer = config.get("snapcast", "alsa-mixer")

        if not volume_sync_enabled and config.has_option("snapcast", "sync-alsa-volume"):
            volume_sync_enabled = config.getboolean("snapcast", "sync-alsa-volume", fallback=False)

        snapcast_wrapper = SnapcastWrapper(glib_main_loop, server_address, sync_volume=volume_sync_enabled, alsa_mixer=mixer)

        if config.getboolean("snapcast", "autostart", fallback=True):
            snapcast_wrapper.autostart_on_stream()

        snapcast_wrapper.start()
        logging.info("Snapcast wrapper thread started")

    except dbus.exceptions.DBusException as e:
        logging.error("DBUS error: %s", e)
        sys.exit(1)

    time.sleep(2)
    if not snapcast_wrapper.is_alive():
        logging.error("Snapcast connector thread died, exiting")
        sys.exit(1)

    try:
        logging.info("main loop started")
        glib_main_loop.run()
    except KeyboardInterrupt:
        logging.debug('Caught SIGINT, exiting.')
    snapcast_wrapper.stop()
    snapcast_wrapper.join()
    logging.info("All threads have exited")


if __name__ == '__main__':
    main()

