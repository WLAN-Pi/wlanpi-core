from typing import Optional

from gi.repository import GLib


class GLibLoop:
    """ Provides a wrapper to make handling scoped glib loop runs a little easier"""

    def __init__(
        self,
        loop: Optional[GLib.MainLoop] = None,
        timeout_seconds: Optional[int] = None,
        timeout_callback: Optional[callable] = None,
        timeout_callback_args: Optional[list] = None,
        timeout_callback_kwargs: Optional[dict] = None,
    ):
        self.loop = loop if loop else GLib.MainLoop()
        self.timeout_seconds = timeout_seconds
        self.timeout_callback = timeout_callback
        self.timeout_callback_args = timeout_callback_args
        self.timeout_callback_kwargs = timeout_callback_kwargs
        self.timeout_source: Optional[GLib.Source] = None
        self.timeout_source_attachment: Optional[int] = None

    def start_timeout(
        self,
        seconds: Optional[int] = None,
        callback: Optional[callable] = None,
        *args,
        **kwargs
    ):
        self.timeout_source = GLib.timeout_source_new_seconds(
            seconds if seconds else self.timeout_seconds
        )
        self.timeout_source.set_callback(
            callback if callback else self.timeout_callback,
            *(args or self.timeout_callback_args or []),
            **(kwargs or self.timeout_callback_kwargs or {})
        )
        self.timeout_source_attachment = self.timeout_source.attach(
            self.loop.get_context()
        )

    def stop_timeout(self):
        if self.timeout_source and self.timeout_source_attachment:
            self.timeout_source.remove(self.timeout_source_attachment)

    def finish(self):
        self.stop_timeout()
        self.loop.quit()

    def run(self, *args, **kwargs):
        self.loop.run(*args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_timeout()
        self.loop.quit()
