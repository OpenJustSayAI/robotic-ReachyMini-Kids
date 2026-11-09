"""Desktop playback through the computer speaker, with no robot connection."""

import argparse
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from .audio import DesktopSink, Library, asset_directory
from .playback import Player
from .web import Runtime, configure_web


def create_preview(directory: Path):
    runtime = Runtime("这台电脑的扬声器")

    @asynccontextmanager
    async def lifespan(app):
        try:
            runtime.library = Library(directory)
            runtime.player = Player(DesktopSink(), runtime.library.decode)
            runtime.player.start()
        except Exception as exc:
            runtime.error = str(exc)
        try:
            yield
        finally:
            if runtime.player is not None:
                runtime.player.close()
                runtime.player = None

    app = FastAPI(lifespan=lifespan)
    configure_web(app, runtime, serve_static=True)
    return app


def main():
    parser = argparse.ArgumentParser(description="Ducky 原声本地试听（无需机器人）")
    parser.add_argument("--assets", type=Path, default=asset_directory())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8042)
    args = parser.parse_args()
    uvicorn.run(create_preview(args.assets), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
