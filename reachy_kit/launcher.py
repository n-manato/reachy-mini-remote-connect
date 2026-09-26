"""Connect to a Reachy Mini over GlobalProtect and run a student app on it.

GlobalProtect must be connected (on or off campus): it routes the robots'
eduroam addresses into the VPN, and eduroam itself blocks client-to-client.

1. Reads the robot from robot_config.json
2. Opens an SSH tunnel (ports 8000, 8443, 8090-8093 -> 127.0.0.1)
3. Wakes the robot up (head up + start-up sound)
4. Opens the check page in the browser: robot camera, USB webcam (a panel shows
   "Not connected" when its camera is missing), a button to listen to the
   robot microphone, and the app's state
5. Runs the app (a ReachyMiniApp subclass, my_app.py by default; loaded and
   checked before connecting) with the same ReachyMini, which works over the tunnel
6. On Ctrl+C or the "Quit" button: stops the app, puts the robot to sleep,
   closes everything

Usage:
    run.bat [APP.py]     (or: .venv\\Scripts\\python.exe -m reachy_kit.launcher [APP.py])

Copy robot_config.example.json to robot_config.json and fill in the robot's
name, IP and SSH login (ask the robot admin).
"""

import http.server
import importlib.util
import ipaddress
import json
import os
import signal
import socket
import sys
import threading
import traceback
import urllib.error
import urllib.request
import webbrowser
from typing import Optional

