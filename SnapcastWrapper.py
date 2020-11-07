import sys
import logging
import time
import threading
import subprocess
from SnapcastMPRISInterface import SnapcastMPRISInterface
from SnapcastRpcListener import SnapcastRpcListener
from SnapcastRpcWebsocketWrapper import SnapcastRpcWebsocketWrapper
from SnapcastRpcWrapper import SnapcastRpcWrapper

PLAYBACK_STOPPED = "stopped"
PLAYBACK_PAUSED = "pause"
PLAYBACK_PLAYING = "playing"
PLAYBACK_UNKNOWN = "unkown"


class SnapcastWrapper(threading.Thread, SnapcastRpcListener):
    """ Wrapper to handle snapclient
    """

    def __init__(self, glib_loop, server_ip: str):
        super().__init__()
        self.name = "SnapcastWrapper"
        self.keep_running = True

        if server_ip is None or len(server_ip) == 0:
            logging.critical("CANNOT START SNAPCAST WRAPPER WITHOUT VALID SERVER IP")
            exit(1)

        self.dbus_service = SnapcastMPRISInterface(self, glib_loop)
        self.rpc_wrapper = SnapcastRpcWrapper(server_ip)
        self.websocket_wrapper = SnapcastRpcWebsocketWrapper(server_ip, self)

        self.playback_status = PLAYBACK_STOPPED
        self.metadata = {}
        self.server_ip = server_ip

        self.snapclient = None
        self.start_snapclient_process()
        self.stream_name = ""

        self.manual_pause = False

    def run(self):
        try:
            self.mainloop()
        except Exception as e:
            logging.error("SnapcastWrapper thread exception: %s", e)
            sys.exit(1)

        if self.keep_running:
            logging.error("SnapcastWrapper thread died - this should not happen")
            sys.exit(1)
        else:
            logging.info("SnapcastWrapper thread has exited")

    def stop(self):
        self.websocket_wrapper.stop()
        self.keep_running = False

    def start_playback(self):
        self.playback_status = PLAYBACK_PLAYING
        self.pause_other_players()
        if self.snapclient is None:
            self.start_snapclient_process()
        else:
            logging.info("snapcast process is already running")
        self.update_dbus()
        # Give snapclient a bit of time to register with the server
        time.sleep(0.5)
        self.rpc_wrapper.unmute()

    def autostart_on_stream(self):
        self.playback_status = PLAYBACK_PAUSED
        self.start_snapclient_process()
        self.update_dbus()

    def pause_other_players(self):
        logging.info("pausing other players")
        subprocess.run(["/opt/hifiberry/bin/pause-all", "snapcast"])

    def start_snapclient_process(self):
        logging.info("starting Snapclient")
        if self.server_ip is not None:
            server_ip_flag = "-h " + self.server_ip
        else:
            server_ip_flag = ""
        self.snapclient = \
            subprocess.Popen(f"/bin/snapclient -e {server_ip_flag}",
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             shell=True)
        logging.info("snapclient now running in background")

    def pause_playback(self):
        self.playback_status = PLAYBACK_PAUSED
        # This prevents snapcast from switching to play again after a second
        # Snapcast will only auto-play after the snapcast source has been paused on the server
        self.manual_pause = True
        self.rpc_wrapper.mute()
        self.update_dbus()

    def stop_playback(self):
        self.playback_status = PLAYBACK_STOPPED
        # Not playing: kill client
        if self.snapclient is None:
            logging.info("No snapclient running, doing nothing")
        else:
            logging.info("Killing snapclient, doing nothing")
            self.snapclient.kill()
            # Wait until it died
            time.sleep(0.25)
            self.snapclient = None
        self.update_dbus()

    def update_dbus(self):
        """
        Update dbus after a change
        """
        # Playback status has changed, now inform DBUS
        self.update_metadata()
        self.dbus_service.update_property('org.mpris.MediaPlayer2.Player',
                                          'PlaybackStatus')

    def on_snapclient_died(self):
        """
        Called when the snapclient process has died
        """
        logging.warning("snapclient died")
        self.playback_status = PLAYBACK_STOPPED
        self.snapclient = None

    def mainloop(self):
        while self.keep_running:
            # Check if snapcast is still running
            if self.snapclient:
                if self.snapclient.poll() is not None:
                    self.on_snapclient_died()
            time.sleep(0.2)

    def on_snapserver_stream_pause(self):
        self.pause_playback()
        self.manual_pause = False
        pass

    def on_snapserver_stream_start(self, stream_name):
        self.stream_name = stream_name
        if self.manual_pause:
            # This prevents snapcast from switching to play again after a second
            # Snapcast will only auto-play after the snapcast source has been paused on the server
            return
        self.start_playback()

    def on_snapserver_volume_change(self, volume_level):
        # TODO: synchronize with OS volume
        pass

    def on_snapserver_mute(self):
        self.playback_status = PLAYBACK_PAUSED
        pass

    def on_snapserver_unmute(self):
        if self.playback_status != PLAYBACK_PLAYING:
            # If unmuted while a stream is playing, then treat this as
            # "start playing" in case the wrapper isn't in the playin state
            # already
            # TODO: Check if a stream is playing
            pass

    def update_metadata(self):
        if self.snapclient is not None:
            self.metadata["xesam:url"] = \
                "snapcast://{}/{}".format(self.server_ip, self.stream_name)

        self.dbus_service.update_property('org.mpris.MediaPlayer2.Player',
                                          'Metadata')
