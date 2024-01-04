"""Library for controlling multiple DJI Ryze Tello drones.
"""

import json

from threading import Thread, Barrier
from queue import Queue
from typing import List, Callable

from .logger import TELLO_LOGGER
from .communication import TelloCommunication
from .tello import Tello, TelloException
from .enforce_types import enforce_types


@enforce_types
class TelloSwarm:
    """Swarm library for controlling multiple Tellos simultaneously
    """

    tellos: List[Tello]
    barrier: Barrier
    funcBarier: Barrier
    funcQueues: List[Queue]
    threads: List[Thread]

    @staticmethod
    def fromJsonFile(path: str):
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

        return TelloSwarm.fromJsonList(definition)

    @staticmethod
    def fromJsonList(definition: list):
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
            tellos.append(Tello(host=d['ip'], vs_udp=d['vs_port']))

        return TelloSwarm(tellos)

    @staticmethod
    def fromFile(path: str):
        """Create TelloSwarm from file. The file should contain one IP address per line.

        Arguments:
            path: path to the file
        """
        with open(path, 'r') as fd:
            ips = fd.readlines()

        return TelloSwarm.fromIps(ips)

    @staticmethod
    def fromIps(ips: list):
        """Create TelloSwarm from a list of IP addresses.

        Arguments:
            ips: list of IP Addresses
        """
        if not ips:
            raise TelloException("No ips provided")

        tellos = []
        for ip in ips:
            tellos.append(Tello(ip.strip()))

        return TelloSwarm(tellos)

    def __init__(self, tellos: List[Tello]):
        """Initialize a TelloSwarm instance

        Arguments:
            tellos: list of [Tello][tello] instances
        """
        self.communication = TelloCommunication()
        self.tellos = tellos

        for i, tello in enumerate(self.tellos):
            self.communication.add_udp_control_handler(tello.address[0], tello.udp_control_receiver)
            self.communication.add_udp_state_handler(tello.address[0], tello.udp_state_receiver)
            tello.set_send_command_fn(self.communication.send_command)

        self.barrier = Barrier(len(tellos))
        self.funcBarrier = Barrier(len(tellos) + 1)
        self.funcQueues = [Queue() for tello in tellos]

        def worker(i):
            queue = self.funcQueues[i]
            tello = self.tellos[i]

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

    def start(self):
        """Start the communication threads."""
        self.communication.start()

    def sequential(self, func: Callable[[int, Tello], None]):
        """Call `func` for each tello sequentially. The function retrieves
        two arguments: The index `i` of the current drone and `tello` the
        current [Tello][tello] instance.

        ```python
        swarm.parallel(lambda i, tello: tello.land())
        ```
        """

        for i, tello in enumerate(self.tellos):
            func(i, tello)

    def parallel(self, func: Callable[[int, Tello], None]):
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

    def sync(self, timeout: float = None):
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
    
    def get_video_streams(self):
        """Get a list of all video streams of the swarm.

        ```python
        swarm.streamon()

        for ip, stream in swarm.get_video_streams():
            cv2.imshow(ip, stream.frame)
        ```
        """

        return [(tello.address[0], tello.get_frame_read()) for tello in self.tellos]

    def by_ip(self, ip: str):
        """Get a tello by its IP address."""

        tello_found = None
        for tello in self.tellos:
            if tello.address[0] == ip:
                tello_found = tello
                break
        
        return tello_found


    def __getattr__(self, attr):
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
        return iter(self.tellos)

    def __len__(self):
        """Return the amount of tellos in the swarm

        ```python
        print("Tello count: {}".format(len(swarm)))
        ```
        """
        return len(self.tellos)
