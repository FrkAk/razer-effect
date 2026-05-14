"""Profile rule callables.

Each rule class exposes a stable `evaluate() -> str | None` method. The
priority chain (RZE-33) calls each rule in order and activates the first
non-None result.
"""

from __future__ import annotations

from typing import Any, TypedDict

from razer_effect.battery import BatteryPoller, get_default_poller


class BatteryRuleEntry(TypedDict):
    """One battery rule loaded from config.

    Attributes:
        threshold: Activate the profile when battery is strictly below this
            integer percentage (0-100).
        profile: Name of the target profile.
    """

    threshold: int
    profile: str


class BatteryRule:
    """Battery-percentage-driven profile selector.

    Reads the latest battery snapshot from a BatteryPoller and returns the
    matching profile name from the configured rule list, or None when no
    rule matches or no battery is present.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        poller: BatteryPoller | None = None,
    ) -> None:
        """Build a battery rule evaluator.

        Args:
            cfg: The current config dict. The rule reads `cfg["battery_rules"]`
                lazily on each evaluate() call so live config reloads land
                without re-instantiation.
            poller: Optional BatteryPoller override (tests); defaults to the
                process singleton via get_default_poller().
        """
        self._cfg = cfg
        self._poller = poller or get_default_poller()

    def configure(self, cfg: dict[str, Any]) -> None:
        """Swap the active config reference.

        Args:
            cfg: Updated config dict. Subsequent evaluate() calls use this dict.
        """
        self._cfg = cfg

    def evaluate(self) -> str | None:
        """Pick the battery-rule profile for the current battery level.

        Reads the poller snapshot. If no battery is present or no rules are
        configured, returns None. Otherwise selects the rule with the lowest
        threshold strictly greater than the current percentage — i.e., the
        most-specific "below X%" rule that fires.

        Returns:
            Profile name to activate, or None when no rule fires.
        """
        snapshot = self._poller.snapshot()
        if snapshot is None:
            return None
        percentage, _present = snapshot
        rules = self._cfg.get("battery_rules", [])
        if not rules:
            return None
        valid = [r for r in rules if _is_valid_entry(r) and percentage < r["threshold"]]
        if not valid:
            return None
        matched = min(valid, key=lambda r: r["threshold"])
        return matched["profile"]


def _is_valid_entry(entry: Any) -> bool:
    """Return True when entry is a well-formed BatteryRuleEntry.

    Args:
        entry: Candidate rule from the config list.

    Returns:
        True if entry is a dict with int threshold in [0, 100] and a
        non-empty str profile name. False for any malformed shape.
    """
    if not isinstance(entry, dict):
        return False
    threshold = entry.get("threshold")
    profile = entry.get("profile")
    if not isinstance(threshold, int) or isinstance(threshold, bool):
        return False
    if not 0 <= threshold <= 100:
        return False
    return isinstance(profile, str) and bool(profile)
