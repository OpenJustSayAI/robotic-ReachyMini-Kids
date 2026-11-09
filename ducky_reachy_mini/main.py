# Based on the Pollen Robotics App Assistant template (Apache-2.0).
# Modified for Ducky: original-voice player, parent controls, no motor commands.
"""Standard Reachy Mini app. Run on the Wireless robot through its app manager."""

import threading

from reachy_mini import ReachyMini, ReachyMiniApp

from .audio import Library, ReachySink, asset_directory
from .playback import Player
from .web import Runtime, configure_web


class DuckyReachyMini(ReachyMiniApp):
    custom_app_url = "http://0.0.0.0:8042"
    request_media_backend = "gstreamer_no_video"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runtime = Runtime("Reachy Mini 扬声器")
        if self.settings_app is not None:
            configure_web(self.settings_app, self.runtime)

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event):
        player = None
        try:
            self.runtime.library = Library(asset_directory())
            player = Player(ReachySink(reachy_mini.media), self.runtime.library.decode)
            player.start()
            self.runtime.player = player
            stop_event.wait()
        except Exception as exc:
            self.runtime.error = str(exc)
            self.logger.exception("Ducky playback could not start")
            # Keep the parent page available to explain a missing bundle/device.
            stop_event.wait()
        finally:
            self.runtime.player = None
            if player is not None:
                player.close()


if __name__ == "__main__":
    app = DuckyReachyMini()
    try:
        app.wrapped_run()
    except KeyboardInterrupt:
        app.stop()
