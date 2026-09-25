"""Use the Reachy Mini SDK through the SSH tunnel (run.bat / reachy_kit.tunnel).

Over the campus VPN only TCP through the tunnel works. The SDK's camera and
audio use WebRTC (signaling to the robot's lab Wi-Fi address, media over UDP),
so neither gets through. connect() returns a ReachyMini whose `media` is
replaced by TunnelMedia, which offers the same calls over the tunnel:

    camera      get_frame(), get_frame_jpeg()          <- MJPEG stream, port 8091
    microphone  start_recording(), get_audio_sample()  <- raw PCM, port 8092
    speaker     start_playing(), push_audio_sample()   -> raw PCM, port 8093
    sounds      play_sound("wake_up.wav"), stop_sound() -> daemon HTTP API

    from reachy_kit import connect

    with connect() as mini:                   # host defaults to 127.0.0.1
        mini.wake_up()                        # head up + start-up sound
        frame = mini.media.get_frame()        # BGR numpy array (needs opencv)
"""

import json
import logging
import queue
import socket
import threading
import urllib.request
from typing import Optional

import numpy as np
from reachy_mini import ReachyMini

from .tunnel import MIC_PORT, ROBOT_CAMERA_PORT, SPEAKER_PORT

# The SDK looks for a local Reachy audio device, which this PC never has.
logging.getLogger("reachy_mini.media.audio_control_utils").setLevel(logging.CRITICAL)

SAMPLE_RATE = 16000
CHANNELS = 2


def api(host: str, path: str, body: Optional[dict] = None, timeout: float = 10) -> dict:
    """POST (with body) or GET a daemon endpoint through the tunnel."""
    req = urllib.request.Request(
        f"http://{host}:8000/api/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def play_sound(host: str, sound_file: str) -> None:
    """Play a built-in sound (e.g. "wake_up.wav") on the robot's speaker."""
    api(host, "media/play_sound", {"file": sound_file})


class TunnelMedia:
    """Drop-in for the SDK's MediaManager, carried over the SSH tunnel."""

    def __init__(self, host: str = "127.0.0.1") -> None:
        self.host = host
        self._mic_resp = None
        self._mic_thread: Optional[threading.Thread] = None
        self._mic_queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=250)  # ~5 s of 20 ms chunks
        self._speaker: Optional[socket.socket] = None

    # ---- camera -------------------------------------------------------
    def get_frame_jpeg(self) -> Optional[bytes]:
        try:
            with urllib.request.urlopen(
                f"http://{self.host}:{ROBOT_CAMERA_PORT}/snapshot.jpg", timeout=10
            ) as r:
                return r.read()
        except OSError:
            return None

    def get_frame(self) -> Optional[np.ndarray]:
        """Latest robot camera frame as a BGR array, like the SDK (requires opencv)."""
        jpg = self.get_frame_jpeg()
        if jpg is None:
            return None
        try:
            import cv2
        except ImportError as e:
            raise ImportError("get_frame() needs opencv: pip install opencv-python-headless") from e
        return cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)

    # ---- sound files --------------------------------------------------
    def play_sound(self, sound_file: str) -> None:
        play_sound(self.host, sound_file)

    def stop_sound(self) -> None:
        api(self.host, "media/stop_sound", {})

    # ---- microphone ---------------------------------------------------
    def get_input_audio_samplerate(self) -> int:
        return SAMPLE_RATE

    def get_input_channels(self) -> int:
        return CHANNELS

    def start_recording(self) -> None:
        if self._mic_thread:
            return
        self._mic_resp = urllib.request.urlopen(f"http://{self.host}:{MIC_PORT}/mic", timeout=10)
        self._mic_thread = threading.Thread(target=self._read_mic, daemon=True)
        self._mic_thread.start()

    def _read_mic(self) -> None:
        frame_bytes = 2 * CHANNELS
        rest = b""
        try:
            while True:
                data = self._mic_resp.read1(8192)
                if not data:
                    break
                data = rest + data
                usable = len(data) - len(data) % frame_bytes
                rest = data[usable:]
                pcm = np.frombuffer(data[:usable], "<i2").reshape(-1, CHANNELS)
                chunk = pcm.astype(np.float32) / 32768.0
                if self._mic_queue.full():
                    self._mic_queue.get_nowait()  # drop the oldest, like a live source
                self._mic_queue.put_nowait(chunk)
        except (OSError, ValueError):
            pass

    def get_audio_sample(self) -> Optional[np.ndarray]:
        """Next microphone chunk, float32 of shape (n, 2), or None if nothing new."""
        try:
            return self._mic_queue.get_nowait()
        except queue.Empty:
            return None

    def stop_recording(self) -> None:
        if self._mic_resp:
            self._mic_resp.close()
        self._mic_resp = self._mic_thread = None
        self._mic_queue = queue.Queue(maxsize=250)

    # ---- speaker ------------------------------------------------------
    def get_output_audio_samplerate(self) -> int:
        return SAMPLE_RATE

    def get_output_channels(self) -> int:
        return CHANNELS

    def start_playing(self) -> None:
        if self._speaker is None:
            self._speaker = socket.create_connection((self.host, SPEAKER_PORT), timeout=10)

    def push_audio_sample(self, data: np.ndarray) -> None:
        """Play float32 samples (-1..1), mono (n,) or (n, channels), at 16 kHz."""
        if self._speaker is None:
            self.start_playing()
        data = np.asarray(data, dtype=np.float32)
        if data.ndim == 1:
            data = data[:, None]
        if data.shape[1] != CHANNELS:
            data = np.repeat(data[:, :1], CHANNELS, axis=1)
        pcm = (np.clip(data, -1.0, 1.0) * 32767).astype("<i2")
        self._speaker.sendall(pcm.tobytes())

    def stop_playing(self) -> None:
        if self._speaker is not None:
            self._speaker.close()
            self._speaker = None

    def close(self) -> None:
        self.stop_recording()
        self.stop_playing()


class TunnelReachyMini(ReachyMini):
    """ReachyMini for use over the tunnel: motion via the SDK, media via TunnelMedia."""

    def __init__(self, host: str = "127.0.0.1", **kwargs) -> None:
        kwargs.setdefault("connection_mode", "network")
        kwargs.setdefault("timeout", 15)
        kwargs["media_backend"] = "no_media"  # skip WebRTC, it cannot pass the VPN
        super().__init__(host=host, **kwargs)
        self.media_manager = TunnelMedia(host)

    def release_media(self) -> None:
        # "no_media" normally asks the daemon to release the camera and audio,
        # which would stop the robot-camera stream and the audio bridge.
        pass


def connect(host: str = "127.0.0.1", **kwargs) -> TunnelReachyMini:
    return TunnelReachyMini(host, **kwargs)
