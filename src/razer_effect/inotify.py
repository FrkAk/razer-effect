"""Linux inotify wrapper for config file watching via ctypes."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

IN_CLOSE_WRITE = 0x00000008
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_NONBLOCK = 0x00000800
EVENT_HEADER_SIZE = 16
READ_BUFFER_SIZE = 4096

_libc_name = ctypes.util.find_library("c")
_libc = ctypes.CDLL(_libc_name, use_errno=True)


class ConfigWatcher:
    """Watches a config file for changes using Linux inotify on the parent directory.

    Watches the parent directory instead of the file directly so that atomic
    writes (write to .tmp then os.replace) are detected. Filters events by
    the target filename.
    """

    def __init__(self, path: Path) -> None:
        """Create an inotify watcher for the given file path.

        Watches the parent directory for create, move-to, and close-write
        events matching the target filename.

        Args:
            path: Path to the config file to watch.

        Raises:
            OSError: If inotify initialization or watch setup fails.
        """
        self._filename = str(path.name).encode()

        self._fd = _libc.inotify_init1(IN_NONBLOCK)
        if self._fd < 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))

        dir_bytes = str(path.parent).encode()
        mask = IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE
        self._wd = _libc.inotify_add_watch(self._fd, dir_bytes, mask)
        if self._wd < 0:
            errno = ctypes.get_errno()
            os.close(self._fd)
            raise OSError(errno, os.strerror(errno))

    def has_changed(self) -> bool:
        """Check if the watched config file has been modified.

        Non-blocking: returns immediately if no events are pending.
        Drains all pending events and returns True only if any match
        the target filename.

        Returns:
            True if the config file was modified, False otherwise.
        """
        try:
            data = os.read(self._fd, READ_BUFFER_SIZE)
        except BlockingIOError:
            return False

        changed = False
        offset = 0
        while offset < len(data):
            _wd, _mask, _cookie, name_len = struct.unpack_from("iIII", data, offset)
            offset += EVENT_HEADER_SIZE
            name = data[offset : offset + name_len].rstrip(b"\x00")
            offset += name_len
            if name == self._filename:
                changed = True

        return changed

    def close(self) -> None:
        """Close the inotify file descriptor and release resources."""
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
