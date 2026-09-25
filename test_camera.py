"""Wake up, save a camera frame to camera_awake.jpg, then go back to sleep."""

import sys
import time

from reachy_mini import ReachyMini

HOST = sys.argv[1] if len(sys.argv) > 1 else "localhost"  # 127.0.0.2 = mini-2, 127.0.0.3 = mini-3

with ReachyMini(host=HOST, connection_mode="network", timeout=15) as mini:
    mini.wake_up()
    time.sleep(2.5)
    jpg = None
    for _ in range(20):
        jpg = mini.media.get_frame_jpeg()
        if jpg:
            break
        time.sleep(0.5)
    time.sleep(1.5)
    jpg = mini.media.get_frame_jpeg() or jpg
    with open("camera_awake.jpg", "wb") as f:
        f.write(jpg)
    frame = mini.media.get_frame()
    print("mean brightness:", None if frame is None else round(float(frame.mean()), 1))
    mini.goto_sleep()
