import sys
import logging
import time
import threading
import subprocess
import select
from zeroconf import Zeroconf, IPVersion
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

    def __init__(self, glib_loop, server_address: str, sync_volume=False, alsa_mixer='Softvol'):
        super().__init__()
        self.name = "SnapcastWrapper"
        self.keep_running = True
        self.server_address = server_address

        self.dbus_service = SnapcastMPRISInterface(self, glib_loop)

        self.playback_status = PLAYBACK_STOPPED
        self.metadata = {}
        self.stream_name = ""
        self.stream_group = ""

        self.server_streaming_port = self.get_zeroconf_server_stream_port()
        # Start snapclient before the rpc service, to ensure snapclient can register with the server first
        self.snapclient = None
        self.start_snapclient_process()
        # Give the client some time to register
        time.sleep(2)

        self.server_control_port = 1780  # This port cannot be determined through zeroconf
        self.rpc_wrapper = SnapcastRpcWrapper(
            server_address,
            self.server_control_port
        )
        self.websocket_wrapper = SnapcastRpcWebsocketWrapper(
            server_address,
            self.server_control_port,
            self.rpc_wrapper.client_id,
            self
        )

        self.alsa_mixer = alsa_mixer
        self.sync_volume = sync_volume
        if self.sync_volume:
            # Import alsa only when needed, to ensure this code can still run on other platforms
            import alsaaudio as alsa
            self.alsa = alsa
            self.current_volume = self.get_system_volume()
            self.alsa_poll_thread = threading.Thread(target=self.poll_system_volume_loop)
            self.alsa_poll_thread.name = "SnapcastWrapper ALSA Volume poll thread"

        self.manual_pause = False

    def run(self):
        try:
            if self.sync_volume:
                logging.info("ALSA <-> Snapcast volume synchronisation is enabled")
                self.alsa_poll_thread.start()
            else:
                logging.info("ALSA <-> Snapcast volume synchronisation is disabled")
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
        if self.sync_volume:
            self.alsa_poll_thread.join()

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
        if self.snapclient is None:
            self.start_snapclient_process()
        else:
            logging.info("snapcast process is already running")
        self.update_dbus()

    def pause_other_players(self):
        logging.info("pausing other players")
        subprocess.run(["/opt/hifiberry/bin/pause-all", "snapcast"])

    def start_snapclient_process(self):
        logging.info("starting Snapclient")
        cmd = ["/bin/snapclient", "-e"]
        if self.server_address is not None:
            cmd += ["-h", self.server_address]
        if self.server_streaming_port is not None:
            cmd += ["-p", str(self.server_streaming_port)]
        logging.info("starting snapcast with command" + str(cmd))
        self.snapclient = \
            subprocess.Popen(" ".join(cmd),
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

    def on_snapserver_stream_start(self, stream_name, stream_group):
        self.stream_name = stream_name
        self.stream_group = stream_group
        self.update_metadata()
        if self.manual_pause:
            # This prevents snapcast from switching to play again after a second
            # Snapcast will only auto-play after the snapcast source has been paused on the server
            return
        self.start_playback()

    def on_snapserver_volume_change(self, volume_level):
        if self.sync_volume and volume_level > 0:
            self.set_system_volume(volume_level)

    def on_system_volume_change(self, volume_level):
        if self.sync_volume:
            self.rpc_wrapper.set_volume(volume_level)

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

    def poll_system_volume_loop(self):
        logging.info("SnapcastWrapper ALSA volume poll thread started")
        mixer = self.alsa.Mixer(self.alsa_mixer)
        descriptors = mixer.polldescriptors()
        fd = descriptors[0][0]
        event_mask = descriptors[0][1]
        poll = select.poll()
        poll.register(fd, event_mask)
        while self.keep_running:
            # 1s is reasonably long, but still short enough to react quickly
            # in case keep_running changes.
            poll_events = poll.poll(500)
            if poll_events:
                volume = self.get_system_volume()
                if volume != self.current_volume:
                    logging.info("ALSA Volume changed - updating Snapserver")
                    self.on_system_volume_change(volume)
                    self.current_volume = volume
        poll.unregister(fd)
        logging.info("SnapcastWrapper ALSA volume poll thread exited")

    def set_system_volume(self, volume_level):
        if volume_level == self.get_system_volume():
            return
        # Import alsa locally to be system-independent

        mixer = self.alsa.Mixer(self.alsa_mixer)
        mixer.setvolume(volume_level, self.alsa.MIXER_CHANNEL_ALL, self.alsa.PCM_PLAYBACK)
        self.current_volume = volume_level

    def get_system_volume(self):
        mixer = self.alsa.Mixer(self.alsa_mixer)
        return mixer.getvolume(self.alsa.PCM_PLAYBACK)[0]

    def update_metadata(self):
        if self.snapclient is not None:
            self.metadata["xesam:url"] = \
                "snapcast://{}/{}".format(self.server_address, self.stream_name)
            self.metadata["xesam:title"] = self.stream_name

        self.dbus_service.update_property('org.mpris.MediaPlayer2.Player',
                                          'Metadata')

    def get_zeroconf_server_stream_port(self):
        zerocfg = Zeroconf()
        service_info = zerocfg.get_service_info("_snapcast._tcp.local.",
                                                "Snapcast._snapcast._tcp.local.",
                                                3000)
        logging.debug(service_info)
        if service_info is None or service_info.parsed_addresses(IPVersion.All)[0] != self.server_address:
            logging.warning("Failed to obtain snapserver streaming port through zeroconf!")
            return 1704
        logging.info("Obtained snapserver streaming port through zeroconf: " + str(service_info.port))
        return service_info.port
