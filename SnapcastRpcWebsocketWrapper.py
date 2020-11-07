import json
import logging
import threading
import websocket
from SnapcastRpcWrapper import SnapcastRpcWrapper
from SnapcastRpcListener import SnapcastRpcListener

RPC_EVENT_CLIENT_VOLUME_CHANGE = "Client.OnVolumeChanged"
RPC_EVENT_CLIENT_MUTE = "Client.OnMute"
RPC_EVENT_CLIENT_CONNECT = "Client.OnConnect"
RPC_EVENT_CLIENT_DISCONNECT = "Client.OnDisconnect"
RPC_EVENT_STREAM_UPDATE = "Stream.OnUpdate"


class SnapcastRpcWebsocketWrapper:

    def __init__(self, server_ip: str, listener: SnapcastRpcListener):
        self.healthy = True
        self.server_ip = server_ip
        self.client_id = SnapcastRpcWrapper.get_client_id()
        self.listener = listener
        self.websocket = websocket.WebSocketApp(
            "ws://" + server_ip + ":1780/jsonrpc",
            on_message=self.on_ws_message,
            on_error=self.on_ws_error,
            on_close=self.on_ws_close,
        )
        self.websocket_thread = threading.Thread(target=self.websocket_loop, args=())
        self.websocket_thread.name = "SnapcastRpcWebsocketWrapper"
        self.websocket_thread.start()

    def websocket_loop(self):
        logging.info("Started SnapcastRpcWebsocketWrapper loop")
        self.websocket.run_forever()
        logging.info("Ending SnapcastRpcWebsocketWrapper loop")

    def on_ws_message(self, message):
        logging.debug("Snapcast RPC websocket message received")
        logging.debug(message)
        json_data = json.loads(message)

        handlers = self.get_event_handlers_mapping()

        event = json_data["method"]
        handlers[event](json_data["params"])

    def get_event_handlers_mapping(self):
        return {
            RPC_EVENT_CLIENT_VOLUME_CHANGE: self.on_volume_change,
            RPC_EVENT_CLIENT_MUTE: self.on_mute,
            RPC_EVENT_CLIENT_CONNECT: self.on_client_connect,
            RPC_EVENT_CLIENT_DISCONNECT: self.on_client_disconnect,
            RPC_EVENT_STREAM_UPDATE: self.on_stream_update,
        }

    def on_volume_change(self, params: {}):
        if not self.targeted_at_current_client(params):
            return
        volume = params['volume']['percent']
        logging.info("Snapclient volume changed to " + str(volume))
        self.listener.on_snapserver_volume_change(volume)

    def on_mute(self, params: {}):
        if not self.targeted_at_current_client(params):
            return
        is_muted = params['mute']
        if is_muted:
            logging.info("Snapclient muted")
            self.listener.on_snapserver_mute()
        else:
            logging.info("Snapclient unmuted")
            self.listener.on_snapserver_unmute()

    def on_client_connect(self, params: {}):
        if not self.targeted_at_current_client(params):
            return
        # Not used right now, but could be useful for status monitoring
        # This event is fired every second for every connected client
        logging.debug("Client connected!")

    def on_client_disconnect(self, params: {}):
        if not self.targeted_at_current_client(params):
            return
        # Not used right now, but could be useful for status monitoring
        logging.info("Client disconnected!")

    def on_stream_update(self, params: {}):
        # There is a lot of information here, such as audio details
        # We focus on idle/playing right now

        # TODO: we need to know/check if the stream is played on this client
        # It might only be targeted at other players, in which case this player shouldn't do anything

        stream_status = params["stream"]["status"]
        # The stream name can be present in id, stream.id, or stream.meta.STREAM
        if "meta" in params["stream"]:
            stream_name = params["stream"]["meta"]["STREAM"]
        else:
            stream_name = params["stream"]["id"]

        if stream_status == "playing":
            logging.info("Snapclient stream started")
            self.listener.on_snapserver_stream_start(stream_name)
        elif stream_status == "idle":
            logging.info("Snapclient stream idle")
            self.listener.on_snapserver_stream_pause()
        else:
            logging.warning("Snapclient stream has unknown status: " + stream_status)

    def targeted_at_current_client(self, params: {}):
        # This method works only for client-specific events!
        return params["id"] == self.client_id

    # noinspection PyMethodMayBeStatic
    def on_ws_error(self, error):
        logging.error("Snapcast RPC websocket error")
        logging.error(error)

    def on_ws_close(self):
        logging.info("Snapcast RPC websocket closed!")
        self.healthy = False

    def stop(self):
        self.websocket.keep_running = False
        logging.info("Waiting for websocket thread to exit")
        self.websocket_thread.join()