from .tunnel import MIC_PORT, ROBOT_CAMERA_PORT, WEBCAM_PORT, close_tunnel, open_tunnel

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "robot_config.json")
LOCAL = "127.0.0.1"
STREAMS = {  # panel id -> MJPEG server on the robot, reached through the tunnel
    "robot": f"http://{LOCAL}:{ROBOT_CAMERA_PORT}",
    "webcam": f"http://{LOCAL}:{WEBCAM_PORT}",
}
MIC_URL = f"http://{LOCAL}:{MIC_PORT}/mic"  # raw PCM s16le, 16 kHz, 2 ch

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{name}</title>
<style>
body{{margin:0;background:#111;color:#ddd;font:14px sans-serif}}
header{{display:flex;justify-content:space-between;align-items:center;padding:8px 16px}}
main{{display:flex;flex-wrap:wrap;gap:12px;padding:0 16px 16px}}
section{{flex:1 1 480px;min-width:0}} h2{{font-size:15px;margin:6px 0}}
.view{{aspect-ratio:16/9;background:#000;display:flex;align-items:center;justify-content:center;border:1px solid #333}}
.view img{{width:100%;height:100%;object-fit:contain}} .nc{{color:#888;font-size:20px}}
button{{font-size:14px;padding:6px 16px}}
</style></head><body>
<header><div><b>{name}</b> ({ip})</div><div>App: <b id="app">-</b> <span id="state"></span></div>
<div><button id="listen">Listen to robot mic</button> <button id="quit">Quit (robot goes to sleep)</button></div></header>
<main>
<section><h2>Robot camera</h2><div class="view" id="robot"><span class="nc">Not connected</span></div></section>
<section><h2>Webcam</h2><div class="view" id="webcam"><span class="nc">Not connected</span></div></section>
</main>
<script>
const urls = {urls};
const on = {{}};
async function poll() {{
  try {{
    const s = await (await fetch('/status')).json();
    document.getElementById('app').textContent = s.app;
    for (const id in urls) {{
      if (s[id] && !on[id]) {{ document.getElementById(id).innerHTML = '<img src="' + urls[id] + '/stream">'; on[id] = true; }}
      if (!s[id] && on[id]) {{ document.getElementById(id).innerHTML = '<span class="nc">Not connected</span>'; on[id] = false; }}
    }}
  }} catch (e) {{ document.getElementById('state').textContent = 'disconnected'; }}
}}
poll(); setInterval(poll, 5000);

// Robot microphone: raw PCM (s16le, 16 kHz, stereo) through the tunnel, played with Web Audio.
let mic = null;
document.getElementById('listen').onclick = async (ev) => {{
  const btn = ev.target;
  if (mic) {{ mic.abort.abort(); mic.ctx.close(); mic = null; btn.textContent = 'Listen to robot mic'; return; }}
  const ctx = new AudioContext({{sampleRate: 16000}});
  const abort = new AbortController();
  mic = {{ctx, abort}};
  btn.textContent = 'Stop listening';
  let next = 0, rest = new Uint8Array(0);
  try {{
    const reader = (await fetch('{mic_url}', {{signal: abort.signal}})).body.getReader();
    for (;;) {{
      const {{value, done}} = await reader.read();
      if (done) break;
      const buf = new Uint8Array(rest.length + value.length);
      buf.set(rest); buf.set(value, rest.length);
      const usable = buf.length - buf.length % 4;
      rest = buf.slice(usable);
      const pcm = new Int16Array(buf.buffer, 0, usable / 2);
      const n = pcm.length / 2;
      if (!n) continue;
      const ab = ctx.createBuffer(1, n, 16000), ch = ab.getChannelData(0);
      for (let i = 0; i < n; i++) ch[i] = (pcm[2 * i] + pcm[2 * i + 1]) / 65536;
      const src = ctx.createBufferSource();
      src.buffer = ab; src.connect(ctx.destination);
      const now = ctx.currentTime;
      if (next < now || next > now + 0.5) next = now + 0.1;  // resync, keep latency low
      src.start(next); next += ab.duration;
    }}
  }} catch (e) {{ if (mic) btn.textContent = 'Listen to robot mic'; mic = null; }}
}};

document.getElementById('quit').onclick = async () => {{
  await fetch('/quit', {{method: 'POST'}}).catch(() => {{}});
  document.body.innerHTML = '<p style="padding:16px">Stopped. You can close this tab.</p>';
}};
</script></body></html>"""


def fail(msg: str) -> None:
    print(f"\n[ERROR] {msg}\n")
    try:
        input("Press Enter to close...")  # keep the run.bat window open
    except EOFError:
        pass
    sys.exit(1)


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        fail(f"{CONFIG_PATH} not found.\n"
             "        Copy robot_config.example.json to robot_config.json and fill it in.")
    missing = [k for k in ("name", "ip", "ssh_password") if not cfg.get(k)]
    if missing:
        fail(f"robot_config.json is missing: {', '.join(missing)}")
    cfg.setdefault("ssh_user", "pollen")
    cfg.setdefault("volume", 100)
    webcam = {"width": 640, "height": 360, "fps": 8}  # the VPN is slow: leave room for control
    webcam.update(cfg.get("webcam", {}))
    try:  # these end up on the robot's command line, so only plain numbers
        webcam = {"width": int(webcam["width"]), "height": int(webcam["height"]), "fps": float(webcam["fps"])}
    except (TypeError, ValueError):
        fail('robot_config.json: "webcam" width/height/fps must be numbers, e.g. {"width": 640, "height": 360, "fps": 8}')
    if min(webcam.values()) <= 0:
        fail('robot_config.json: "webcam" width/height/fps must be greater than 0')
    cfg["webcam"] = webcam
    return cfg


def set_volume(volume: int) -> None:
    """Robot volume can be left low (e.g. 62 % after a reboot); the start-up sound needs it up."""
    req = urllib.request.Request(
        f"http://{LOCAL}:8000/api/volume/set", method="POST",
        data=json.dumps({"volume": volume}).encode(), headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"Volume: {json.load(r)['volume']} %")
    except OSError as e:
        print(f"Could not set volume: {e}")


def preflight(ip: str, isolated_subnet: str = "") -> None:
    """Check that the robot is reached through the VPN.

    isolated_subnet: the robots' Wi-Fi subnet, which blocks client-to-client
    traffic. If this PC talks to the robot from inside it, the VPN is not in use.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((ip, 22))
        src = ipaddress.ip_address(s.getsockname()[0])
        s.close()
    except OSError:
        fail("No network route to the robot. Is GlobalProtect connected?")
    if isolated_subnet and src in ipaddress.ip_network(isolated_subnet):
        # With GlobalProtect up, this subnet is routed into the VPN; going out
        # through the Wi-Fi directly means GP is down.
        fail("Traffic to the robot is not going through GlobalProtect.\n"
             "        Connect GlobalProtect and try again.")
    for attempt in range(3):  # the VPN sometimes drops the first packets after (re)connecting
        try:
            socket.create_connection((ip, 22), timeout=5).close()
            break
        except OSError:
            pass
    else:
        fail(f"Cannot reach the robot ({ip}:22).\n"
             "        - Is GlobalProtect connected?\n"
             "        - Is the robot powered on?\n"
             "        - The robot's eduroam IP may have changed (update robot_config.json).")


def stream_available(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=6) as r:  # tiny reply, not a whole JPEG
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return False
        # A stream server started by an older kit (reused, not restarted) has no /health.
        try:
            with urllib.request.urlopen(f"{url}/snapshot.jpg", timeout=6) as r:
                return r.status == 200
        except OSError:
            return False
    except OSError:
        return False


def load_app(path: str):
    """Import APP.py and instantiate the ReachyMiniApp subclass it defines.

    Runs before connecting, so a broken app never leaves the robot awake.
    """
    from reachy_mini.apps.app import ReachyMiniApp

    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))  # let the app import its neighbours
    spec = importlib.util.spec_from_file_location("student_app", path)
    module = importlib.util.module_from_spec(spec)
    # Registered like a normal import: ReachyMiniApp looks its own module up by
    # name (e.g. to find the static/ folder of apps with a settings page).
    sys.modules["student_app"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        traceback.print_exc()
        fail(f"Could not load {path} (see the error above).")
    apps = [c for c in vars(module).values()
            if isinstance(c, type) and issubclass(c, ReachyMiniApp) and c.__module__ == module.__name__]
    if not apps:
        fail(f"{path} does not define a class that inherits from ReachyMiniApp.")
    try:
        return apps[0]()
    except Exception:
        traceback.print_exc()
        fail(f"Could not create {apps[0].__name__} (see the error above).")


def start_settings_page(app) -> Optional[threading.Thread]:
    """Serve the app's settings page (custom_app_url) like the SDK's wrapped_run does."""
    if app.settings_app is None:
        return None
    import uvicorn
    from urllib.parse import urlparse

    url = urlparse(app.custom_app_url)
    server = uvicorn.Server(uvicorn.Config(app.settings_app, host=url.hostname, port=url.port, log_level="warning"))

    def serve() -> None:
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        app.stop_event.wait()
        server.should_exit = True
        t.join(timeout=5)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    print(f"App settings page: http://127.0.0.1:{url.port}/")
    return thread


def run_app(app, mini, state: dict) -> None:
    """Run the app like the SDK's wrapped_run, but with our tunnel-aware ReachyMini."""
    state["app"] = "running"
    settings = None
    try:
        settings = start_settings_page(app)
        app.run(mini, app.stop_event)
        state["app"] = "finished"
        if not app.stop_event.is_set():  # the app ended on its own, not via Quit
            print("App finished. Press Quit (or Ctrl+C) to disconnect.")
    except Exception:
        state["app"] = "error (see the console)"
        traceback.print_exc()
    finally:
        if settings is not None:
            app.stop_event.set()
            settings.join(timeout=5)


def make_viewer(cfg: dict, stop: threading.Event, status: dict) -> http.server.ThreadingHTTPServer:
    status.update({name: False for name in STREAMS})

    def watch_streams() -> None:
        while not stop.is_set():
            for name, url in STREAMS.items():
                status[name] = stream_available(url)
            stop.wait(5)

    threading.Thread(target=watch_streams, daemon=True).start()
    page = PAGE.format(name=cfg["name"], ip=cfg["ip"], urls=json.dumps(STREAMS), mic_url=MIC_URL).encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _send(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/":
                self._send(200, "text/html; charset=utf-8", page)
            elif self.path == "/status":
                self._send(200, "application/json", json.dumps(status).encode())
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self) -> None:
            if self.path == "/quit":
                self._send(200, "text/plain", b"bye")
                stop.set()
            else:
                self._send(404, "text/plain", b"not found")

    server = http.server.ThreadingHTTPServer((LOCAL, 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    if len(sys.argv) > 1:
        app_path = sys.argv[1]
        if not os.path.isfile(app_path):  # a typo must not silently run no app
            fail(f"App file not found: {app_path}")
    else:
        app_path = os.path.join(ROOT, "my_app.py")
        if not os.path.isfile(app_path):
            print(f"No app at {app_path}; only the check page will run.")
            app_path = ""
    cfg = load_config()
    print(f"Robot: {cfg['name']} ({cfg['ip']})")
    preflight(cfg["ip"], cfg.get("isolated_subnet", ""))

    # Load the app before connecting: a broken app must fail before the robot wakes up.
    app = None
    if app_path:
        print(f"Loading app: {app_path}")
        app = load_app(app_path)

    print("Opening SSH tunnel...")
    w = cfg["webcam"]
    try:
        clients, servers = open_tunnel(cfg["ip"], cfg["ssh_password"], LOCAL, cfg["ssh_user"],
                                       f"--width {w['width']} --height {w['height']} --fps {w['fps']}")
    except OSError as e:
        if getattr(e, "winerror", None) == 10048 or "address already in use" in str(e).lower():
            fail("Port 8000/8443/8090-8093 is already in use. Is another run.bat or tunnel running?")
        fail(f"SSH connection failed: {e}")
    except Exception as e:
        fail(f"SSH connection failed: {e}")

    from .remote import connect

    stop = threading.Event()
    status = {"app": "none"}
    viewer = app_thread = None
    try:
        with connect(LOCAL, camera_size=(w["width"], w["height"])) as mini:
            try:
                print("Waking up the robot...")
                set_volume(cfg["volume"])
                mini.enable_motors()  # motors come up disabled after a robot reboot
                mini.wake_up()  # head up + start-up sound (played through the daemon API)

                viewer = make_viewer(cfg, stop, status)
                url = f"http://{LOCAL}:{viewer.server_address[1]}/"
                print(f"Check page: {url}")
                webbrowser.open(url)

                print("Running. Press Ctrl+C or the Quit button to stop.")
                if app is not None:
                    print(f"Starting app: {type(app).__name__} ({app_path})", flush=True)
                    app_thread = threading.Thread(target=run_app, args=(app, mini, status), daemon=True)
                    app_thread.start()
                try:
                    while not stop.wait(0.5):
                        pass
                except KeyboardInterrupt:
                    pass
            finally:
                # Always hand the robot back asleep, whatever happened above; a second
                # Ctrl+C while doing so must not leave it awake with the motors on.
                signal.signal(signal.SIGINT, signal.SIG_IGN)
                stop.set()
                if app_thread and app_thread.is_alive():
                    print("Stopping the app...")
                    app.stop()
                    app_thread.join(timeout=10)
                    if app_thread.is_alive():
                        print("The app did not stop within 10 s (does run() check stop_event?); "
                              "blocking its commands.")
                        mini.take_control()  # the app's next command raises instead of fighting the sleep
                        app_thread.join(timeout=2)
                print("Putting the robot to sleep...")
                try:
                    mini.goto_sleep()
                except Exception as e:
                    print(f"Could not put the robot to sleep: {e}")
    except KeyboardInterrupt:
        pass  # Ctrl+C during start-up: the robot has been put to sleep above
    finally:
        stop.set()
        if viewer:
            viewer.shutdown()
            viewer.server_close()
        close_tunnel(clients, servers)
        print("Disconnected.")


if __name__ == "__main__":
    main()
