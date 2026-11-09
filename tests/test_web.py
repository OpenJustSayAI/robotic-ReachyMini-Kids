from fastapi import FastAPI
from fastapi.testclient import TestClient

from ducky_reachy_mini.web import Runtime, configure_web


class Library:
    clips = [
        {
            "id": "peppa_jump",
            "label": "jump",
            "group": "muddy-puddles",
            "language": "en",
        }
    ]
    by_id = {"peppa_jump": clips[0]}


class Player:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"state": "stopped", "clip_id": None}

    def play(self, clip):
        self.calls.append(("play", clip))

    def pause(self):
        self.calls.append("pause")

    def resume(self):
        self.calls.append("resume")

    def replay(self):
        self.calls.append("replay")

    def stop(self):
        self.calls.append("stop")

    def volume(self, value):
        self.calls.append(("volume", value))


def test_startup_routes_and_missing_library_are_clear():
    app = FastAPI()
    runtime = Runtime("test")
    configure_web(app, runtime, serve_static=True)
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/api/status").json()["ready"] is False
    assert client.post("/api/control", json={"action": "stop"}).status_code == 503


def test_controls_and_validation():
    runtime = Runtime("test")
    runtime.library, runtime.player = Library(), Player()
    app = FastAPI()
    configure_web(app, runtime)
    client = TestClient(app)
    assert len(client.get("/api/catalog").json()["clips"]) == 1
    assert client.post("/api/play/peppa_jump").status_code == 200
    for action in ("pause", "resume", "replay", "stop"):
        assert client.post("/api/control", json={"action": action}).status_code == 200
    assert runtime.player.calls == [
        ("play", "peppa_jump"),
        "pause",
        "resume",
        "replay",
        "stop",
    ]
    assert client.post("/api/play/absent").status_code == 404
    assert client.post("/api/control", json={"action": "anything"}).status_code == 422
    assert client.post("/api/volume", json={"value": 1.5}).status_code == 422
    assert client.post("/api/volume", json={"value": 0.4}).status_code == 200
    assert (
        client.post(
            "/api/control",
            json={"action": "stop"},
            headers={"Origin": "https://unrelated.example"},
        ).status_code
        == 403
    )
