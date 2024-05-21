import av
import numpy as np
import json
from collections import deque
from threading import Thread, Lock
from typing import List, Union
from .logger import TelloLogger

class TelloException(Exception):
    pass


class BackgroundFrameRead:
    """
    This class read frames using PyAV in background. Use
    backgroundFrameRead.frame to get the current frame.
    """

    def __init__(self, address, with_queue = False, maxsize = 32) -> None:
        self.address = address
        self.lock = Lock()
        self.frame = np.zeros([300, 400, 3], dtype=np.uint8)
        self.frames = deque([], maxsize)
        self.with_queue = with_queue

        # Try grabbing frame with PyAV
        # According to issue #90 the decoder might need some time
        # https://github.com/damiafuentes/DJITelloPy/issues/90#issuecomment-855458905
        try:
            TelloLogger.debug('trying to grab video frames...')
            self.container = av.open(self.address, timeout=(TelloStream.FRAME_GRAB_TIMEOUT, None))
        except av.error.ExitError:
            raise TelloException('Failed to grab video frames from video stream')

        self.stopped = False
        self.worker = Thread(target=self.update_frame, args=(), daemon=True)

    def start(self) -> None:
        """Start the frame update worker
        Internal method, you normally wouldn't call this yourself.
        """
        self.worker.start()

    def update_frame(self) -> None:
        """Thread worker function to retrieve frames using PyAV
        Internal method, you normally wouldn't call this yourself.
        """
        try:
            for frame in self.container.decode(video=0):
                if self.with_queue:
                    self.frames.append(np.array(frame.to_image()))
                else:
                    self.frame = np.array(frame.to_image())

                if self.stopped:
                    self.container.close()
                    break
        except av.error.ExitError:
            raise TelloException('Do not have enough frames for decoding, please try again or increase video fps before get_frame_read()')
    
    def get_queued_frame(self):
        """
        Get a frame from the queue
        """
        with self.lock:
            try:
                return self.frames.popleft()
            except IndexError:
                return None

    @property
    def frame(self):
        """
        Access the frame variable directly
        """
        if self.with_queue:
            return self.get_queued_frame()

        with self.lock:
            return self._frame

    @frame.setter
    def frame(self, value) -> None:
        with self.lock:
            self._frame = value

    def stop(self) -> None:
        """Stop the frame update worker
        Internal method, you normally wouldn't call this yourself.
        """
        self.stopped = True


class TelloStream:
    
    TELLO_MULTICAST_IP = '239.239.239.239'
    DEFAULT_VS_MULTICAST_UDP_PORT = 30000
    VS_MULTICAST_UDP_PORT = DEFAULT_VS_MULTICAST_UDP_PORT

    FRAME_GRAB_TIMEOUT = 5

    def __init__(self, tello_id: str, host: str = TELLO_MULTICAST_IP, vs_port: int = VS_MULTICAST_UDP_PORT, if_ip: Union[str, None] = None) -> None:
        
        self.tello_id: str = tello_id
        self.host: str = host
        self.vs_port: int = vs_port
        self.if_ip: Union[str, None] = if_ip
        self.background_frame_read: BackgroundFrameRead = None

    def get_udp_video_address(self) -> str:
        """Internal method, you normally wouldn't call this youself.
        """
        address_schema = 'udp://@{ip}:{port}?localaddr={if_ip}'
        return address_schema.format(ip=self.host, port=self.vs_port, if_ip=self.if_ip)
    
    def get_frame_read(self, with_queue = False, max_queue_len = 32) -> BackgroundFrameRead:
        """Get the BackgroundFrameRead object from the camera drone. Then, you just need to call
        backgroundFrameRead.frame to get the actual frame received by the drone.
        Returns:
            BackgroundFrameRead
        """
        if self.background_frame_read is None:
            address = self.get_udp_video_address()
            self.background_frame_read = BackgroundFrameRead(address, with_queue, max_queue_len)
            self.background_frame_read.start()
        return self.background_frame_read
    
    def end(self) -> None:
        if self.background_frame_read is not None:
            self.background_frame_read.stop()


class TelloSwarmStream:

    @staticmethod
    def fromJsonFile(path: str, if_ip: str):
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

        return TelloSwarmStream.fromJsonList(definition, if_ip)

    @staticmethod
    def fromJsonList(definition: list, if_ip: str):
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
            tellos.append(TelloStream(tello_id=d['id'], host=d['ip'], vs_port=d['vs_port'], if_ip=if_ip))

        return TelloSwarmStream(tellos)
    
    def __init__(self, streams: List[TelloStream]):
        self.streams = streams

    def get_video_streams(self):
        """Get a list of all video streams of the swarm.

        ```python
        swarm.streamon()

        for ip, stream in swarm.get_video_streams():
            cv2.imshow(ip, stream.frame)
        ```
        """

        return [(stream.tello_id, stream.get_frame_read()) for stream in self.streams]
