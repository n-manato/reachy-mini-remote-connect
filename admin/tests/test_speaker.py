"""Speaker test over the SSH tunnel (run `python -m reachy_kit.tunnel <robot>` first)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))  # repo root

import io
import time
import wave

import numpy as np
import requests

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"  # 127.0.0.2 = mini-2, 127.0.0.3 = mini-3
BASE = f"http://{HOST}:8000/api"
TEST_VOLUME = 60


def make_beep_wav() -> bytes:
    sr = 16000
    t = np.arange(int(sr * 0.25)) / sr
    tones = [np.sin(2 * np.pi * f * t) for f in (523, 659, 784)]  # C-E-G
    pcm = (np.concatenate(tones) * 0.5 * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


original = requests.get(f"{BASE}/volume/current", timeout=5).json()["volume"]
print("original volume:", original)
try:
    print("set volume:", requests.post(f"{BASE}/volume/set", json={"volume": TEST_VOLUME}, timeout=5).json())

    print("test-sound:", requests.post(f"{BASE}/volume/test-sound", timeout=10).json())
    time.sleep(2)

    r = requests.post(f"{BASE}/media/sounds/upload",
                      files={"file": ("vpn_beep.wav", make_beep_wav(), "audio/wav")}, timeout=15)
    print("upload:", r.status_code, r.json())
    r = requests.post(f"{BASE}/media/play_sound", json={"file": "vpn_beep.wav"}, timeout=10)
    print("play_sound:", r.status_code, r.json())
    time.sleep(1.5)
finally:
    print("restore volume:", requests.post(f"{BASE}/volume/set", json={"volume": original}, timeout=5).json())
