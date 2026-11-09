import threading
import time

import numpy as np
import pytest

from ducky_reachy_mini.playback import Player


class Sink:
    sample_rate = 1000

    def __init__(self):
        self.samples = []
        self.running = False
        self.starts = 0
        self.stops = 0

    def start(self):
        self.running = True
        self.starts += 1

    def write(self, samples):
        assert self.running
        self.samples.extend(samples.tolist())

    def stop(self):
        self.running = False
        self.stops += 1


def until(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out")


@pytest.fixture
def player():
    sink = Sink()
    p = Player(
        sink, lambda key, rate: np.full(500, 1 if key == "a" else 2, dtype=np.float32)
    )
    p.start()
    yield p, sink
    p.close()


def test_pause_resume_replay_stop(player):
    p, sink = player
    p.play("a")
    until(lambda: len(sink.samples) >= 40)
    p.pause()
    cursor = p.status()["position_seconds"]
    assert cursor == 0
    count = len(sink.samples)
    time.sleep(0.06)
    assert len(sink.samples) == count
    assert p.status()["state"] == "paused"
    p.resume()
    until(lambda: p.status()["position_seconds"] > cursor)
    p.replay()
    assert p.status()["position_seconds"] <= 0.02
    p.stop()
    count = len(sink.samples)
    time.sleep(0.05)
    assert len(sink.samples) == count
    assert p.status()["state"] == "stopped"
    p.play("b")
    until(lambda: p.status()["state"] == "finished")
    assert sink.samples[-1] == pytest.approx(0.7)  # 2 * default gain .35


def test_replacement_drops_previous_audio(player):
    p, sink = player
    p.play("a")
    until(lambda: len(sink.samples) >= 20)
    p.play("b")
    boundary = len(sink.samples)
    until(lambda: len(sink.samples) > boundary)
    p.pause()
    assert all(v == pytest.approx(0.7) for v in sink.samples[boundary:])


def test_delayed_decode_cannot_override_stop():
    entered, release = threading.Event(), threading.Event()

    def decode(key, rate):
        entered.set()
        release.wait(2)
        return np.ones(100, dtype=np.float32)

    p = Player(Sink(), decode)
    p.start()
    t = threading.Thread(target=p.play, args=("a",))
    t.start()
    assert entered.wait(1)
    p.stop()
    release.set()
    t.join(1)
    assert p.status()["state"] == "stopped"
    p.close()


def test_device_error_exposes_failure_and_worker_survives(player):
    p, sink = player

    def fail(samples):
        raise RuntimeError("speaker disconnected")

    original = sink.write
    sink.write = fail
    p.play("a")
    until(lambda: p.status()["state"] == "error")
    assert "speaker disconnected" in p.status()["error"]
    sink.write = original
    p.play("b")
    until(lambda: p.status()["state"] == "finished")


def test_close_joins_worker_and_rejects_play(player):
    p, sink = player
    p.play("a")
    p.close()
    assert not p.worker_alive
    assert not sink.running
    with pytest.raises(RuntimeError):
        p.play("b")


def test_natural_completion_drains_and_interruption_aborts():
    sink = Sink()
    completed = []
    sink.finish = lambda: completed.append(True)
    p = Player(sink, lambda key, rate: np.ones(20, dtype=np.float32))
    p.start()
    p.play("a")
    until(lambda: p.status()["state"] == "finished")
    assert completed == [True]
    p.play("a")
    p.stop()
    assert completed == [True]
    p.close()


def test_resume_restarts_sentence_when_device_queue_was_flushed():
    sink = Sink()
    p = Player(sink, lambda key, rate: np.arange(500, dtype=np.float32) / 500)
    p.start()
    p.play("a")
    until(lambda: len(sink.samples) >= 40)
    p.pause()
    assert p.status()["position_seconds"] == 0
    sink.samples.clear()  # Model queued-but-unheard frames discarded by device stop.
    p.resume()
    until(lambda: len(sink.samples) >= 20)
    p.pause()
    assert sink.samples[0] == 0
    p.close()
