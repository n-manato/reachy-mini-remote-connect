"""MJPEG stream of a camera, served on the robot (runs on Reachy Mini).

--source webcam   a USB webcam watching the robot (default)
--source robot    the robot's own camera, read from the daemon's local IPC
                  socket, so it works without WebRTC (whose UDP media does
                  not get through the campus VPN)

Started automatically by reachy_kit.tunnel. Only listens on 127.0.0.1, so it
is reachable through the SSH tunnel only.

    GET /               viewer page
    GET /stream         multipart MJPEG (always the latest frame, no backlog)
    GET /snapshot.jpg   single JPEG
    GET /health         200 once a frame has been captured

Usage:
    python3 webcam_stream.py [--source webcam|robot] [--device PATH]
                             [--width 640] [--height 360] [--fps 8] [--port 8090]
"""

import argparse
import glob
import http.server
import socketserver
import subprocess
import sys
import threading
import time
from typing import Optional

latest_frame: Optional[bytes] = None
frame_id = 0
frame_cond = threading.Condition()

PAGE = b"""<!doctype html><html><head><meta charset="utf-8"><title>Reachy webcam</title>
<style>body{margin:0;background:#111;color:#ccc;font:14px sans-serif;display:flex;flex-direction:column;align-items:center}
img{max-width:100vw;max-height:calc(100vh - 32px)}#s{padding:6px}</style></head>
<body><div id="s">Reachy webcam</div><img src="/stream"></body></html>"""


def find_device() -> str:
    for pattern in ("/dev/v4l/by-id/*EMEET*-video-index0", "/dev/v4l/by-id/usb-*-video-index0"):
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    sys.exit("no USB webcam found under /dev/v4l/by-id")


ROBOT_CAMERA_SOCKET = "/tmp/reachymini_camera_socket"  # served by the Reachy Mini daemon


def pipeline(source: str, device: str, width: int, height: int) -> list:
    """gst-launch command that writes multipart JPEG frames to stdout."""
    if source == "robot":
        head = ["unixfdsrc", f"socket-path={ROBOT_CAMERA_SOCKET}", "!", "queue", "!",
                "v4l2convert", "!", f"video/x-raw,format=I420,width={width},height={height}", "!",
                "jpegenc", "quality=70"]
    else:
        head = ["v4l2src", f"device={device}", "!",
                f"image/jpeg,width={width},height={height},framerate=30/1"]
    return ["gst-launch-1.0", "-q", *head, "!", "multipartmux", "boundary=frame", "!", "fdsink", "fd=1"]


def capture_loop(cmd: list, fps: float) -> None:
    """Read JPEG frames from GStreamer (multipartmux) and keep the latest one."""
    global latest_frame, frame_id
    while True:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        out = proc.stdout
        last = 0.0
        try:
            while True:
                line = out.readline()
                if not line:
                    break
                if not line.lower().startswith(b"content-length:"):
                    continue
                length = int(line.split(b":", 1)[1])
                while out.readline() not in (b"\r\n", b"\n", b""):
                    pass
                jpg = out.read(length)
                # Publish at most `fps` frames per second: over the VPN the
                # streams must leave room for the robot's control traffic.
                now = time.monotonic()
                if now - last < 1.0 / fps:
                    continue
                last = now
                with frame_cond:
                    latest_frame = jpg
                    frame_id += 1
                    frame_cond.notify_all()
        finally:
            proc.kill()
        print("gstreamer exited, restarting in 2s", file=sys.stderr, flush=True)
        time.sleep(2)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # quiet
        pass

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(200, "text/html", PAGE)
        elif self.path == "/health":  # cheap liveness check for the check page
            if latest_frame is None:
                self._send(503, "text/plain", b"no frame yet")
            else:
                self._send(200, "text/plain", b"ok")
        elif self.path.startswith("/snapshot.jpg"):
            with frame_cond:
                frame_cond.wait_for(lambda: latest_frame is not None, timeout=5)
                jpg = latest_frame
            if jpg is None:
                self._send(503, "text/plain", b"no frame yet")
            else:
                self._send(200, "image/jpeg", jpg)
        elif self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            last = -1
            try:
                while True:
                    with frame_cond:
                        frame_cond.wait_for(lambda: frame_id != last, timeout=5)
                        if frame_id == last:
                            continue
                        jpg, last = latest_frame, frame_id
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpg)}\r\n\r\n".encode())
                    self.wfile.write(jpg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client (e.g. the viewer's status check) went away mid-response


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", choices=["webcam", "robot"], default="webcam")
    p.add_argument("--device")
    p.add_argument("--width", type=int, default=640)  # small frames: eduroam + VPN is slow
    p.add_argument("--height", type=int, default=360)
    p.add_argument("--fps", type=float, default=8)
    p.add_argument("--port", type=int, default=8090)
    a = p.parse_args()
    # UVC webcams usually only offer 30/60 fps: capture at 30 and drop frames down to --fps.
    device = ROBOT_CAMERA_SOCKET if a.source == "robot" else (a.device or find_device())
    cmd = pipeline(a.source, device, a.width, a.height)
    threading.Thread(target=capture_loop, args=(cmd, a.fps), daemon=True).start()
    print(f"{a.source} {device} {a.width}x{a.height} on 127.0.0.1:{a.port}", flush=True)
    Server(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
