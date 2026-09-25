"""Tour of everything a Reachy Mini app can use.

Run it with:  run.bat examples\\all_features_app.py

1. Motion      head, antennas and body
2. Camera      grab a frame, measure its brightness, save it
3. Sound file  play a built-in sound on the robot speaker
4. Speaker     stream a short melody generated in Python
5. Microphone  the antennas follow how loud the room is, until you press Quit

Each step checks stop_event, so Quit on the check page stops the app quickly.
"""

import threading
import time

import cv2
import numpy as np
from reachy_mini import ReachyMini, ReachyMiniApp
from reachy_mini.utils import create_head_pose

SAMPLE_RATE = 16000


class AllFeaturesApp(ReachyMiniApp):
    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        steps = [self.motion, self.camera, self.sound_file, self.speaker, self.microphone]
        for step in steps:
            if stop_event.is_set():
                break
            print(f"--- {step.__name__}")
            step(reachy_mini, stop_event)
        reachy_mini.goto_target(head=create_head_pose(), antennas=[0.0, 0.0], body_yaw=0.0, duration=1.0)

    # 1. Motion ------------------------------------------------------------
    def motion(self, mini: ReachyMini, stop_event: threading.Event) -> None:
        moves = [
            dict(head=create_head_pose(pitch=15)),                 # nod down
            dict(head=create_head_pose(pitch=-10)),                # look up
            dict(head=create_head_pose(yaw=30)),                   # look left
            dict(head=create_head_pose(yaw=-30)),                  # look right
            dict(head=create_head_pose(roll=15)),                  # tilt
            dict(head=create_head_pose(z=10, mm=True)),            # stretch up 10 mm
            dict(head=create_head_pose(), antennas=np.deg2rad([40, -40])),
            dict(antennas=np.deg2rad([-40, 40])),
            dict(antennas=[0.0, 0.0], body_yaw=np.deg2rad(25)),   # turn the body
            dict(body_yaw=np.deg2rad(-25)),
            dict(body_yaw=0.0),
        ]
        for move in moves:
            if stop_event.is_set():
                return
            mini.goto_target(duration=0.8, **move)

    # 2. Camera ------------------------------------------------------------
    def camera(self, mini: ReachyMini, stop_event: threading.Event) -> None:
        frame = mini.media.get_frame()  # BGR numpy array, or None if no frame yet
        if frame is None:
            print("no camera frame")
            return
        brightness = float(frame.mean())
        print(f"camera frame {frame.shape[1]}x{frame.shape[0]}, brightness {brightness:.0f}/255")
        cv2.imwrite("last_frame.jpg", frame)
        print("saved last_frame.jpg")
        # React: nod if the room is bright, shake the head if it is dark.
        if brightness > 80:
            mini.goto_target(head=create_head_pose(pitch=15), duration=0.5)
        else:
            mini.goto_target(head=create_head_pose(yaw=20), duration=0.4)
            mini.goto_target(head=create_head_pose(yaw=-20), duration=0.4)
        mini.goto_target(head=create_head_pose(), duration=0.5)

    # 3. Sound file --------------------------------------------------------
    def sound_file(self, mini: ReachyMini, stop_event: threading.Event) -> None:
        # Built-in files: wake_up.wav, go_sleep.wav, dance1.wav, confused1.wav, impatient1.wav, count.wav
        mini.media.play_sound("dance1.wav")
        stop_event.wait(3)

    # 4. Speaker stream ----------------------------------------------------
    def speaker(self, mini: ReachyMini, stop_event: threading.Event) -> None:
        notes = [523, 587, 659, 698, 784]  # C D E F G
        t = np.arange(int(SAMPLE_RATE * 0.25)) / SAMPLE_RATE
        melody = np.concatenate([0.3 * np.sin(2 * np.pi * hz * t) for hz in notes]).astype(np.float32)
        mini.media.start_playing()
        # Push the whole melody at once: tiny pieces would stutter over the slow VPN.
        mini.media.push_audio_sample(melody)
        stop_event.wait(len(melody) / SAMPLE_RATE + 0.3)  # let it finish playing
        mini.media.stop_playing()

    # 5. Microphone --------------------------------------------------------
    def microphone(self, mini: ReachyMini, stop_event: threading.Event) -> None:
        print("antennas now follow the room's loudness - make some noise, press Quit to stop")
        mini.media.start_recording()
        level, last_move, last_print = 0.0, 0.0, 0.0
        while not stop_event.is_set():
            chunk = mini.media.get_audio_sample()  # float32 (n, 2) or None
            if chunk is None:
                time.sleep(0.01)
                continue
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            level = 0.8 * level + 0.2 * rms  # smooth it
            # Send at most ~10 motion commands per second: over the VPN, a command
            # for every audio chunk floods the connection and it drops.
            if time.time() - last_move < 0.1:
                continue
            last_move = time.time()
            angle = float(np.clip(level * 800, 0, 60))  # louder -> antennas up
            mini.set_target(antennas=np.deg2rad([angle, -angle]))
            if time.time() - last_print > 1:
                print(f"mic level {level:.4f} -> antennas {angle:.0f} deg")
                last_print = time.time()
        mini.media.stop_recording()
