import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from ducky_reachy_mini import main


class Media:
    def __init__(self):
        self.stops = 0

    def get_output_audio_samplerate(self):
        return 16000

    def stop_playing(self):
        self.stops += 1


class Library:
    def __init__(self, directory):
        self.clips = []
        self.by_id = {}

    def decode(self, key, rate):
        raise AssertionError("No autoplay")


def test_sdk_stop_event_closes_player_without_robot_motion(monkeypatch):
    monkeypatch.setattr(
        main.ReachyMiniApp, "_check_daemon_on_localhost", lambda *a: False
    )
    monkeypatch.setattr(main, "Library", Library)
    app = main.DuckyReachyMini()
    client = TestClient(app.settings_app)
    assert client.get("/api/status").status_code == 200  # Before run()
    media = Media()
    stop_event = threading.Event()
    thread = threading.Thread(
        target=app.run, args=(SimpleNamespace(media=media), stop_event)
    )
    thread.start()
    deadline = time.monotonic() + 2
    while app.runtime.player is None and time.monotonic() < deadline:
        time.sleep(0.005)
    player = app.runtime.player
    assert player is not None
    assert client.get("/api/status").json()["ready"] is True
    stop_event.set()
    thread.join(2)
    assert not thread.is_alive()
    assert not player.worker_alive
    assert app.runtime.player is None
    assert media.stops > 0


def test_missing_bundle_explained_on_settings_page(monkeypatch):
    monkeypatch.setattr(
        main.ReachyMiniApp, "_check_daemon_on_localhost", lambda *a: False
    )

    def missing(path):
        raise FileNotFoundError("Missing manifest.json")

    monkeypatch.setattr(main, "Library", missing)
    app = main.DuckyReachyMini()
    stop = threading.Event()
    stop.set()
    app.run(SimpleNamespace(media=Media()), stop)
    state = TestClient(app.settings_app).get("/api/status").json()
    assert not state["ready"]
    assert "manifest.json" in state["startup_error"]
