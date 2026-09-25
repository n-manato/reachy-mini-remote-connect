"""Forward the Reachy Mini daemon ports to a local address through SSH (port 22).

The campus network blocks TCP 8000/8443 from the VPN but allows SSH, so the
daemon is reached through an SSH tunnel over the robot's eduroam address.
Each robot gets its own loopback address, so several tunnels can run at once
with the same port numbers (the SDK always uses 8443 for WebRTC signaling).

Usage:
    python reachy_tunnel.py ROBOT      ROBOT = a name from robots.json, or an IP

robots.json (not committed, see robots.example.json) maps names to
[robot IP, local address], e.g. {"mini-2": ["10.0.0.12", "127.0.0.2"]}.

Keep it running, then connect with e.g.:
    ReachyMini(host="127.0.0.2", connection_mode="network")

It also starts two MJPEG streams on the robot (robot/webcam_stream.py):
    http://<local address>:8090/   USB webcam watching the robot (if plugged in)
    http://<local address>:8091/   the robot's own camera
The SDK's WebRTC camera/audio does not work over the VPN; use reachy_remote.py.
"""

import getpass
import json
import logging
import os
import select
import socket
import socketserver
import sys
import threading

import paramiko

# paramiko logs every refused port-forward at ERROR; make_handler reports it once.
logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)

HERE = os.path.dirname(os.path.abspath(__file__))
ROBOTS_PATH = os.path.join(HERE, "robots.json")
WEBCAM_PORT = 8090        # USB webcam watching the robot
ROBOT_CAMERA_PORT = 8091  # robot's own camera (WebRTC media does not pass the VPN)
PORTS = [8000, 8443, WEBCAM_PORT, ROBOT_CAMERA_PORT]  # 8000 daemon API, 8443 WebRTC signaling
STREAM_SCRIPT = os.path.join(HERE, "robot", "webcam_stream.py")
REMOTE_STREAM_SCRIPT = "/home/pollen/webcam_stream.py"


def start_stream(client: paramiko.SSHClient, source: str, port: int, args: str = "") -> None:
    """Start an MJPEG server on the robot unless one is already running on that port.

    The server stops when the SSH session that started it closes. An already
    running one (started by someone else's tunnel) is reused, not restarted,
    so its resolution stays whatever the first user chose.
    """
    tag = f"[{source} stream]"
    # "[p]ython3" so the pattern does not match the shell running pgrep itself
    _, out, _ = client.exec_command(f"pgrep -f '[p]ython3 .*webcam_stream.py --port {port}'")
    if out.read().strip():
        print(f"{tag} already running, reusing it", flush=True)
        return
    chan = client.get_transport().open_session()
    chan.get_pty()  # closing the session then kills the remote process
    chan.exec_command(f"python3 {REMOTE_STREAM_SCRIPT} --port {port} --source {source} {args}".strip())

    def relay() -> None:
        for line in iter(chan.makefile("r").readline, ""):
            print(f"{tag} {line.rstrip()}", flush=True)

    threading.Thread(target=relay, daemon=True).start()


def start_streams(client: paramiko.SSHClient, webcam_args: str = "") -> None:
    """Upload webcam_stream.py and start the webcam and robot-camera streams."""
    sftp = client.open_sftp()
    with open(STREAM_SCRIPT, "rb") as f:
        sftp.putfo(f, REMOTE_STREAM_SCRIPT)
    sftp.close()
    start_stream(client, "webcam", WEBCAM_PORT, webcam_args)
    start_stream(client, "robot", ROBOT_CAMERA_PORT, webcam_args)


def make_handler(transport: paramiko.Transport, remote_port: int) -> type:
    reported = False  # e.g. 8090 is refused on every poll when there is no webcam

    class ForwardHandler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            nonlocal reported
            try:
                chan = transport.open_channel(
                    "direct-tcpip", ("127.0.0.1", remote_port), self.request.getpeername()
                )
            except Exception as e:
                if not reported:
                    print(f"nothing listening on robot port {remote_port} ({e})", flush=True)
                    reported = True
                self.request.close()
                return
            try:
                while True:
                    r, _, _ = select.select([self.request, chan], [], [])
                    if self.request in r:
                        data = self.request.recv(65536)
                        if not data:
                            break
                        chan.sendall(data)
                    if chan in r:
                        data = chan.recv(65536)
                        if not data:
                            break
                        self.request.sendall(data)
            except OSError:
                pass  # either side dropped the connection
            finally:
                chan.close()
                self.request.close()

    return ForwardHandler


class ThreadedServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second tunnel silently bind the same
    # port; keep it off there so a busy port fails loudly.
    allow_reuse_address = sys.platform != "win32"


class ThreadedServerV6(ThreadedServer):
    # Windows resolves "localhost" to ::1 first; without a v6 listener every
    # connection waits ~2 s before falling back to 127.0.0.1.
    address_family = socket.AF_INET6


def open_tunnel(robot_ip: str, password: str, local_addr: str = "127.0.0.1",
                 user: str = "pollen", webcam_args: str = "") -> tuple[paramiko.SSHClient, list]:
    """SSH to the robot, start the webcam stream and forward PORTS to local_addr.

    webcam_args is passed to both robot/webcam_stream.py instances (webcam and
    robot camera), e.g. "--width 640 --height 360 --fps 15".
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(robot_ip, username=user, password=password, timeout=10,
                   allow_agent=False, look_for_keys=False)
    transport = client.get_transport()
    transport.set_keepalive(30)
    start_streams(client, webcam_args)

    listen = [(ThreadedServer, local_addr)]
    if local_addr == "127.0.0.1":
        listen.append((ThreadedServerV6, "::1"))  # so "localhost" works too
    servers = []
    for port in PORTS:
        handler = make_handler(transport, port)
        for server_cls, addr in listen:
            server = server_cls((addr, port), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
        print(f"tunnel up: {local_addr}:{port} -> {robot_ip}:{port}", flush=True)
    return client, servers


def close_tunnel(client: paramiko.SSHClient, servers: list) -> None:
    for server in servers:
        server.shutdown()
        server.server_close()
    client.close()


def wait_forever() -> None:
    """Block until Ctrl+C (short waits so the interrupt is seen on Windows)."""
    stop = threading.Event()
    while not stop.wait(0.5):
        pass


def load_robots() -> dict:
    """name -> (robot IP, local address) from robots.json, if present."""
    try:
        with open(ROBOTS_PATH, encoding="utf-8") as f:
            return {name: tuple(v) for name, v in json.load(f).items()}
    except FileNotFoundError:
        return {}


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    arg = sys.argv[1]
    robot_ip, local_addr = load_robots().get(arg, (arg, "127.0.0.1"))
    password = os.environ.get("REACHY_PASSWORD") or getpass.getpass(f"pollen@{robot_ip} password: ")
    client, servers = open_tunnel(robot_ip, password, local_addr)
    print("Ctrl+C to stop", flush=True)
    try:
        wait_forever()
    except KeyboardInterrupt:
        pass
    finally:
        close_tunnel(client, servers)


if __name__ == "__main__":
    main()
