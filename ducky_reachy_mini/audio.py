"""Original MP3 decoding and output adapters; no TTS or microphone consumer."""

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


def asset_directory() -> Path:
    return Path(
        os.environ.get(
            "DUCKY_ASSET_DIR", str(Path.home() / ".local/share/ducky-reachy-mini")
        )
    ).expanduser()


class Library:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.clips = manifest["clips"]
        self.by_id = {c["id"]: c for c in self.clips}
        if not self.clips or len(self.by_id) != len(self.clips):
            raise ValueError("Empty library or duplicate clip IDs")
        for clip in self.clips:
            self.path(clip["id"])

    def path(self, clip_id):
        path = (self.directory / self.by_id[clip_id]["path"]).resolve()
        if not path.is_relative_to(self.directory):
            raise ValueError("Audio path escapes asset directory")
        return path

    def decode(self, clip_id: str, sample_rate: int) -> np.ndarray:
        path = self.path(clip_id)
        if (
            hashlib.sha256(path.read_bytes()).hexdigest()
            != self.by_id[clip_id]["sha256"]
        ):
            raise ValueError(f"Audio checksum mismatch: {clip_id}")
        samples, source_rate = sf.read(path, dtype="float32", always_2d=True)
        mono = samples.mean(axis=1)
        if source_rate != sample_rate:
            factor = math.gcd(source_rate, sample_rate)
            mono = resample_poly(mono, sample_rate // factor, source_rate // factor)
        return np.ascontiguousarray(mono, dtype=np.float32)


class ReachySink:
    # Allow the GStreamer device buffer to render the tail before NULL flush.
    drain_seconds = 0.2

    def __init__(self, media):
        self.media = media
        self.sample_rate = media.get_output_audio_samplerate()
        if self.sample_rate <= 0:
            raise RuntimeError("Reachy audio output is unavailable")

    def start(self):
        self.media.start_playing()

    def write(self, samples):
        self.media.push_audio_sample(samples)

    def stop(self):
        # GStreamer stop_playing moves the pipeline to NULL, flushing queued audio.
        self.media.stop_playing()


class DesktopSink:
    def __init__(self):
        import sounddevice as sd

        self.sd = sd
        self.sample_rate = int(sd.query_devices(kind="output")["default_samplerate"])
        self.stream = None

    def start(self):
        self.stream = self.sd.OutputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32", latency="low"
        )
        self.stream.start()

    def write(self, samples):
        self.stream.write(samples)

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.abort()
            finally:
                self.stream.close()
                self.stream = None

    def finish(self):
        if self.stream is not None:
            try:
                self.stream.stop()  # Natural completion drains; interruption uses abort.
            finally:
                self.stream.close()
                self.stream = None
