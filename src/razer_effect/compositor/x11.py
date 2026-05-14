"""X11 focused-window adapter that publishes WM_CLASS strings to the shared queue.

Polls `_NET_ACTIVE_WINDOW` on the root window and `WM_CLASS` on the active
window via python-xlib every 500ms. The lowercase instance name (first token
of `WM_CLASS`) is pushed to `window_class_queue` only on transitions, so the
queue never accumulates duplicate consecutive entries.

Known limitations:
    Native Wayland applications running under XWayland do not set `WM_CLASS`
    and are therefore invisible to this adapter; the Wayland adapter (RZE-35)
    covers them.

The adapter is a no-op when `DISPLAY` is unset, when `python-xlib` is not
installed, or when the display connection cannot be established. In all three
cases a single stderr line is logged and the daemon continues running.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import queue

POLL_INTERVAL_SECONDS = 0.5
_NET_ACTIVE_WINDOW_ATOM = "_NET_ACTIVE_WINDOW"
WM_CLASS_ATOM = "WM_CLASS"


class X11Adapter:
    """Daemon-thread poller that publishes the focused X11 window's class.

    Owns a single long-lived `Xlib.display.Display` connection and a poll
    thread. Both are created lazily on `start()` so importing this module on a
    pure-Wayland or headless host does not touch python-xlib. The shared queue
    is injected so the package init owns its lifetime and tests can substitute
    a private queue.
    """

    def __init__(
        self,
        queue: queue.SimpleQueue[str],
        interval: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        """Build an adapter that publishes to the given queue.

        Args:
            queue: Destination for window-class strings. Adapters share the
                module-level `window_class_queue` from
                `razer_effect.compositor` in production.
            interval: Seconds between polls. Defaults to
                POLL_INTERVAL_SECONDS; tests override with a small value to
                exercise the loop fast.
        """
        self._queue = queue
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_class: str | None = None
        self._display: Any = None
        self._atom_active: int | None = None
        self._atom_wm_class: int | None = None
        self._x: Any = None
        self._xerror: Any = None

    def start(self) -> None:
        """Connect to the X server and spawn the poll thread if possible.

        Idempotent: returns immediately if the worker is already alive. Skips
        startup silently (with a single stderr warning) when `DISPLAY` is
        unset, when `python-xlib` is not installed, or when the display
        connection cannot be opened. No exception escapes.
        """
        if self._thread is not None and self._thread.is_alive():
            return

        display_name = os.environ.get("DISPLAY")
        if not display_name:
            print(
                "razer-effect: X11 adapter skipped (DISPLAY unset)",
                file=sys.stderr,
            )
            return

        try:
            from Xlib import X
            from Xlib import display as xdisplay
            from Xlib import error as xerror
        except ImportError:
            print(
                "razer-effect: X11 adapter skipped (python-xlib not installed)",
                file=sys.stderr,
            )
            return

        try:
            self._display = xdisplay.Display(display_name)
        except (xerror.DisplayNameError, xerror.DisplayConnectionError) as e:
            print(
                f"razer-effect: X11 adapter skipped (display connect failed: {e})",
                file=sys.stderr,
            )
            self._display = None
            return

        self._atom_active = self._display.intern_atom(_NET_ACTIVE_WINDOW_ATOM)
        self._atom_wm_class = self._display.intern_atom(WM_CLASS_ATOM)
        self._x = X
        self._xerror = xerror

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="x11-compositor-adapter", daemon=True
        )
        self._thread.start()
        print("razer-effect: X11 adapter started", file=sys.stderr)

    def stop(self) -> None:
        """Signal the worker to exit and join it.

        Test teardown only; production relies on daemon-thread auto-termination
        on process exit. Sets the stop event and joins with a 1-second timeout.
        Idempotent on a never-started adapter.
        """
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        """Run the polling loop until stopped, then close the display.

        Performs an immediate tick so the first reading lands within one
        cycle of start(), then sleeps on the stop event for the configured
        interval between subsequent ticks. The display connection is closed
        in a finally block so an unexpected thread exit cannot leak the fd.
        """
        try:
            self._tick()
            while not self._stop.wait(self._interval):
                self._tick()
        finally:
            if self._display is not None:
                with contextlib.suppress(Exception):
                    self._display.close()
                self._display = None

    def _tick(self) -> None:
        """Read `_NET_ACTIVE_WINDOW` and `WM_CLASS` once and publish on change.

        Catches `Xlib.error.XError` (parent of `BadWindow`) to absorb the
        race where the active window is destroyed between the two property
        reads. On error the last-known class is retained so the next
        successful tick still emits only on a true transition.
        """
        try:
            assert self._display is not None
            assert self._atom_active is not None
            assert self._atom_wm_class is not None
            assert self._x is not None

            root = self._display.screen().root
            prop = root.get_full_property(self._atom_active, self._x.AnyPropertyType)
            if prop is None or not prop.value:
                return
            window_id = int(prop.value[0])
            if window_id == 0:
                return

            win = self._display.create_resource_object("window", window_id)
            wm_class = win.get_wm_class()
            if wm_class is None:
                return

            class_str = wm_class[0].lower()
            if class_str != self._last_class:
                self._queue.put(class_str)
                self._last_class = class_str
        except self._xerror.XError:
            return
