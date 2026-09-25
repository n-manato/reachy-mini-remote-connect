# Reachy Mini remote connect

Connect to one Reachy Mini robot from your own Windows PC over the university VPN (GlobalProtect).
One run of `run.bat`:

1. connects to the robot set in `robot_config.json`,
2. wakes the robot up (head up + start-up sound),
3. opens a browser page showing the **robot camera** and the **webcam** that watches the robot,
4. puts the robot back to sleep when you press **Quit** (or Ctrl+C).

How it works: the robots sit on the campus Wi-Fi with a USB Wi-Fi adapter. The campus network
blocks the robot's API ports from the VPN but allows SSH, so the scripts reach the robot through
an SSH tunnel (ports 8000 / 8443 / 8090 are forwarded to `127.0.0.1`).

## Files

```
reachy_connect.py            main script (run.bat)
reachy_tunnel.py             SSH tunnel to the robot (also usable on its own)
robot/webcam_stream.py       webcam MJPEG stream, uploaded to the robot automatically
robot_config.example.json    template for robot_config.json
requirements.txt             Python packages
setup.bat / run.bat          one-time setup / start

admin only
setup_eduroam.py             connects a robot's USB Wi-Fi (wlan1) to eduroam
robot/60-eduroam-policy-route  NetworkManager hook installed by setup_eduroam.py
robots.example.json          template for robots.json (names for reachy_tunnel.py)
test_*.py                    motion / camera / mic / speaker checks through the tunnel
```

`robot_config.json` and `robots.json` hold robot IPs and passwords and are **not** in the repository.

## Requirements

| | |
|---|---|
| OS | Windows 10 / 11 |
| Python | **3.11 – 3.13, 64-bit** (tested with 3.13). Tick **"Add python.exe to PATH"** when installing. |
| Disk | About 1 GB free |
| Internet | Needed for the one-time setup |
| VPN | **GlobalProtect**, signed in with **your own** university account (works on and off campus) |
| Browser | Any (Edge, Chrome, …) |

## Setup (once)

1. Install Python 3.13 (64-bit) from <https://www.python.org/downloads/> and tick **"Add python.exe to PATH"**.
2. Double-click **`setup.bat`**. It creates a `.venv` folder and installs the Reachy Mini SDK (takes a few minutes).
3. Copy **`robot_config.example.json`** to **`robot_config.json`** and fill it in.
   Ask the robot admin for the robot's `name`, `ip` and `ssh_password`.

   ```json
   {
     "name": "reachy-mini-2",
     "ip": "10.0.0.12",
     "ssh_user": "pollen",
     "ssh_password": "ASK-THE-ROBOT-ADMIN",
     "isolated_subnet": "",
     "volume": 100,
     "webcam": {"width": 640, "height": 360, "fps": 15}
   }
   ```

   - `isolated_subnet` (optional): the robots' Wi-Fi subnet. If set, the script warns when traffic
     to the robot is not going through the VPN.
   - `volume`: robot speaker volume (0–100) set at start-up.
   - `webcam`: webcam resolution/frame rate. Keep it small; the VPN is slow and 1280x720 drops to a few fps.

## How to connect (step by step)

1. **Connect to the VPN.**
   Open **GlobalProtect** from the Windows taskbar and click **Connect**, then sign in with your own university account.
   Wait until it shows **Connected**.
2. **(First time only) Check that the robot is reachable.**
   In PowerShell, run the command below with your robot's `ip`:
   ```powershell
   Test-NetConnection <robot-ip> -Port 22
   ```
   `TcpTestSucceeded : True` means you can reach it. If it says `False`, see [Troubleshooting](#troubleshooting).
3. **Start the connection.**
   Double-click **`run.bat`**. A console window opens and shows:
   ```
   Robot: reachy-mini-2 (<robot-ip>)
   Opening SSH tunnel...
   Waking up the robot...
   Volume: 100 %
   Viewer: http://127.0.0.1:xxxxx/
   Running. Press Ctrl+C or the Quit button to stop.
   ```
   Keep this window open while you use the robot.
4. **Watch the robot.**
   The robot raises its head and plays the start-up sound, and a browser tab opens with two feeds:
   **Robot camera** (what the robot sees) and **Webcam** (a camera watching the robot).
   If the robot has no webcam, the webcam panel shows **"Not connected"**.
5. **Use the robot.** Run your own code while `run.bat` is running (see below).
6. **Finish.** Press **Quit** on the browser page (or Ctrl+C in the console window).
   The robot goes back to its sleep pose and the console shows `Disconnected.`
7. **Disconnect the VPN** in GlobalProtect when you no longer need it. While it is connected, all your
   internet traffic goes through the university VPN and is much slower.

### Using the robot from your own code

While `run.bat` is running, the robot is available on `127.0.0.1`:

```python
from reachy_mini import ReachyMini

with ReachyMini(host="127.0.0.1", connection_mode="network") as mini:
    mini.enable_motors()   # motors are off after a robot reboot
    ...
```

Run it with `.venv\Scripts\python.exe your_script.py`.

## Rules

- **One person per robot at a time.** Two people moving the same robot send conflicting commands.
- Never commit or share `robot_config.json` / `robots.json`: they contain robot passwords.

## Troubleshooting

| Message / symptom | What to do |
|---|---|
| `Traffic to the robot is not going through GlobalProtect.` | Connect GlobalProtect and run again. |
| `Cannot reach the robot (…:22)` | Check that GlobalProtect is connected and the robot is powered on. The robot's IP may have changed; ask the robot admin for the new one and update `ip`. |
| `Port 8000/8443/8090 is already in use` | Another `run.bat` (or tunnel) is still running on this PC. Close it first. |
| `SSH connection failed` | Wrong `ssh_user` / `ssh_password`, or the robot is still booting. |
| No start-up sound | Check `volume` in `robot_config.json` (100 = loudest). |
| Video is slow or choppy | Lower `webcam` resolution/fps. Everything goes through the VPN, which is slow. |
| Robot does not move | The robot may be in use by someone else, or its motors are off (they are turned on automatically at start-up; restart `run.bat`). |

If `Test-NetConnection <robot-ip> -Port 22` returns `False` while GlobalProtect is connected, your VPN
account may not be allowed to reach the robots; contact the robot admin.

## Admin notes

- **Tunnel only:** `python reachy_tunnel.py <name|ip>` forwards the robot's ports without waking it up.
  Names come from `robots.json` (copy `robots.example.json`); each robot gets its own local address
  (`127.0.0.1`, `127.0.0.2`, …) so several tunnels can run at once.
- **eduroam setup:** `setup_eduroam.py` configures a robot's USB Wi-Fi adapter for eduroam
  (PEAP/MSCHAPv2), makes it the default route, and installs `robot/60-eduroam-policy-route`.
  Credentials are read from environment variables only; see the script's docstring.
- **Checks:** `test_motion.py`, `test_media.py`, `test_camera.py`, `test_speaker.py` take the local
  tunnel address as an argument, e.g. `python test_motion.py 127.0.0.2`.
