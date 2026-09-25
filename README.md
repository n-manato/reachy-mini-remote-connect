# Reachy Mini starter kit

Build your own app for the lab's Reachy Mini robots from your Windows PC, over the university VPN.
The connection is already handled for you: you write the app in **`my_app.py`** and start it with **`run.bat`**.

`run.bat`:

1. connects to the robot set in `robot_config.json`,
2. wakes the robot up (head up + start-up sound),
3. opens the **check page** in your browser (robot camera, webcam watching the robot, robot microphone),
4. runs your app,
5. when you press **Quit** (or Ctrl+C): stops your app and puts the robot back to sleep.

## Requirements

| | |
|---|---|
| OS | Windows 10 / 11 |
| Python | **3.11 – 3.13, 64-bit** (tested with 3.13). Tick **"Add python.exe to PATH"** when installing. |
| Disk | About 1 GB free |
| VPN | **GlobalProtect**, signed in with **your own** university account (on or off campus) |
| Browser | Any (Edge, Chrome, …) |

## Setup (once)

1. Install Python 3.13 (64-bit) from <https://www.python.org/downloads/> and tick **"Add python.exe to PATH"**.
2. Double-click **`setup.bat`**. It creates a `.venv` folder and installs the Reachy Mini SDK (a few minutes).
3. Open **`robot_config.json`** (created by `setup.bat` from `robot_config.example.json`) and fill in
   the robot's `name`, `ip` and `ssh_password`. **Ask your instructor for these values.**

   ```json
   {
     "name": "reachy-mini-2",
     "ip": "10.0.0.12",
     "ssh_user": "pollen",
     "ssh_password": "ASK-YOUR-INSTRUCTOR",
     "isolated_subnet": "",
     "volume": 100,
     "webcam": {"width": 640, "height": 360, "fps": 8}
   }
   ```

## Run

1. **Connect GlobalProtect** (taskbar → GlobalProtect → Connect) and wait for **Connected**.
2. Double-click **`run.bat`**. Keep the console window open. It shows:
   ```
   Robot: reachy-mini-2 (<robot-ip>)
   Loading app: my_app.py
   Opening SSH tunnel...
   Waking up the robot...
   Check page: http://127.0.0.1:xxxxx/
   Running. Press Ctrl+C or the Quit button to stop.
   Starting app: MyApp (my_app.py)
   ```
3. The **check page** opens in your browser:
   - **Robot camera** – what the robot sees
   - **Webcam** – a camera watching the robot, so you can see what your app does
     (shows "Not connected" if that robot has no webcam)
   - **Listen to robot mic** – hear the room through the robot's microphone
   - **App** – `running`, `finished` or `error (see the console)`
4. Press **Quit** on the page (or Ctrl+C in the console) when you are done.
5. Disconnect GlobalProtect when you no longer need it (while connected, all your internet traffic
   goes through the university VPN and is slower).

To run another app file: `run.bat examples\all_features_app.py`.

## Writing your app

Open **`my_app.py`**. An app is a class that inherits from `ReachyMiniApp` and puts its code in
`run()`. This is the standard Reachy Mini SDK app format, so the same code can later run directly on
the robot.

```python
import threading

import numpy as np
from reachy_mini import ReachyMini, ReachyMiniApp
from reachy_mini.utils import create_head_pose


class MyApp(ReachyMiniApp):
    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        while not stop_event.is_set():          # Quit sets stop_event: return soon after
            reachy_mini.goto_target(head=create_head_pose(yaw=20), duration=1.0)
            reachy_mini.goto_target(head=create_head_pose(yaw=-20), duration=1.0)
```

The robot is already awake when `run()` starts, and it is put back to sleep after your app stops.

### What you can use

| Feature | Call |
|---|---|
| Move head / antennas / body smoothly | `reachy_mini.goto_target(head=create_head_pose(pitch=15, yaw=20), antennas=np.deg2rad([30, -30]), body_yaw=0.3, duration=1.0)` |
| Set a target immediately | `reachy_mini.set_target(antennas=np.deg2rad([20, -20]))` |
| Read the head pose | `reachy_mini.get_current_head_pose()` |
| Robot camera | `frame = reachy_mini.media.get_frame()` (BGR numpy array, use with OpenCV) |
| Look at a point in the camera image | `reachy_mini.look_at_image(u, v, duration=1.0)` (pixels in the 640x360 frame) |
| Play a built-in sound | `reachy_mini.media.play_sound("dance1.wav")` (`wake_up`, `go_sleep`, `dance1`, `confused1`, `impatient1`, `count`) |
| Robot microphone | `reachy_mini.media.start_recording()`, then `chunk = reachy_mini.media.get_audio_sample()` (float32 `(n, 2)` at 16 kHz, or `None`) |
| Robot speaker (your own audio) | `reachy_mini.media.start_playing()`, `reachy_mini.media.push_audio_sample(samples)` (float32 at 16 kHz), `stop_playing()` |

`examples/all_features_app.py` uses every one of them – read it and run it with
`run.bat examples\all_features_app.py`.

### Rules of thumb over the VPN

The VPN is slow (about 0.2–0.3 s each way), so:

- **Send at most ~10 motion commands per second.** Sending one for every audio chunk floods the
  connection and it drops ("Lost connection with the server").
- **Push audio in big pieces** (e.g. a whole sound at once), not 20 ms at a time, or it stutters.
- **Check `stop_event` regularly** so Quit stops your app quickly.
- Not available over the VPN: face tracking, direction of arrival, speech wobbling.

## Rules

- **One person per robot at a time.** Two people moving the same robot send conflicting commands.
- Do not share `robot_config.json`: it contains the robot's password.

## Troubleshooting

| Message / symptom | What to do |
|---|---|
| `Traffic to the robot is not going through GlobalProtect.` | Connect GlobalProtect and run again. |
| `Cannot reach the robot (…:22)` | Check that GlobalProtect is connected and the robot is on. The robot's IP may have changed – ask your instructor. |
| `Port 8000/8443/8090-8093 is already in use` | Another `run.bat` is still running on this PC. Close it first. |
| `SSH connection failed` | Wrong `ssh_user` / `ssh_password`, or the robot is still booting. |
| `does not define a class that inherits from ReachyMiniApp` | Your app file needs `class Something(ReachyMiniApp):` with a `run()` method. |
| App shows `error (see the console)` | Your app raised an exception; the console shows where. |
| `Task did not complete in time` / `Lost connection with the server` | The VPN is too slow or your app sends too many commands; see the rules of thumb above. |
| No start-up sound | Check `volume` in `robot_config.json` (100 = loudest). |
| Video is slow or choppy | Lower `webcam` `fps` (or resolution) in `robot_config.json`. |

## Files

```
my_app.py                    your app (start here)
examples/all_features_app.py tour of every feature
run.bat / setup.bat          start / one-time setup
robot_config.example.json    template for robot_config.json (not committed)
requirements.txt             Python packages
reachy_kit/                  the connection (you do not need to change it)
admin/                       tools for the robot admin, see admin/README.md
```
