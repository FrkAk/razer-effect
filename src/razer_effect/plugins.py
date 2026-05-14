"""Discover, load, validate, and supervise user-supplied effect plugins.

Plugins are arbitrary user-supplied Python loaded from one of the directories
listed in ``cfg['plugin_paths']`` (default ``~/.config/razer-effect/effects/``).
Loading executes the module via ``importlib.util.exec_module``; the daemon
already runs as the user, so the trust boundary is unchanged. Filenames are
written to ``plugin_status.json`` for the GUI; plugin source and render output
are never persisted.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from typing import TYPE_CHECKING, Any, cast

from razer_effect.config import CONFIG_DIR

if TYPE_CHECKING:
    from pathlib import Path

PLUGIN_STATUS: dict[str, dict[str, Any]] = {}
"""Filename-keyed plugin status: ``{ok, error, disabled, failures}``.

The dict is keyed by filename (``path.name``) for entries written by
``_load_one`` so the GUI can map back to files on disk. Runtime failure
counters tracked by ``record_render_failure`` are keyed by the registry key
(filename stem) handed in by ``compositor.blend`` via ``layer.effect_name``.
"""

STATUS_PATH = CONFIG_DIR / "plugin_status.json"
FAILURE_THRESHOLD = 3

REQUIRED_CLASSVARS: tuple[str, ...] = ("LABEL", "PARAMS", "STATIC")
REQUIRED_METHODS: tuple[str, ...] = ("setup", "configure", "render")


def _validate(effect_cls: type) -> str | None:
    """Return None when the class satisfies the Effect protocol, else a reason.

    Args:
        effect_cls: A class object discovered in a plugin module.

    Returns:
        None on success, or a single-line human-readable reason string on
        failure. Reasons are stable enough for the GUI to display verbatim.
    """
    cls = cast("Any", effect_cls)
    sentinel = object()
    for var in REQUIRED_CLASSVARS:
        if getattr(cls, var, sentinel) is sentinel:
            return f"missing required class attribute: {var}"
    if not isinstance(cls.LABEL, str) or not cls.LABEL:
        return "LABEL must be a non-empty string"
    if not isinstance(cls.PARAMS, dict):
        return "PARAMS must be a dict"
    if not isinstance(cls.STATIC, bool):
        return "STATIC must be a bool"
    for method in REQUIRED_METHODS:
        if not callable(getattr(cls, method, None)):
            return f"missing required method: {method}"
    return None


def _discover_effect_class(module: Any) -> type | None:
    """Return the first module-level class that looks like an Effect.

    The discovery rule is deliberately loose: the first class defined in the
    module (``__module__`` matches the plugin module) that exposes a
    ``LABEL`` attribute. Validation of ``PARAMS``, ``STATIC``, ``setup``,
    ``configure``, and ``render`` is the job of :func:`_validate`, so a class
    missing ``render`` is reported with the precise reason rather than
    silently passed over.

    Args:
        module: A freshly-loaded plugin module.

    Returns:
        The discovered class, or None when no class matches.
    """
    for name in dir(module):
        obj = getattr(module, name)
        if not isinstance(obj, type):
            continue
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        if hasattr(obj, "LABEL"):
            return obj
    return None


def _load_one(path: Path) -> tuple[str, type] | None:
    """Load one ``.py`` file and return ``(registry_key, class)`` on success.

    Args:
        path: Absolute path to a ``.py`` plugin file.

    Returns:
        Tuple of ``(registry_key, effect class)`` on success, ``None`` on
        failure. Side effect: populates ``PLUGIN_STATUS[path.name]`` with
        either ``{ok: True, error: None, disabled: False, failures: 0}`` on
        success or ``{ok: False, error: <reason>, disabled: False,
        failures: 0}`` on failure.
    """
    fname = path.name
    try:
        spec = importlib.util.spec_from_file_location(
            f"_razer_plugin_{path.stem}", path
        )
        if spec is None or spec.loader is None:
            PLUGIN_STATUS[fname] = {
                "ok": False,
                "error": "spec_from_file_location returned None",
                "disabled": False,
                "failures": 0,
            }
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        PLUGIN_STATUS[fname] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "disabled": False,
            "failures": 0,
        }
        print(
            f"razer-effect: plugin {fname!r} failed to load: {exc}",
            file=sys.stderr,
        )
        return None

    effect_cls = _discover_effect_class(module)
    if effect_cls is None:
        PLUGIN_STATUS[fname] = {
            "ok": False,
            "error": "no Effect-shaped class found",
            "disabled": False,
            "failures": 0,
        }
        print(
            f"razer-effect: plugin {fname!r}: no Effect-shaped class found",
            file=sys.stderr,
        )
        return None

    reason = _validate(effect_cls)
    if reason is not None:
        PLUGIN_STATUS[fname] = {
            "ok": False,
            "error": reason,
            "disabled": False,
            "failures": 0,
        }
        print(
            f"razer-effect: plugin {fname!r} rejected: {reason}",
            file=sys.stderr,
        )
        return None

    key = path.stem
    PLUGIN_STATUS[fname] = {
        "ok": True,
        "error": None,
        "disabled": False,
        "failures": 0,
    }
    return key, effect_cls


def load_plugins(paths: list[Path]) -> dict[str, type]:
    """Scan directories for ``*.py`` files and return validated ``{key: cls}``.

    Args:
        paths: Directories to scan. Missing or non-directory entries are
            skipped silently. Files whose name starts with ``_`` are skipped
            (convention for helper modules co-located with plugins).

    Returns:
        Dict mapping registry key (filename stem) to effect class. Side
        effect: populates ``PLUGIN_STATUS`` for every file encountered,
        including failures. Duplicate keys override earlier loads with a
        stderr warning; iteration order is deterministic via
        ``sorted(d.glob('*.py'))``.
    """
    result: dict[str, type] = {}
    for d in paths:
        if not d.is_dir():
            continue
        for py in sorted(d.glob("*.py")):
            if py.name.startswith("_"):
                continue
            loaded = _load_one(py)
            if loaded is None:
                continue
            key, cls = loaded
            if key in result:
                print(
                    f"razer-effect: plugin key {key!r} already registered; "
                    f"overriding with {py}",
                    file=sys.stderr,
                )
            result[key] = cls
    return result


def get_status() -> dict[str, dict[str, Any]]:
    """Return a deep-copied snapshot of ``PLUGIN_STATUS`` for the GUI.

    Returns:
        A new dict mapping plugin keys to status entries. Callers may mutate
        the returned dict without affecting daemon state.
    """
    return {k: dict(v) for k, v in PLUGIN_STATUS.items()}


def write_status_file() -> None:
    """Atomically write ``PLUGIN_STATUS`` to ``STATUS_PATH``.

    Uses the same tmp+rename pattern as ``config.save_config``. Best-effort:
    ``OSError`` is logged to stderr and swallowed so the render loop never
    crashes because the status file could not be written.
    """
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATUS_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(PLUGIN_STATUS, f, indent=2, sort_keys=True)
        os.replace(tmp, STATUS_PATH)
    except OSError as exc:
        print(
            f"razer-effect: could not write {STATUS_PATH}: {exc}",
            file=sys.stderr,
        )


def record_render_failure(plugin_key: str, exc: BaseException) -> bool:
    """Increment the failure counter for ``plugin_key``; return True at threshold.

    Args:
        plugin_key: Registry key of the failing plugin (matches
            ``Layer.effect_name``, which is the filename stem).
        exc: The exception raised by ``render``.

    Returns:
        True iff this call crosses the ``FAILURE_THRESHOLD`` (i.e. the
        counter went from ``THRESHOLD - 1`` to ``THRESHOLD``). False on
        every other call, including failures recorded after the plugin is
        already disabled.
    """
    entry = PLUGIN_STATUS.setdefault(
        plugin_key,
        {"ok": True, "error": None, "disabled": False, "failures": 0},
    )
    if entry["disabled"]:
        return False
    entry["failures"] = int(entry.get("failures", 0)) + 1
    entry["error"] = f"{type(exc).__name__}: {exc}"
    print(
        f"razer-effect: plugin {plugin_key!r} render failed "
        f"({entry['failures']}/{FAILURE_THRESHOLD}): {exc}",
        file=sys.stderr,
    )
    if entry["failures"] >= FAILURE_THRESHOLD:
        entry["disabled"] = True
        entry["ok"] = False
        return True
    return False
