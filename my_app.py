"""My Reachy Mini app - start here.

run.bat connects to the robot, wakes it up, opens the check page and then runs
this app. Put your code in run(). When you press Quit on the check page (or
Ctrl+C), stop_event is set: return from run() soon after that.

This is the standard Reachy Mini SDK app format (ReachyMiniApp), so the same
code can later run directly on the robot.

Useful calls (see examples/all_features_app.py for all of them):

    reachy_mini.goto_target(head=create_head_pose(pitch=15), duration=1.0)  # move the head
    reachy_mini.goto_target(antennas=np.deg2rad([30, -30]), duration=0.5)   # move the antennas
    frame = reachy_mini.media.get_frame()           # robot camera, BGR numpy array
    reachy_mini.media.play_sound("dance1.wav")      # built-in sound file
    reachy_mini.media.start_recording()             # robot microphone ...
    chunk = reachy_mini.media.get_audio_sample()    # ... float32 (n, 2) at 16 kHz, or None
"""

import threading

import numpy as np
from reachy_mini import ReachyMini, ReachyMiniApp
from reachy_mini.utils import create_head_pose


class MyApp(ReachyMiniApp):
    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        # Example: look left and right until Quit is pressed. Replace it with your own code.
        while not stop_event.is_set():
            reachy_mini.goto_target(head=create_head_pose(yaw=20), antennas=np.deg2rad([20, -20]), duration=1.0)
            reachy_mini.goto_target(head=create_head_pose(yaw=-20), antennas=np.deg2rad([-20, 20]), duration=1.0)
        reachy_mini.goto_target(head=create_head_pose(), antennas=[0.0, 0.0], duration=1.0)
