"""A single interruptible player. Commands and sink writes share one lock."""

import threading
import time
from collections.abc import Callable
from typing import Protocol

import numpy as np


class AudioSink(Protocol):
    sample_rate: int

    def start(self) -> None: ...
    def write(self, samples: np.ndarray) -> None: ...
    def stop(self) -> None: ...


class Player:
    def __init__(self, sink: AudioSink, decode: Callable[[str, int], np.ndarray]):
        if sink.sample_rate <= 0:
            raise ValueError("No usable audio output sample rate")
        self.sink, self.decode = sink, decode
        self._cv = threading.Condition()
        self._state = "stopped"
        self._clip = None
        self._samples = np.empty(0, dtype=np.float32)
        self._position = 0
        self._gain = 0.35
        self._error = None
        self._generation = 0
        self._closed = False
        self._due = 0.0
        self._thread = threading.Thread(
            target=self._work, name="ducky-player", daemon=True
        )

    @property
    def worker_alive(self):
        return self._thread.is_alive()

    def start(self):
        self._thread.start()

    def status(self):
        with self._cv:
            return dict(
                state=self._state,
                clip_id=self._clip,
                position_seconds=self._position / self.sink.sample_rate,
                duration_seconds=len(self._samples) / self.sink.sample_rate,
                volume=self._gain,
                error=self._error,
            )

    def _stop_sink(self):
        self.sink.stop()

    def play(self, clip_id: str):
        with self._cv:
            if self._closed:
                raise RuntimeError("Player is closed")
            self._generation += 1
            generation = self._generation
            self._state = "loading"
            self._clip = clip_id
            self._position = 0
            self._samples = np.empty(0, dtype=np.float32)
            self._error = None
            try:
                self._stop_sink()
            except Exception as exc:
                self._fail(exc)
                return
            self._cv.notify_all()
        try:
            samples = self.decode(clip_id, self.sink.sample_rate)
            if not len(samples) or samples.ndim != 1 or not np.isfinite(samples).all():
                raise ValueError("Invalid or empty decoded audio")
        except Exception as exc:
            with self._cv:
                if generation == self._generation:
                    self._fail(exc)
            return
        with self._cv:
            if generation != self._generation or self._closed:
                return
            self._samples = samples
            try:
                self.sink.start()
                self._state, self._due = "playing", time.monotonic()
            except Exception as exc:
                self._fail(exc)
            self._cv.notify_all()

    def pause(self):
        with self._cv:
            if self._state == "loading":
                self.stop()  # Cancel an unfinished decode instead of playing after pause.
            elif self._state == "playing":
                self._state = "paused"
                # Resume the complete utterance; the SDK cannot report the played
                # cursor of audio flushed by stop_playing. Never skip a word tail.
                self._position = 0
                try:
                    self._stop_sink()
                except Exception as exc:
                    self._fail(exc)
                self._cv.notify_all()

    def resume(self):
        with self._cv:
            if self._state == "paused" and not self._closed:
                try:
                    self.sink.start()
                    self._state, self._due = "playing", time.monotonic()
                except Exception as exc:
                    self._fail(exc)
                self._cv.notify_all()

    def replay(self):
        with self._cv:
            clip = self._clip
        if clip is not None:
            self.play(clip)

    def stop(self):
        with self._cv:
            self._generation += 1
            self._state, self._position = "stopped", 0
            try:
                self._stop_sink()
            except Exception as exc:
                self._fail(exc)
            self._cv.notify_all()

    def volume(self, value: float):
        if not 0 <= value <= 1:
            raise ValueError("Volume must be between 0 and 1")
        with self._cv:
            self._gain = value

    def _fail(self, exc):
        self._state, self._error = "error", str(exc)
        try:
            self._stop_sink()
        except Exception:
            pass
        self._cv.notify_all()

    def _work(self):
        chunk_size = max(1, int(self.sink.sample_rate * 0.02))
        with self._cv:
            while not self._closed:
                if self._state != "playing":
                    self._cv.wait()
                    continue
                remaining = self._due - time.monotonic()
                if remaining > 0:
                    self._cv.wait(remaining)
                    continue
                if self._position >= len(self._samples):
                    try:
                        getattr(self.sink, "finish", self.sink.stop)()
                        self._state = "finished"
                    except Exception as exc:
                        self._fail(exc)
                    continue
                end = min(self._position + chunk_size, len(self._samples))
                samples = self._samples[self._position : end] * self._gain
                started = time.monotonic()
                try:
                    self.sink.write(samples)
                except Exception as exc:
                    self._fail(exc)
                    continue
                self._position = end
                self._due = started + len(samples) / self.sink.sample_rate
                if end == len(self._samples):
                    self._due += getattr(self.sink, "drain_seconds", 0.0)

    def close(self):
        with self._cv:
            if self._closed:
                return
            self.stop()
            self._closed = True
            self._cv.notify_all()
        if self._thread.ident is not None:
            self._thread.join(timeout=3)
        if self._thread.is_alive():
            raise RuntimeError("Audio worker did not stop")
