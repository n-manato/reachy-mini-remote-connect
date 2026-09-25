"""One-click connection to a Reachy Mini over GlobalProtect.

GlobalProtect must be connected (on or off campus): it routes the robots'
eduroam addresses into the VPN, and eduroam itself blocks client-to-client.

1. Reads the robot from robot_config.json
2. Opens an SSH tunnel (port 8000/8443/8090 -> 127.0.0.1)
3. Wakes the robot up (head up + start-up sound)
4. Opens a browser page with the robot camera and the USB webcam
   (the webcam panel shows "Not connected" when there is none)
5. On Ctrl+C or the "Quit" button: robot goes to sleep, everything closes

Usage:
    run.bat          (or: .venv\\Scripts\\python.exe reachy_connect.py)

Copy robot_config.example.json to robot_config.json and fill in the robot's
name, IP and SSH login (ask the robot admin).
"""

import http.server
import ipaddress
import json
import os
import socket
import sys
import threading
import urllib.request
import webbrowser

from reachy_tunnel import ROBOT_CAMERA_PORT, WEBCAM_PORT, close_tunnel, open_tunnel

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "robot_config.json")
LOCAL = "127.0.0.1"
STREAMS = {  # panel id -> MJPEG server on the robot, reached through the tunnel
    "robot": f"http://{LOCAL}:{ROBOT_CAMERA_PORT}",
    "webcam": f"http://{LOCAL}:{WEBCAM_PORT}",
}

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
<header><div><b>{name}</b> ({ip})</div><div id="state"></div><button id="quit">Quit (robot goes to sleep)</button></header>
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
    for (const id in urls) {{
      if (s[id] && !on[id]) {{ document.getElementById(id).innerHTML = '<img src="' + urls[id] + '/stream">'; on[id] = true; }}
      if (!s[id] && on[id]) {{ document.getElementById(id).innerHTML = '<span class="nc">Not connected</span>'; on[id] = false; }}
    }}
  }} catch (e) {{ document.getElementById('state').textContent = 'disconnected'; }}
}}
poll(); setInterval(poll, 5000);
document.getElementById('quit').onclick = async () => {{
  await fetch('/quit', {{method: 'POST'}}).catch(() => {{}});
  document.body.innerHTML = '<p style="padding:16px">Stopped. You can close this tab.</p>';
}};
</script></body></html>"""


def fail(msg: str) -> None:
    print(f"\n[ERROR] {msg}\n")
    input("Press Enter to close...")
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
    webcam = {"width": 640, "height": 360, "fps": 15}  # eduroam + VPN cannot carry 720p
    webcam.update(cfg.get("webcam", {}))
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
    try:
        socket.create_connection((ip, 22), timeout=3).close()
    except OSError:
        fail(f"Cannot reach the robot ({ip}:22).\n"
             "        - Is GlobalProtect connected?\n"
             "        - Is the robot powered on?\n"
             "        - The robot's eduroam IP may have changed (update robot_config.json).")


def stream_available(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/snapshot.jpg", timeout=6) as r:
            return r.status == 200
    except OSError:
        return False


def make_viewer(cfg: dict, stop: threading.Event) -> http.server.ThreadingHTTPServer:
    status = {name: False for name in STREAMS}

    def watch_streams() -> None:
        while not stop.is_set():
            for name, url in STREAMS.items():
                status[name] = stream_available(url)
            stop.wait(5)

    threading.Thread(target=watch_streams, daemon=True).start()
    page = PAGE.format(name=cfg["name"], ip=cfg["ip"], urls=json.dumps(STREAMS)).encode()

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
    cfg = load_config()
    print(f"Robot: {cfg['name']} ({cfg['ip']})")
    preflight(cfg["ip"], cfg.get("isolated_subnet", ""))

    print("Opening SSH tunnel...")
    try:
        w = cfg["webcam"]
        client, servers = open_tunnel(cfg["ip"], cfg["ssh_password"], LOCAL, cfg["ssh_user"],
                                      f"--width {int(w['width'])} --height {int(w['height'])} --fps {int(w['fps'])}")
    except OSError as e:
        if getattr(e, "winerror", None) == 10048 or "address already in use" in str(e).lower():
            fail("Port 8000/8443/8090/8091 is already in use. Is another tunnel or reachy_connect running?")
        fail(f"SSH connection failed: {e}")
    except Exception as e:
        fail(f"SSH connection failed: {e}")

    # Imported late: loading the SDK takes a few seconds.
    from reachy_remote import connect

    stop = threading.Event()
    viewer = None
    try:
        with connect(LOCAL) as mini:
            print("Waking up the robot...")
            set_volume(cfg["volume"])
            mini.enable_motors()  # motors come up disabled after a robot reboot
            mini.wake_up()  # head up + start-up sound (played through the daemon API)

            viewer = make_viewer(cfg, stop)
            url = f"http://{LOCAL}:{viewer.server_address[1]}/"
            print(f"Viewer: {url}")
            webbrowser.open(url)
            print("Running. Press Ctrl+C or the Quit button to stop.")
            try:
                while not stop.wait(0.5):
                    pass
            except KeyboardInterrupt:
                pass
            stop.set()
            print("Putting the robot to sleep...")
            mini.goto_sleep()
    finally:
        stop.set()
        if viewer:
            viewer.shutdown()
            viewer.server_close()
        close_tunnel(client, servers)
        print("Disconnected.")


if __name__ == "__main__":
    main()
