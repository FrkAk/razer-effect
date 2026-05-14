"""UPower D-Bus reader for battery percentage with non-blocking background polling.

On systems without a battery (desktop, IsPresent=False), the public API
returns None so profile rules can be skipped silently. Any dbus error is
swallowed and reported as None for the same reason: the daemon must never
crash because UPower is missing or restarting.
"""

from __future__ import annotations

import sys
import threading

UPOWER_BUS = "org.freedesktop.UPower"
UPOWER_DISPLAY_DEVICE = "/org/freedesktop/UPower/devices/DisplayDevice"
UPOWER_DEVICE_IFACE = "org.freedesktop.UPower.Device"
POLL_INTERVAL_SECONDS = 30.0


class BatteryReadError(Exception):
    """Raised internally when the UPower D-Bus read fails.

    Callers of the public API never see this; it is caught at the boundary
    and converted to None so battery rules can degrade silently.
    """


def read_battery() -> tuple[float, bool] | None:
    """Read the current battery percentage and presence from UPower.

    Connects to the system D-Bus, fetches the DisplayDevice's IsPresent
    and Percentage properties, and returns them. Returns None when no
    battery is present, when dbus is unreachable, or when UPower is
    unavailable. Never raises.

    Returns:
        A tuple (percentage, is_present) with percentage in [0.0, 100.0]
        when a battery is present, otherwise None. The is_present flag is
        always True in the returned tuple; callers do not need to inspect it
        but it is retained for forward use (charge-state rules in a future
        iteration).
    """
    try:
        import dbus

        bus = dbus.SystemBus()
        proxy = bus.get_object(UPOWER_BUS, UPOWER_DISPLAY_DEVICE)
        props = dbus.Interface(proxy, "org.freedesktop.DBus.Properties")
        is_present = bool(props.Get(UPOWER_DEVICE_IFACE, "IsPresent"))
        if not is_present:
            return None
        percentage = float(props.Get(UPOWER_DEVICE_IFACE, "Percentage"))
        return (percentage, True)
    except Exception as e:
        print(f"razer-effect: battery read failed: {e}", file=sys.stderr)
        return None


class BatteryPoller:
    """Background poller that refreshes the battery snapshot every 30 seconds.

    The poller owns a daemon thread that calls read_battery() on a fixed
    cadence and publishes the latest result under a lock. Consumers read
    via snapshot() without blocking the render loop.
    """

    def __init__(self, interval: float = POLL_INTERVAL_SECONDS) -> None:
        """Build a poller with the given tick interval.

        Args:
            interval: Seconds between ticks. Defaults to POLL_INTERVAL_SECONDS;
                tests override with a small value to exercise the loop fast.
        """
        self._interval = interval
        self._lock = threading.Lock()
        self._snapshot: tuple[float, bool] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background daemon thread if not already running.

        Idempotent: if the worker is already alive, return without spawning
        a second thread. The worker is created with daemon=True so it
        terminates automatically when the process exits.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="battery-poller", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the worker to exit and join it.

        Test teardown only; production relies on daemon thread auto-termination
        on process exit. Sets the stop event and joins with a 1-second timeout.
        Idempotent on a never-started poller.
        """
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def snapshot(self) -> tuple[float, bool] | None:
        """Return the latest battery reading under the lock.

        Returns:
            The most recent (percentage, is_present) tuple, or None when no
            successful read has happened yet or no battery is present.
        """
        with self._lock:
            return self._snapshot

    def _loop(self) -> None:
        """Run the polling loop until stopped.

        Performs an immediate tick so the first reading lands within seconds
        of start(), then sleeps on the stop event for the configured interval
        between subsequent ticks.
        """
        self._tick()
        while not self._stop.wait(self._interval):
            self._tick()

    def _tick(self) -> None:
        """Read the battery once and publish the result under the lock."""
        result = read_battery()
        with self._lock:
            self._snapshot = result


_default_poller: BatteryPoller | None = None


def get_default_poller() -> BatteryPoller:
    """Return the process-wide BatteryPoller, lazily starting it on first use.

    Returns:
        The singleton BatteryPoller, with its thread already started.
    """
    global _default_poller
    if _default_poller is None:
        _default_poller = BatteryPoller()
        _default_poller.start()
    return _default_poller
