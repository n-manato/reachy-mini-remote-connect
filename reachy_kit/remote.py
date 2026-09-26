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
import time
import urllib.request
from typing import Optional

import numpy as np
from reachy_mini import ReachyMini

from .tunnel import MIC_PORT, ROBOT_CAMERA_PORT, SPEAKER_PORT

# The SDK looks for a local Reachy audio device, which this PC never has.
logging.getLogger("reachy_mini.media.audio_control_utils").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 2
DEFAULT_CAMERA_SIZE = (640, 360)  # must match the robot-camera stream (robot_config "webcam")


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
    """Play a built-in sound (e.g. "wake_up.wav") on the robot's speaker.

    Like the SDK, a failure is only logged: wake_up()/goto_sleep() play a sound
    before moving, and a missing sound must not keep the robot from moving.
    """
    try:
        api(host, "media/play_sound", {"file": sound_file})
    except Exception as e:  # HTTPError (e.g. 503 backend not ready), URLError, timeout
        logger.warning("play_sound(%s) failed: %s", sound_file, e)


def jpeg_size(jpg: bytes) -> Optional[tuple[int, int]]:
    """(width, height) from a JPEG's SOF header, without decoding it."""
    i = 2
    while i + 9 < len(jpg):
        if jpg[i] != 0xFF:
            return None
        marker, seg = jpg[i + 1], int.from_bytes(jpg[i + 2:i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(jpg[i + 7:i + 9], "big"), int.from_bytes(jpg[i + 5:i + 7], "big")
        i += 2 + seg
    return None


class TunnelCamera:
    """Camera info for the robot-camera stream, so SDK helpers like look_at_image() work.

    The daemon hands out its default-resolution feed (1280x720 on the wireless
    robot) and the stream scales it down, so the intrinsics are the SDK's
    calibration for the size of the frames actually received.
    """

    def __init__(self, specs_name: str, media: "TunnelMedia", fallback_size: tuple[int, int]) -> None:
        from reachy_mini.media.camera_constants import get_camera_specs_by_name

        self.camera_specs = get_camera_specs_by_name(specs_name)
        self.D = self.camera_specs.D
        self._media = media
        self._fallback_size = fallback_size

    @property
    def resolution(self) -> tuple[int, int]:
        # The stream may have been started by someone else at another size.
        return self._media.frame_size or self._fallback_size

    @property
    def K(self) -> np.ndarray:
        from reachy_mini.media.camera_utils import intrinsics_for_size

        crop_scale = self.camera_specs.default_resolution.value[3]
        return intrinsics_for_size(self.camera_specs.K, crop_scale, self.resolution)


class TunnelMedia:
    """Drop-in for the SDK's MediaManager, carried over the SSH tunnel."""

    STALE_AFTER = 3.0  # s without a new frame -> the stream is down, report None

    def __init__(self, host: str = "127.0.0.1") -> None:
        self.host = host
        self.camera: Optional[TunnelCamera] = None  # set by TunnelReachyMini
        self.frame_size: Optional[tuple[int, int]] = None  # of the frames actually received
        # camera: one persistent MJPEG reader keeps the latest frame
        self._cam_lock = threading.Condition()
        self._cam_jpeg: Optional[bytes] = None
        self._cam_time = 0.0
        self._cam_thread: Optional[threading.Thread] = None
        self._cam_stop = threading.Event()
        # microphone
        self._mic_lock = threading.Lock()
        self._mic_recording = False
        self._mic_resp = None
        self._mic_thread: Optional[threading.Thread] = None
        self._mic_queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=250)  # ~5 s
        self._mic_retry_at = 0.0
        self._mic_reconnecting = False
        # speaker
        self._speaker: Optional[socket.socket] = None

    # ---- camera -------------------------------------------------------
    def _read_camera(self) -> None:
        url = f"http://{self.host}:{ROBOT_CAMERA_PORT}/stream"
        while not self._cam_stop.is_set():
            try:
                with urllib.request.urlopen(url, timeout=10) as r:
                    while not self._cam_stop.is_set():
                        line = r.readline()
                        if not line:
                            break
                        if not line.lower().startswith(b"content-length:"):
                            continue
                        length = int(line.split(b":", 1)[1])
                        while r.readline() not in (b"\r\n", b"\n", b""):
                            pass
                        jpg = r.read(length)
                        with self._cam_lock:
                            self._cam_jpeg, self._cam_time = jpg, time.monotonic()
                            self.frame_size = jpeg_size(jpg) or self.frame_size
                            self._cam_lock.notify_all()
            except (OSError, ValueError):
                pass
            with self._cam_lock:
                self._cam_jpeg = None  # never hand out a frozen frame as if it were live
            self._cam_stop.wait(1)  # stream dropped: reconnect

    def get_frame_jpeg(self, timeout: float = 5.0) -> Optional[bytes]:
        """Latest robot camera frame as JPEG bytes, or None if the stream is down.

        Waits up to `timeout` for the first frame after (re)connecting.
        """
        with self._cam_lock:  # one reader, even if several threads ask at once
            if self._cam_thread is None or not self._cam_thread.is_alive():
                self._cam_stop.clear()
                self._cam_thread = threading.Thread(target=self._read_camera, daemon=True)
                self._cam_thread.start()

            def fresh() -> bool:
                return self._cam_jpeg is not None and time.monotonic() - self._cam_time < self.STALE_AFTER

            self._cam_lock.wait_for(fresh, timeout=timeout)
            return self._cam_jpeg if fresh() else None

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
        try:
            api(self.host, "media/stop_sound", {})
        except Exception as e:
            logger.warning("stop_sound failed: %s", e)

    # ---- microphone ---------------------------------------------------
    def get_input_audio_samplerate(self) -> int:
        return SAMPLE_RATE

    def get_input_channels(self) -> int:
        return CHANNELS

    def start_recording(self) -> None:
        with self._mic_lock:
            self._mic_recording = True
            self._start_mic_reader()

    def _start_mic_reader(self) -> None:
        """(Re)start the reader thread if it is not running. Call with _mic_lock held."""
        if self._mic_thread is not None and self._mic_thread.is_alive():
            return
        if self._mic_resp is not None:
            self._mic_resp.close()
        resp = urllib.request.urlopen(f"http://{self.host}:{MIC_PORT}/mic", timeout=10)
        self._mic_resp = resp
        # The thread gets its own response and queue, so an old thread that is
        # still finishing can never write into a newer recording.
        self._mic_thread = threading.Thread(target=self._read_mic, args=(resp, self._mic_queue), daemon=True)
        self._mic_thread.start()

    @staticmethod
    def _read_mic(resp, out: "queue.Queue[np.ndarray]") -> None:
        frame_bytes = 2 * CHANNELS
        rest = b""
        try:
            while True:
                data = resp.read1(8192)
                if not data:
                    break
                data = rest + data
                usable = len(data) - len(data) % frame_bytes
                rest = data[usable:]
                pcm = np.frombuffer(data[:usable], "<i2").reshape(-1, CHANNELS)
                chunk = pcm.astype(np.float32) / 32768.0
                if out.full():
                    try:
                        out.get_nowait()  # drop the oldest, like a live source
                    except queue.Empty:
                        pass
                out.put_nowait(chunk)
        except (OSError, ValueError):
            pass

    def get_audio_sample(self) -> Optional[np.ndarray]:
        """Next microphone chunk, float32 of shape (n, 2), or None if nothing new."""
        try:
            return self._mic_queue.get_nowait()
        except queue.Empty:
            pass
        # Reader died (stream stalled, robot-side error): reconnect in the background,
        # at most once a second. Never wait for the lock: a reconnect in progress
        # holds it while it talks to the robot, and this poll must not block the app.
        if not self._mic_lock.acquire(blocking=False):
            return None
        try:
            dead = self._mic_thread is None or not self._mic_thread.is_alive()
            due = time.monotonic() >= self._mic_retry_at
            if self._mic_recording and dead and due and not self._mic_reconnecting:
                self._mic_retry_at = time.monotonic() + 1.0
                self._mic_reconnecting = True
                threading.Thread(target=self._reconnect_mic, daemon=True).start()
        finally:
            self._mic_lock.release()
        return None

    def _reconnect_mic(self) -> None:
        try:
            with self._mic_lock:
                if self._mic_recording:
                    self._start_mic_reader()
        except OSError as e:
            logger.warning("microphone reconnect failed: %s", e)
        finally:
            self._mic_reconnecting = False

    def stop_recording(self) -> None:
        with self._mic_lock:
            self._mic_recording = False
            if self._mic_resp is not None:
                self._mic_resp.close()
            if self._mic_thread is not None:
                self._mic_thread.join(timeout=2)
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

    # ---- not available over the VPN ------------------------------------
    def enable_wobbling(self, *args, **kwargs) -> None:
        raise RuntimeError("Speech wobbling needs the SDK's WebRTC audio, which does not work over the VPN.")

    def disable_wobbling(self) -> None:
        pass

    def get_DoA(self) -> None:
        """Direction of arrival is not available over the VPN (the SDK also returns None without it)."""
        return None

    def close(self) -> None:
        self._cam_stop.set()
        self.stop_recording()
        self.stop_playing()


class TunnelReachyMini(ReachyMini):
    """ReachyMini for use over the tunnel: motion via the SDK, media via TunnelMedia."""

    def __init__(self, host: str = "127.0.0.1", camera_size: tuple[int, int] = DEFAULT_CAMERA_SIZE,
                 **kwargs) -> None:
        kwargs.setdefault("connection_mode", "network")
        kwargs.setdefault("timeout", 15)
        kwargs["media_backend"] = "no_media"  # skip WebRTC, it cannot pass the VPN
        super().__init__(host=host, **kwargs)
        # The SDK has just received a status; waiting for the next one costs up to 1 s.
        specs_name = getattr(self.client.get_status(wait=False), "camera_specs_name", "") or "wireless"
        media = TunnelMedia(host)
        media.camera = TunnelCamera(specs_name, media, camera_size)
        self.media_manager = media
        self._owner: Optional[threading.Thread] = None
        for name in ("send_command", "send_task_request"):  # every motion goes through these
            setattr(self.client, name, self._guarded(getattr(self.client, name)))

    def _guarded(self, send):
        def guarded(*args, **kwargs):
            if self._owner is not None and threading.current_thread() is not self._owner:
                raise RuntimeError("The robot was taken back after Quit; this app can no longer move it.")
            return send(*args, **kwargs)
        return guarded

    def take_control(self) -> None:
        """From now on only the calling thread may send commands (e.g. an app that ignores Quit)."""
        self._owner = threading.current_thread()

    def release_media(self) -> None:
        # "no_media" normally asks the daemon to release the camera and audio,
        # which would stop the robot-camera stream and the audio bridge.
        pass


def connect(host: str = "127.0.0.1", **kwargs) -> TunnelReachyMini:
    return TunnelReachyMini(host, **kwargs)
