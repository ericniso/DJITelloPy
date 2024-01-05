import socket
from threading import Thread
from .enforce_types import enforce_types
from .logger import TELLO_LOGGER


@enforce_types
class TelloCommunication:
    """Handles communication with the Tello drone."""

    CONTROL_UDP_PORT = 8889
    STATE_UDP_PORT = 8890

    def __init__(self):
        """Initialize the TelloCommunication object."""

        self.udp_control_handlers = {}
        self.udp_state_handlers = {}
        self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.state_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.video_stream_socket = {}
        self.control_socket.bind(('', TelloCommunication.CONTROL_UDP_PORT))
        self.state_socket.bind(('', TelloCommunication.STATE_UDP_PORT))

    def send_command(self, command: str, address):
        """Send a command to the Tello."""

        self.control_socket.sendto(command.encode('utf-8'), address)

    def add_udp_control_handler(self, ip: str, fn):
        """Add a handler for UDP control data."""

        self.udp_control_handlers[ip] = fn

    def add_udp_state_handler(self, ip: str, fn):
        """Add a handler for UDP state data."""

        self.udp_state_handlers[ip] = fn

    def add_udp_video_stream_multicast(self, port: int, multicast_address: str, multicast_port: int):

        current_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        current_socket.bind(('', port))

        multicast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        multicast_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)

        self.video_stream_socket[port] = {
            "socket": current_socket,
            "multicast_address": multicast_address,
            "multicast_port": multicast_port,
            "multicast_socket": multicast_socket,
        }

    def start(self):
        """Start the communication thread."""

        udp_control_thread = Thread(target=self._receive_control_data)
        udp_control_thread.daemon = True
        udp_state_thread = Thread(target=self._receive_state_data)
        udp_state_thread.daemon = True

        for port in self.video_stream_socket:
            current_thread = Thread(target=self._receive_video_stream_data, args=(port,))
            current_thread.daemon = True
            current_thread.start()

        udp_control_thread.start()
        udp_state_thread.start()

    def _receive_control_data(self):
        """Receive control data from the Tello."""

        while True:
            try:
                data, address = self.control_socket.recvfrom(1024)
                if address[0] in self.udp_control_handlers:
                    self.udp_control_handlers[address[0]](data, address)
            except Exception as e:
                TELLO_LOGGER.error(e)

    def _receive_state_data(self):
        """Receive state data from the Tello."""

        while True:
            try:
                data, address = self.state_socket.recvfrom(1024)
                if address[0] in self.udp_state_handlers:
                    self.udp_state_handlers[address[0]](data, address)
            except Exception as e:
                TELLO_LOGGER.error(e)

    def _receive_video_stream_data(self, port: int):
        """Receive video stream data from the Tello."""

        while True:
            try:
                current_socket = self.video_stream_socket[port]["socket"]
                data, _ = current_socket.recvfrom(1024)

                current_multicast_address = self.video_stream_socket[port]["multicast_address"]
                current_multicast_port = self.video_stream_socket[port]["multicast_port"]
                
                multicast_socket = self.video_stream_socket[port]["multicast_socket"]
                multicast_socket.sendto(data, (current_multicast_address, current_multicast_port))
            except Exception as e:
                TELLO_LOGGER.error(e)
