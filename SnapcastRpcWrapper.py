import json
from os import listdir
import logging
import requests

REQ_TAG_GET_SERVER_RPC_VERSION = 0
REQ_TAG_SET_VOLUME = 1
REQ_TAG_SET_MUTE = 2
REQ_TAG_SET_NAME = 3
REQ_TAG_SET_LATENCY = 4
REQ_TAG_GET_STATUS = 5
REQ_TAG_GET_SERVER_STATUS = 6


class SnapcastRpcWrapper:

    def __init__(self, server_address, server_control_port):
        """
        Create a new instance

        :param:server_address The ip of the snapcast server
        :param:listener a SnapcastRpcListener listener
        """
        logging.debug("Initializing SnapcastRpcWrapper")
        self.server_address = server_address
        self.server_control_port = server_control_port
        self.client_id = self.get_client_id()
        self.verify_srver_rpc_version()
        logging.debug("Initialized SnapcastRpcWrapper")

    def get_server_status(self):
        logging.info("Getting snapserver clients")
        payload = \
            {"id": REQ_TAG_GET_SERVER_STATUS,
             "jsonrpc": "2.0",
             "method": "Server.GetStatus",
             }
        return self.call_snapserver_jsonrcp(payload)

    def get_status(self):
        logging.info("Getting snapclient status")
        payload = \
            {"id": REQ_TAG_GET_STATUS,
             "jsonrpc": "2.0",
             "method": "Client.GetStatus",
             "params": {"id": self.client_id}
             }
        return self.call_snapserver_jsonrcp(payload)

    def unmute(self):
        logging.info("Unmuting snapclient")
        self.set_muted(False)

    def mute(self):
        logging.info("Muting snapclient")
        self.set_muted(True)

    def set_muted(self, is_muted):
        logging.debug("Setting snapclient mute to " + str(is_muted))
        payload = \
            {"id": REQ_TAG_SET_MUTE,
             "jsonrpc": "2.0",
             "method": "Client.SetVolume",
             "params":
                 {"id": self.client_id,
                  "volume": {"muted": is_muted}}}
        self.call_snapserver_jsonrcp(payload)

    def set_volume(self, volume_level):
        logging.info("Setting snapclient volume level to " + str(volume_level))
        volume_level = min(volume_level, 100)
        volume_level = max(volume_level, 0)
        payload = \
            {"id": REQ_TAG_SET_VOLUME,
             "jsonrpc": "2.0",
             "method": "Client.SetVolume",
             "params":
                 {"id": self.client_id,
                  "volume": {"percent": volume_level}}}
        self.call_snapserver_jsonrcp(payload)

    def set_name(self, name):
        logging.info("Setting snapclient name to " + name)
        payload = \
            {"id": REQ_TAG_SET_NAME,
             "jsonrpc": "2.0",
             "method": "Client.SetName",
             "params": {"id": self.client_id,
                        "name": name}
             }
        self.call_snapserver_jsonrcp(payload)

    def set_latency(self, latency):
        logging.info("Setting snapclient latency to " + latency)
        payload = \
            {"id": REQ_TAG_SET_LATENCY,
             "jsonrpc": "2.0",
             "method": "Client.SetName",
             "params": {"id": self.client_id,
                        "latency": latency}
             }
        self.call_snapserver_jsonrcp(payload)

    def verify_srver_rpc_version(self):
        payload = {"id": REQ_TAG_GET_SERVER_RPC_VERSION,
                   "jsonrpc": "2.0",
                   "method": "Server.GetRPCVersion"}
        result = self.call_snapserver_jsonrcp(payload)
        # Result: {"major":2,"minor":0,"patch":0}
        logging.info(f"Snapserver RPC version is {result['major']}.{result['minor']}.{result['major']}")
        if result['major'] != 2:
            logging.warning("Snapserver uses a JsonRPC version different from v2")
            logging.warning("Snapserver RPC calls might cause unexpected behaviour")
            logging.warning("Update Snapserver to resolve this")

    def call_snapserver_jsonrcp(self, payload_data):
        logging.debug("Sending JsonRPC call to Snapserver at " + self.server_address)
        response = requests.post('http://' + self.server_address + ":" + str(self.server_control_port) +"/jsonrpc", json=payload_data)
        logging.debug("JsonRCP response: " + response.text)
        return response.json()['result']

    def get_client_id(self):
        logging.info("Finding MAC address of active interface to use as snapclient id")
        addresses = list()
        for interface in listdir("/sys/class/net/"):
            if interface == "lo":
                continue
            try:
                status = open('/sys/class/net/' + interface + '/operstate').readline()
                logging.info(f"Status for interface {interface}: {status.strip()}")
                if status == "down":
                    continue
                mac = open('/sys/class/net/' + interface + '/address').readline()
                logging.info(f"MAC address for interface {interface}: {mac[0:17]}")
                addresses.append(mac[0:17])
            except:
                pass

        if len(addresses) == 0:
            logging.critical("Failed to find MAC address of active network adapter")
            exit(1)
        elif len(addresses) == 1:
            logging.info("Single MAC address: " + addresses[0])
            return addresses[0]
        else:
            logging.info("Multiple MAC addresses, determining id")
            snapcast_clients = dict()
            response = self.get_server_status()
            for group in response['server']['groups']:
                for client in group['clients']:
                    if not client['connected']:
                        logging.info("Client " + client['id'] + " is currently disconnected"
                                     + " (was connected to " + group['stream_id'] + ")")
                        continue
                    logging.info(
                        "Client " + client['id'] + " is connected to stream " + group['stream_id'])
                    snapcast_clients[client['id']] = group['stream_id']

            for address in addresses:
                if address in snapcast_clients.keys():
                    logging.info("Found mac address registered in snapserver: " + address)
                    return address
