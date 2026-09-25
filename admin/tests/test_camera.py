"""Wake up, save a robot camera frame to camera_awake.jpg, then go back to sleep.

Run reachy_tunnel.py first; the frame comes from the robot-camera MJPEG
stream on port 8091, so this works over the VPN.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))  # repo root

import time
import urllib.request

from reachy_kit.remote import connect
from reachy_kit.tunnel import ROBOT_CAMERA_PORT

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"  # 127.0.0.2 = mini-2, 127.0.0.3 = mini-3

with connect(HOST) as mini:
    mini.enable_motors()
    mini.wake_up()
    time.sleep(2)
    with urllib.request.urlopen(f"http://{HOST}:{ROBOT_CAMERA_PORT}/snapshot.jpg", timeout=10) as r:
        jpg = r.read()
    with open("camera_awake.jpg", "wb") as f:
        f.write(jpg)
    print(f"saved camera_awake.jpg ({len(jpg)} bytes)")
    mini.goto_sleep()
