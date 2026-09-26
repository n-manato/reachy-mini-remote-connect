# Reachy Mini starter kit

Build your own app for the lab's Reachy Mini robots from your Windows PC, over the university VPN.
The connection is already handled for you: you write the app in **`my_app.py`** and start it with **`run.bat`**.

`run.bat`:

1. connects to the robot set in `robot_config.json`,
2. wakes the robot up (head up + start-up sound),
3. opens the **check page** in your browser (robot camera, webcam watching the robot, robot microphone),
4. runs your app,
5. when you press **Quit** (or Ctrl+C): stops your app and puts the robot back to sleep.

## Quick start

With **GlobalProtect connected** (any Wi-Fi: campus, home, dorm, ...):

1. Get the kit: `git clone https://github.com/n-manato/reachy-mini-remote-connect.git`
   (or **Code → Download ZIP** on GitHub and unzip it). Put it in a normal folder such as
   `C:\reachy-mini`, **not in OneDrive**.
2. Double-click **`setup.bat`** and follow the prompts. It
   - finds Python 3.11–3.13, or offers to install Python 3.13 for you (winget),
   - installs everything into a `.venv` folder (a few minutes, about 1 GB),
   - asks for the **connection code** from your instructor (one line starting with `reachy1:`),
   - tests the connection to the robot and tells you what to fix if something is wrong.
3. Double-click **`run.bat`**.

To switch to another robot later, double-click **`configure.bat`** and paste its code.

## Requirements

| | |
|---|---|
| OS | Windows 10 / 11 |
| Python | 3.11 – 3.13, 64-bit; `setup.bat` finds it or installs 3.13 |
| Disk | About 1 GB free |
| VPN | **GlobalProtect**, signed in with **your own** university account |
| Wi-Fi | Any – the robot is reached through the VPN |
| Browser | Any (Edge, Chrome, …) |

No connection code? Press Enter at the prompt and type the robot's name, IP address and SSH
password (ask your instructor). They are saved in `robot_config.json`, which is never committed.

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
| `GlobalProtect is not connected.` / `Traffic to the robot is not going through GlobalProtect.` | Connect GlobalProtect and run again. |
| `setup.bat`: `Python 3.11-3.13 (64-bit) was not found` | Let it install Python 3.13, or install it from python.org, then run `setup.bat` again. |
| `That code did not work` | Copy the whole connection code (one line starting with `reachy1:`) and paste it again. |
| `Login failed: wrong SSH user or password` | Run `configure.bat` and paste the code again, or check the details with your instructor. |
| `The robot (…) does not answer on port 22` | Check that GlobalProtect is connected and the robot is on. The robot's IP may have changed – ask your instructor for a new code and run `configure.bat`. |
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
setup.bat                    one-time setup (Python, packages, robot connection)
run.bat                      start
configure.bat                change the robot / re-test the connection
robot_config.example.json    what robot_config.json looks like (the real one is not committed)
requirements.txt             Python packages
reachy_kit/                  the connection (you do not need to change it)
admin/                       tools for the robot admin, see admin/README.md
```
