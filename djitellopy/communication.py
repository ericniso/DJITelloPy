import socket
from threading import Thread
from .logger import TelloLogger


class TelloCommunication:
    """Handles communication with the Tello drone."""

    CONTROL_UDP_PORT = 8889
    STATE_UDP_PORT = 8890

    def __init__(self, forward_video_stream: bool = False) -> None:
        """Initialize the TelloCommunication object."""

        self.forward_video_stream = forward_video_stream
        self.udp_control_handlers = {}
        self.udp_state_handlers = {}
        self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.state_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.video_stream_socket = {}
        self.video_stream_multicast_destination = {}
        self.control_socket.bind(('', TelloCommunication.CONTROL_UDP_PORT))
        self.state_socket.bind(('', TelloCommunication.STATE_UDP_PORT))

    def send_command(self, command: str, address) -> None:
        """Send a command to the Tello."""

        self.control_socket.sendto(command.encode('utf-8'), address)

    def add_udp_control_handler(self, ip: str, fn) -> None:
        """Add a handler for UDP control data."""

        self.udp_control_handlers[ip] = fn

    def add_udp_state_handler(self, ip: str, fn) -> None:
        """Add a handler for UDP state data."""

        self.udp_state_handlers[ip] = fn

    def add_udp_video_stream_handler(self, iface_ip: str, port: int) -> None:

        if not self.forward_video_stream:
            TelloLogger.warning("Video stream forwarding is disabled. Please enable it by setting forward_video_stream to True.")
            return

        current_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        current_socket.bind(('', port))

        forward_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        multicast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        multicast_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        multicast_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface_ip))

        self.video_stream_socket[port] = {
            "socket": current_socket,
            "forward_socket": forward_socket,
            "multicast_socket": multicast_socket
        }

    def add_video_stream_multicast_destination(self, local_port: int, destination_multicast_ip: str, destination_multicast_port: int) -> None:

        if not self.forward_video_stream:
            TelloLogger.warning("Video stream forwarding is disabled. Please enable it by setting forward_video_stream to True.")
            return

        if local_port not in self.video_stream_multicast_destination:
            self.video_stream_multicast_destination[local_port] = []
        
        self.video_stream_multicast_destination[local_port].append((destination_multicast_ip, destination_multicast_port))

    def remove_video_stream_multicast_destination(self, local_port: int, destination_multicast_ip: str, destination_multicast_port: int) -> None:

        if not self.forward_video_stream:
            TelloLogger.warning("Video stream forwarding is disabled. Please enable it by setting forward_video_stream to True.")
            return
        
        if local_port not in self.video_stream_multicast_destination:
            return

        self.video_stream_multicast_destination[local_port].remove((destination_multicast_ip, destination_multicast_port))

    def start(self) -> None:
        """Start the communication thread."""

        udp_control_thread = Thread(target=self._receive_control_data)
        udp_control_thread.daemon = True
        udp_state_thread = Thread(target=self._receive_state_data)
        udp_state_thread.daemon = True

        if self.forward_video_stream is True:
            for port in self.video_stream_socket:
                current_thread = Thread(target=self._receive_video_stream_data, args=(port,))
                current_thread.daemon = True
                current_thread.start()

        udp_control_thread.start()
        udp_state_thread.start()

    def _receive_control_data(self) -> None:
        """Receive control data from the Tello."""

        while True:
            try:
                data, address = self.control_socket.recvfrom(1024)
                if address[0] in self.udp_control_handlers:
                    self.udp_control_handlers[address[0]](data, address)
            except Exception as e:
                TelloLogger.error(e)

    def _receive_state_data(self) -> None:
        """Receive state data from the Tello."""

        while True:
            try:
                data, address = self.state_socket.recvfrom(1024)
                if address[0] in self.udp_state_handlers:
                    self.udp_state_handlers[address[0]](data, address)
            except Exception as e:
                TelloLogger.error(e)

    def _receive_video_stream_data(self, port: int) -> None:
        """Receive video stream data from the Tello."""

        while True:
            try:
                current_socket = self.video_stream_socket[port]["socket"]
                data, _ = current_socket.recvfrom(2048)

                if port in self.video_stream_multicast_destination and self.video_stream_multicast_destination[port] is not None:
                    multicast_socket = self.video_stream_socket[port]["multicast_socket"]
                    for dest_ip, dest_port in self.video_stream_multicast_destination[port]:
                        multicast_socket.sendto(data, (dest_ip, dest_port))
            except Exception as e:
                TelloLogger.error(e)
