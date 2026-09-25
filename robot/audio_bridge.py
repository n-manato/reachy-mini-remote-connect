"""Robot microphone / speaker over TCP, for use through the SSH tunnel (runs on Reachy Mini).

The SDK's WebRTC audio is UDP and does not get through the campus VPN, so the
tunnel carries raw PCM instead. Both use the shared ALSA devices that the
daemon also uses (dsnoop / dmix), so they do not block it.

    GET http://127.0.0.1:8092/mic   endless raw PCM: S16LE, 16 kHz, 2 channels
                                    (CORS open, so the viewer page can play it)
    TCP 127.0.0.1:8093              send raw PCM S16LE 16 kHz 2 ch -> robot speaker

Started automatically by reachy_tunnel.py. Only listens on 127.0.0.1.
"""

import http.server
import socketserver
import subprocess
import threading

RATE, CHANNELS = 16000, 2
FMT = ["-f", "S16_LE", "-r", str(RATE), "-c", str(CHANNELS), "-t", "raw"]
MIC_CMD = ["arecord", "-q", "-D", "reachymini_audio_src", *FMT]
SPEAKER_CMD = ["aplay", "-q", "-D", "reachymini_audio_sink", "--buffer-time=200000", *FMT]
MIC_PORT, SPEAKER_PORT = 8092, 8093
CHUNK = RATE * CHANNELS * 2 // 50  # 20 ms


class MicHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        if self.path != "/mic":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Audio-Format", f"s16le;rate={RATE};channels={CHANNELS}")
        self.end_headers()
        proc = subprocess.Popen(MIC_CMD, stdout=subprocess.PIPE)
        try:
            while True:
                data = proc.stdout.read(CHUNK)
                if not data:
                    break
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.kill()


class SpeakerHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        proc = subprocess.Popen(SPEAKER_CMD, stdin=subprocess.PIPE)
        try:
            while True:
                data = self.request.recv(65536)
                if not data:
                    break
                proc.stdin.write(data)
                proc.stdin.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                proc.stdin.close()
                proc.wait(timeout=2)
            except Exception:
                proc.kill()


class ThreadingHTTP(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class ThreadingTCP(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    speaker = ThreadingTCP(("127.0.0.1", SPEAKER_PORT), SpeakerHandler)
    threading.Thread(target=speaker.serve_forever, daemon=True).start()
    print(f"audio bridge: mic http://127.0.0.1:{MIC_PORT}/mic, speaker tcp 127.0.0.1:{SPEAKER_PORT}", flush=True)
    ThreadingHTTP(("127.0.0.1", MIC_PORT), MicHandler).serve_forever()


if __name__ == "__main__":
    main()
