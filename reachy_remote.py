"""Use the Reachy Mini SDK through the SSH tunnel (reachy_tunnel.py / run.bat).

Over the campus VPN only TCP through the tunnel works. The SDK's camera and
audio use WebRTC, whose signaling goes to the robot's lab Wi-Fi address and
whose media is UDP, so neither gets through. This module connects for motion
only, keeps the daemon's camera running (it feeds the robot-camera stream on
port 8091), and plays sounds through the daemon's HTTP API instead.

    from reachy_remote import connect

    with connect() as mini:          # host defaults to 127.0.0.1
        mini.wake_up()               # head up + start-up sound
        ...
"""

import json
import logging
import urllib.request

from reachy_mini import ReachyMini

# The SDK looks for a local Reachy audio device, which this PC never has.
logging.getLogger("reachy_mini.media.audio_control_utils").setLevel(logging.CRITICAL)


def api(host: str, path: str, body: dict | None = None, timeout: float = 10) -> dict:
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


class TunnelReachyMini(ReachyMini):
    """ReachyMini for use over the tunnel: motion via the SDK, sounds via HTTP."""

    def __init__(self, host: str = "127.0.0.1", **kwargs) -> None:
        kwargs.setdefault("connection_mode", "network")
        kwargs.setdefault("timeout", 15)
        kwargs["media_backend"] = "no_media"
        super().__init__(host=host, **kwargs)
        # wake_up() / goto_sleep() call self.media.play_sound(); route it to the daemon.
        self.media.play_sound = lambda sound_file: play_sound(host, sound_file)

    def release_media(self) -> None:
        # "no_media" normally asks the daemon to release the camera, which would
        # stop the robot-camera stream for everyone. Keep it with the daemon.
        pass


def connect(host: str = "127.0.0.1", **kwargs) -> TunnelReachyMini:
    return TunnelReachyMini(host, **kwargs)
