# Admin notes

Tools for whoever looks after the robots. Students do not need anything in this folder.

## How the connection works

The robots sit on the lab Wi-Fi and on eduroam (a USB Wi-Fi adapter, `wlan1`). From the VPN only SSH
(port 22) reaches their eduroam address; the daemon's own ports are blocked, and the SDK's WebRTC
camera/audio (UDP, and signalled to the robot's lab Wi-Fi address) does not get through at all.
`reachy_kit` therefore opens two SSH connections and forwards everything to `127.0.0.1`:

| Port | SSH connection | What |
|---|---|---|
| 8000 | control | robot daemon API (motion, sound files, volume) |
| 8443 | control | WebRTC signaling (only useful on the lab Wi-Fi) |
| 8090 | media | webcam MJPEG stream (`reachy_kit/robot/webcam_stream.py --source webcam`) |
| 8091 | media | robot camera MJPEG stream from the daemon's IPC socket (`--source robot`) |
| 8092 | media | robot microphone, raw PCM 16 kHz stereo over HTTP (`reachy_kit/robot/audio_bridge.py`) |
| 8093 | media | robot speaker, raw PCM 16 kHz stereo over TCP (`audio_bridge.py`) |

Control and media are separate because video queued in a shared SSH connection delayed motion
commands by seconds and the SDK timed out. The robot-side scripts are uploaded to `/home/pollen`
and stop when the SSH session that started them closes; a second user reuses running ones.

`reachy_kit.connect()` returns a `ReachyMini` that skips WebRTC without asking the daemon to release
the camera (plain `media_backend="no_media"` would, and that kills the camera stream), and whose
`media` is `reachy_kit.remote.TunnelMedia`. The launcher loads the student app before connecting
(a broken app never wakes the robot), then calls `app.run(mini, app.stop_event)` with its own
`ReachyMini`, serving the app's settings page (`custom_app_url`) like the SDK does. If an app ignores
Quit for 10 s, `mini.take_control()` makes its further commands raise, and the robot is put to sleep.

## Connection codes for students

Students set up with `setup.bat` and paste a one-line connection code, which holds the robot's
name, IP and SSH login (base64 only, not encrypted – share it like the password):

```
.venv\Scripts\python.exe admin\make_code.py reachy-mini-2 <robot eduroam IP> --subnet <robots' eduroam subnet>
```

`--subnet` is optional; with it the kit can tell students "not going through GlobalProtect" when
their PC reaches the robot's subnet directly. When a robot's eduroam IP changes, make a new code;
students run `configure.bat` and paste it.

## Tunnel only

```
.venv\Scripts\python.exe -m reachy_kit.tunnel <name|ip>
```

Names come from `admin/robots.json` (copy `admin/robots.example.json`; not committed). Each robot gets
its own local address (`127.0.0.1`, `127.0.0.2`, …) so several tunnels can run at once.

## Checks

Run a tunnel first, then from the repo root, e.g. for the robot on `127.0.0.2`:

```
.venv\Scripts\python.exe admin\tests\test_motion.py 127.0.0.2
.venv\Scripts\python.exe admin\tests\test_camera.py 127.0.0.2
.venv\Scripts\python.exe admin\tests\test_media.py 127.0.0.2    # camera + mic + speaker loopback
.venv\Scripts\python.exe admin\tests\test_speaker.py 127.0.0.2
```

## eduroam on a robot

`admin/setup_eduroam.py` configures a robot's USB Wi-Fi adapter for eduroam (PEAP/MSCHAPv2), makes
it the default route (the lab Wi-Fi has no internet) and installs `admin/robot/60-eduroam-policy-route`.
Credentials are read from environment variables only; see the script's docstring. The robots'
eduroam IPs come from DHCP and can change: update `admin/robots.json` and the students'
`robot_config.json` when they do.
