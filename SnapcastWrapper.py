import sys
import logging
import time
import threading
import fcntl
import os
import subprocess
import json
import SnapcastMPRISInterface


class SnapcastWrapper(threading.Thread):
    """ Wrapper to handle snapcastclient
    """
    PLAYBACK_STOPPED = "stopped"
    PLAYBACK_PAUSED = "pause"
    PLAYBACK_PLAYING = "playing"
    PLAYBACK_UNKNOWN = "unkown"

    def __init__(self, glib_loop, server_ip):
        super().__init__()
        self.glib_loop = glib_loop
        self.playerid = None
        self.playback_status = "stopped"
        self.metadata = {}
        self.server_ip = server_ip

        self.dbus_service = None

        self.bus = dbus.SessionBus()
        self.received_data = False

        self.snapcastclient = None
        self.streamname = ""

    def run(self):
        try:
            self.dbus_service = SnapcastMPRISInterface(self, self.glib_loop)
            self.mainloop()
        except Exception as e:
            logging.error("Snapcastwrapper thread exception: %s", e)
            sys.exit(1)

        logging.error("Snapcastwrapper thread died - this should not happen")
        sys.exit(1)

    def stop_playback(self):
        self.playback_status = SnapcastWrapper.PLAYBACK_STOPPED

    def start_playback(self):
        self.playback_status = SnapcastWrapper.PLAYBACK_PLAYING

    def mainloop(self):
        current_playback_status = None
        while True:
            if self.playback_status != current_playback_status:
                current_playback_status = self.playback_status

                # Changed - do something
                if self.playback_status == PLAYBACK_PLAYING:
                    if self.snapcastclient is None:
                        logging.info("pausing other players")
                        subprocess.run(["/opt/hifiberry/bin/pause-all", "snapcast"])
                        logging.info("starting snapcastclient")
                        if self.server_ip is not None:
                            serveroption = "-h " + self.server_ip
                        else:
                            serveroption = ""
                        self.snapcastclient = \
                            subprocess.Popen("/bin/snapclient -e {}".format(serveroption),
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

                # Playback status has changed, now inform DBUS
                self.update_metadata()
                self.dbus_service.update_property('org.mpris.MediaPlayer2.Player',
                                                  'PlaybackStatus')

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
                    self.parse_stderr(stderr)
                    logging.info("stderr: %s", stderr)

            time.sleep(0.2)

    def parse_stderr(self, data):
        updated = False
        s = data.decode("utf-8")
        for line in s.splitlines():
            if line.startswith("metadata:"):
                _attrib, mds = line.split(":", 1)
                md = json.loads(mds)
                if "STREAM" in md:
                    self.streamname = md["STREAM"]
                    updated = True

        if updated:
            self.update_metadata()

    def update_metadata(self):
        if self.snapcastclient is not None:
            self.metadata["xesam:url"] = \
                "snapcast://{}/{}".format(self.server, self.streamname)

        self.dbus_service.update_property('org.mpris.MediaPlayer2.Player',
                                          'Metadata')

    def non_block_read(output):
        fd = output.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        try:
            return output.read()
        except:
            return ""
