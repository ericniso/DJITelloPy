"""Library for controlling multiple DJI Ryze Tello drones.
"""

import json
import time
from threading import Thread, Barrier
from queue import Queue
from typing import List, Callable, Union, Dict
from .logger import TelloLogger
from .communication import TelloCommunication
from .tello import Tello, TelloException


class TelloSwarm:
    """Swarm library for controlling multiple Tellos simultaneously
    """

    CHECK_REACHABLE_TELLOS_INTERVAL: int = 2
    TRY_RECONNECT_TELLOS_INTERVAL: int = 2

    @staticmethod
    def fromJsonFile(path: str, iface_ip: str, forward_video_stream: bool = False, tello_connected_handler: Callable[[Tello], None] = None) -> 'TelloSwarm':
        """Create TelloSwarm from a json file. The file should contain a list of IP addresses.

        The json structure should look like this:
            
            ```json
            [
                {
                    "ip": "<IP_ADDRESS>",
                    "vs_port": <VIDEO_STREAM_PORT>
                }
            ]
            ```

        Arguments:
            path: path to the json file
        """

        with open(path, 'r', encoding='utf-8') as fd:
            definition = json.load(fd)

        return TelloSwarm.fromJsonList(definition, iface_ip, forward_video_stream, tello_connected_handler)

    @staticmethod
    def fromJsonList(definition: list, iface_ip: str, forward_video_stream: bool = False, tello_connected_handler: Callable[[Tello], None] = None) -> 'TelloSwarm':
        """Create TelloSwarm from a json object.

        The json structure should look like this:
            
            ```json
            [
                {
                    "ip": "<IP_ADDRESS>",
                    "vs_port": <VIDEO_STREAM_PORT>
                }
            ]
            ```

        Arguments:
            definition: json object dict
        """

        tellos = []
        for d in definition:
            tellos.append(Tello(tello_id=d['id'], host=d['ip'], vs_port=d['vs_port']))

        return TelloSwarm(definition, tellos, iface_ip, forward_video_stream, tello_connected_handler)

    def __init__(self, definition: List[Dict], tellos: List[Tello], iface_ip: str, forward_video_stream: bool = False, tello_connected_handler: Callable[[Tello], None] = None) -> None:
        """Initialize a TelloSwarm instance

        Arguments:
            tellos: list of [Tello] instances
        """
        self.definition: List[Dict] = definition
        self.connected_tellos: List[Tello] = tellos
        self.unreachable_tellos: List[Tello] = []
        self.iface_ip: str = iface_ip
        self.forward_video_stream: bool = forward_video_stream
        self.tello_connected_handler: Callable[[Tello], None] = tello_connected_handler
        self.communication: TelloCommunication = TelloCommunication(self.forward_video_stream)
        self.reachable_tellos_thread = Thread(target=self._check_reachable_tellos, daemon=True)
        self.try_tellos_reconnect_thread = Thread(target=self._try_tello_reconnect, daemon=True)

        for i, tello in enumerate(self.connected_tellos):
            tello.set_tello_connected_handler(self.tello_connected_handler)
            self.communication.add_udp_control_handler(tello.address[0], tello.udp_control_receiver)
            self.communication.add_udp_state_handler(tello.address[0], tello.udp_state_receiver)
            if self.forward_video_stream:
                self.communication.add_udp_video_stream_handler(self.iface_ip, tello.vs_port)
            tello.set_send_command_fn(self.communication.send_command)

        self.barrier: Barrier = Barrier(len(tellos))
        self.funcBarrier: Barrier = Barrier(len(tellos) + 1)
        self.funcQueues: List[Queue] = [Queue() for tello in tellos]

        def worker(i):
            queue = self.funcQueues[i]
            tello = self.connected_tellos[i]

            while True:
                func = queue.get()
                self.funcBarrier.wait()
                func(i, tello)
                self.funcBarrier.wait()

        self.threads = []
        for i, _ in enumerate(tellos):
            thread = Thread(target=worker, daemon=True, args=(i,))
            thread.start()
            self.threads.append(thread)

    def start(self) -> None:
        """Start the communication threads."""
        self.communication.start()
        self.reachable_tellos_thread.start()
        self.try_tellos_reconnect_thread.start()

    def _check_reachable_tellos(self) -> None:
        while True:
            try:
                for tello in self.connected_tellos:
                    if tello.is_unreachable():
                        self.connected_tellos.remove(tello)
                        self.unreachable_tellos.append(tello)
                        TelloLogger.warning(f"Tello {str(tello)} is unreachable, removing from active list.")
            except Exception as e:
                TelloLogger.error(e)

            time.sleep(TelloSwarm.CHECK_REACHABLE_TELLOS_INTERVAL)

    def _try_tello_reconnect(self,) -> None:
        while True:
            try:
                for tello in self.unreachable_tellos:
                    TelloLogger.info(f"Trying to reconnect to Tello {str(tello)}...")
                    tello.connect()
                    if not tello.is_unreachable():
                        self.connected_tellos.append(tello)
                        self.unreachable_tellos.remove(tello)
                        TelloLogger.info(f"Tello {str(tello)} connected.")
                    else:
                        TelloLogger.warning(f"Reconnection to Tello {str(tello)} failed, retrying in {TelloSwarm.TRY_RECONNECT_TELLOS_INTERVAL} seconds")
            except Exception as e:
                TelloLogger.error(e)

            time.sleep(TelloSwarm.TRY_RECONNECT_TELLOS_INTERVAL)

    def sequential(self, func: Callable[[int, Tello], None]) -> None:
        """Call `func` for each tello sequentially. The function retrieves
        two arguments: The index `i` of the current drone and `tello` the
        current [Tello][tello] instance.

        ```python
        swarm.parallel(lambda i, tello: tello.land())
        ```
        """

        for i, tello in enumerate(self.connected_tellos):
            func(i, tello)

    def parallel(self, func: Callable[[int, Tello], None]) -> None:
        """Call `func` for each tello in parallel. The function retrieves
        two arguments: The index `i` of the current drone and `tello` the
        current [Tello][tello] instance.

        You can use `swarm.sync()` for syncing between threads.

        ```python
        swarm.parallel(lambda i, tello: tello.move_up(50 + i * 10))
        ```
        """

        for queue in self.funcQueues:
            queue.put(func)

        self.funcBarrier.wait()
        self.funcBarrier.wait()

    def sync(self, timeout: float = None) -> None:
        """Sync parallel tello threads. The code continues when all threads
        have called `swarm.sync`.

        ```python
        def doStuff(i, tello):
            tello.move_up(50 + i * 10)
            swarm.sync()

            if i == 2:
                tello.flip_back()
            # make all other drones wait for one to complete its flip
            swarm.sync()

        swarm.parallel(doStuff)
        ```
        """
        return self.barrier.wait(timeout)

    def by_ip(self, ip: str) -> Union[Tello, None]:
        """Get a tello by its IP address."""

        tello_found = None
        for tello in self.connected_tellos:
            if tello.address[0] == ip:
                tello_found = tello
                break
        
        return tello_found

    def add_video_stream_multicast_destination(self, local_port: int, destination_multicast_ip: str, destination_multicast_port: int) -> None:
        """Add a multicast destination for the video stream."""

        if not self.forward_video_stream:
            TelloLogger.warning("Video stream forwarding is disabled. Enable it with `forward_video_stream=True`.")
            return

        self.communication.add_video_stream_multicast_destination(local_port, destination_multicast_ip, destination_multicast_port)

    def remove_video_stream_multicast_destination(self, local_port: int, destination_multicast_ip: str, destination_multicast_port: int) -> None:
        """Remove a destination for the video stream."""

        if not self.forward_video_stream:
            TelloLogger.warning("Video stream forwarding is disabled. Enable it with `forward_video_stream=True`.")
            return

        self.communication.remove_video_stream_multicast_destination(local_port, destination_multicast_ip, destination_multicast_port)

    def __getattr__(self, attr) -> Callable:
        """Call a standard tello function in parallel on all tellos.

        ```python
        swarm.command()
        swarm.takeoff()
        swarm.move_up(50)
        ```
        """
        def callAll(*args, **kwargs):
            self.parallel(lambda i, tello: getattr(tello, attr)(*args, **kwargs))

        return callAll

    def __iter__(self):
        """Iterate over all drones in the swarm.

        ```python
        for tello in swarm:
            print(tello.get_battery())
        ```
        """
        return iter(self.connected_tellos)

    def __len__(self) -> int:
        """Return the amount of tellos in the swarm

        ```python
        print("Tello count: {}".format(len(swarm)))
        ```
        """
        return len(self.connected_tellos)
