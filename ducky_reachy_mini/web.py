"""Parent controls shared by the SDK app and desktop preview."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .audio import Library
from .playback import Player


@dataclass
class Runtime:
    output: str
    library: Library | None = None
    player: Player | None = None
    error: str | None = None


class Control(BaseModel):
    action: Literal["pause", "resume", "replay", "stop"]


class Volume(BaseModel):
    value: float = Field(ge=0, le=1)


def configure_web(app: FastAPI, runtime: Runtime, *, serve_static=False):
    if serve_static:
        static = Path(__file__).parent / "static"
        app.mount("/static", StaticFiles(directory=static), name="static")

        @app.get("/")
        def index():
            return FileResponse(
                static / "index.html", headers={"Cache-Control": "no-store"}
            )

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method == "POST" and origin:
            if urlsplit(origin).netloc != request.headers.get("host"):
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    {"detail": "Use the app control page"}, status_code=403
                )
        return await call_next(request)

    def player():
        if runtime.player is None:
            raise HTTPException(503, runtime.error or "正在准备音频，请稍候")
        return runtime.player

    @app.get("/api/status")
    def status():
        result = runtime.player.status() if runtime.player else {"state": "unavailable"}
        return {
            **result,
            "ready": runtime.player is not None,
            "output": runtime.output,
            "startup_error": runtime.error,
        }

    @app.get("/api/catalog")
    def catalog():
        if runtime.library is None:
            raise HTTPException(503, runtime.error or "正在加载素材")
        return {"clips": runtime.library.clips}

    @app.post("/api/play/{clip_id}")
    def play(clip_id: str):
        current = player()
        if runtime.library is None or clip_id not in runtime.library.by_id:
            raise HTTPException(404, "找不到这条音频")
        current.play(clip_id)
        return status()

    @app.post("/api/control")
    def control(command: Control):
        getattr(player(), command.action)()
        return status()

    @app.post("/api/volume")
    def volume(command: Volume):
        player().volume(command.value)
        return status()
