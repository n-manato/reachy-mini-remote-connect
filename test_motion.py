"""Motion test over the SSH tunnel (run reachy_tunnel.py first)."""

import sys
import time

import numpy as np

from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

HOST = sys.argv[1] if len(sys.argv) > 1 else "localhost"  # 127.0.0.2 = mini-2, 127.0.0.3 = mini-3


def show(mini: ReachyMini, label: str) -> None:
    head = mini.get_current_head_pose()
    ant = mini.get_present_antenna_joint_positions()
    print(f"{label:12s} head_z={head[2, 3] * 1000:6.1f}mm antennas=({ant[0]:+.2f}, {ant[1]:+.2f})")


with ReachyMini(host=HOST, connection_mode="network", media_backend="no_media", timeout=15) as mini:
    show(mini, "start")
    mini.enable_motors()  # motors come up disabled after a robot reboot
    mini.wake_up()
    show(mini, "wake_up")

    mini.goto_target(head=create_head_pose(pitch=15), duration=0.8)
    mini.goto_target(head=create_head_pose(pitch=-10), duration=0.8)
    mini.goto_target(head=create_head_pose(yaw=25), duration=0.8)
    mini.goto_target(head=create_head_pose(yaw=-25), duration=0.8)
    mini.goto_target(head=create_head_pose(z=10, mm=True), duration=0.8)
    show(mini, "head moves")

    mini.goto_target(antennas=np.deg2rad([40, -40]), duration=0.6)
    mini.goto_target(antennas=np.deg2rad([-40, 40]), duration=0.6)
    show(mini, "antennas")

    mini.goto_target(head=create_head_pose(), body_yaw=np.deg2rad(30), duration=1.0)
    mini.goto_target(body_yaw=np.deg2rad(-30), duration=1.0)
    mini.goto_target(head=create_head_pose(), antennas=[0.0, 0.0], body_yaw=0.0, duration=1.0)
    show(mini, "body yaw")

    time.sleep(0.5)
    mini.goto_sleep()
    show(mini, "goto_sleep")
print("motion test done")
