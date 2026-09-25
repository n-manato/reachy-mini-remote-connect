"""Camera / microphone / speaker test over the SSH tunnel (run `python -m reachy_kit.tunnel <robot>` first).

Uses reachy_kit.connect(), so it works over the VPN only.

- Camera: get_frame() + saves one frame to camera_test_<HOST>.jpg
- Speaker (sound file via daemon API) -> mic: plays vpn_beep.wav (C5-E5-G5), checks the mic hears it
- Speaker (push_audio_sample from PC) -> mic: streams a 440 Hz tone, checks the mic hears it
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))  # repo root

import io
import threading
import time
import wave

import numpy as np
import requests

from reachy_kit.remote import connect

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"  # 127.0.0.2 = mini-2, 127.0.0.3 = mini-3

BASE = f"http://{HOST}:8000/api"
TEST_VOLUME = 60


def record(media, seconds: float) -> np.ndarray:
    chunks = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        s = media.get_audio_sample()
        if s is not None:
            chunks.append(s if s.ndim == 1 else s.mean(axis=1))
        time.sleep(0.01)
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def peak_hz(x: np.ndarray, sr: int, lo: float = 200, hi: float = 2000) -> float:
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    band = (freqs > lo) & (freqs < hi)
    return float(freqs[band][np.argmax(spec[band])])


def tone_energy(x: np.ndarray, sr: int, hz: float) -> float:
    """Energy near `hz` relative to the median of the 200-2000 Hz band."""
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    band = (freqs > 200) & (freqs < 2000)
    near = np.abs(freqs - hz) < 8
    return float(spec[near].max() / np.median(spec[band]))


def beep_wav() -> bytes:
    """C5-E5-G5, 0.25 s each."""
    sr = 16000
    t = np.arange(int(sr * 0.25)) / sr
    pcm = (np.concatenate([np.sin(2 * np.pi * f * t) for f in (523, 659, 784)]) * 0.5 * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


requests.post(f"{BASE}/media/sounds/upload", files={"file": ("vpn_beep.wav", beep_wav(), "audio/wav")}, timeout=15)
original = requests.get(f"{BASE}/volume/current", timeout=5).json()["volume"]
requests.post(f"{BASE}/volume/set", json={"volume": TEST_VOLUME}, timeout=5)
try:
    with connect(HOST) as mini:
        media = mini.media

        # --- camera
        jpg = None
        for _ in range(40):
            jpg = media.get_frame_jpeg()
            if jpg:
                break
            time.sleep(0.5)
        if jpg:
            with open(f"camera_test_{HOST}.jpg", "wb") as f:
                f.write(jpg)
        frame = media.get_frame()
        print("CAMERA:", "OK" if jpg else "NG", None if frame is None else frame.shape)

        sr_in = media.get_input_audio_samplerate()
        sr_out = media.get_output_audio_samplerate()
        print(f"audio: in={sr_in}Hz x{media.get_input_channels()}  out={sr_out}Hz x{media.get_output_channels()}")

        media.start_recording()
        time.sleep(1.0)
        record(media, 0.5)  # flush

        # --- baseline (silence)
        base = record(media, 1.0)
        print(f"MIC baseline: {len(base)} samples, rms={np.sqrt(np.mean(base**2)):.4f}")

        # --- daemon play_sound -> mic
        threading.Timer(0.3, lambda: requests.post(
            f"{BASE}/media/play_sound", json={"file": "vpn_beep.wav"}, timeout=10)).start()
        rec = record(media, 1.8)
        scores = {hz: tone_energy(rec, sr_in, hz) for hz in (523, 659, 784)}
        print("SPEAKER(API)->MIC tone score (x median):", {k: round(v, 1) for k, v in scores.items()})

        # --- WebRTC push from PC -> robot speaker -> mic
        media.start_playing()
        t = np.arange(int(sr_out * 1.5)) / sr_out
        tone = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

        def push() -> None:
            step = sr_out // 50
            for i in range(0, len(tone), step):
                media.push_audio_sample(tone[i:i + step])
                time.sleep(step / sr_out)

        threading.Timer(0.3, push).start()
        rec2 = record(media, 2.2)
        media.stop_playing()
        print(f"SPEAKER(push)->MIC: peak={peak_hz(rec2, sr_in):.0f}Hz, 440Hz score={tone_energy(rec2, sr_in, 440):.1f}x")

        media.stop_recording()
finally:
    requests.post(f"{BASE}/volume/set", json={"volume": original}, timeout=5)
    print("volume restored:", original)
