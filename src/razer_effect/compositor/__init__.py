"""Compositor adapters that publish the focused window's class to a shared queue.

This package owns the per-session compositor adapters (X11, Wayland, GNOME)
and the singleton queue they all push to. The rule evaluator drains the queue
to drive per-app profile rules. Each adapter is responsible for starting only
when its session type is active; the queue itself is process-wide and outlives
any individual adapter.
"""

from __future__ import annotations

import queue

window_class_queue: queue.SimpleQueue[str] = queue.SimpleQueue()
