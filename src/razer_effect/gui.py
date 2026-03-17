"""GTK4 + Adwaita settings UI for razer-effect."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402  # ty: ignore[unresolved-import]

from razer_effect.config import ensure_config, save_config  # noqa: E402
from razer_effect.effects import EFFECTS  # noqa: E402


class RazerEffectWindow(Adw.ApplicationWindow):
    """Main settings window."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the settings window.

        Args:
            **kwargs: Passed to Adw.ApplicationWindow.
        """
        super().__init__(
            **kwargs, title="Razer Effect", default_width=420, default_height=580
        )

        self._saving = False
        self._cfg = ensure_config()
        self._param_widgets: dict[str, Adw.SpinRow] = {}
        self._effect_names = list(EFFECTS.keys())

        content = Adw.ToolbarView()
        content.add_top_bar(Adw.HeaderBar())

        self._toast_overlay = Adw.ToastOverlay()

        page = Adw.PreferencesPage()

        self._banner = Adw.Banner(title="Effect service is not running")
        self._banner.set_button_label("Start Service")
        self._banner.connect("button-clicked", self._on_start_service)
        self._toast_overlay.set_child(page)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self._banner)
        box.append(self._toast_overlay)
        content.set_content(box)
        self.set_content(content)

        self._check_service_status()

        self._build_effect_selector(page)
        self._build_global_params(page)
        self._params_group = Adw.PreferencesGroup(title="Effect Parameters")
        page.add(self._params_group)
        self._build_param_widgets(self._cfg.get("effect", "key_shuffle"))
        self._build_control(page)

    def _build_effect_selector(self, page: Adw.PreferencesPage) -> None:
        """Build the effect type selector combo row.

        Args:
            page: The preferences page to add the group to.
        """
        group = Adw.PreferencesGroup(title="Effect")
        labels = [EFFECTS[name].LABEL for name in self._effect_names]
        effects_model = Gtk.StringList.new(labels)
        self._effect_row = Adw.ComboRow(title="Effect", model=effects_model)

        current = self._cfg.get("effect", "key_shuffle")
        if current in self._effect_names:
            self._effect_row.set_selected(self._effect_names.index(current))

        self._effect_row.connect("notify::selected", self._on_effect_changed)
        group.add(self._effect_row)
        page.add(group)

    def _build_global_params(self, page: Adw.PreferencesPage) -> None:
        """Build global parameter widgets (FPS, brightness).

        Args:
            page: The preferences page to add the group to.
        """
        group = Adw.PreferencesGroup(title="Global")
        self._fps = self._make_spin_row(
            group, "FPS", "Frames per second", 12, 60, 1, 0, self._cfg.get("fps", 24)
        )
        self._brightness = self._make_spin_row(
            group,
            "Brightness",
            "Keyboard brightness (0-100)",
            0,
            100,
            1,
            0,
            self._cfg.get("brightness", 75) or 75,
        )
        page.add(group)

    def _build_param_widgets(self, effect_name: str) -> None:
        """Clear and rebuild parameter widgets for the selected effect.

        Args:
            effect_name: The effect key from EFFECTS registry.
        """
        for widget in list(self._param_widgets.values()):
            self._params_group.remove(widget)
        self._param_widgets.clear()

        effect_cls = EFFECTS.get(effect_name)
        if effect_cls is None:
            return

        for name, schema in effect_cls.PARAMS.items():
            value = self._cfg.get(name, schema["default"])
            row = self._make_spin_row(
                self._params_group,
                schema["label"],
                schema["subtitle"],
                schema["min"],
                schema["max"],
                schema["step"],
                schema["digits"],
                value,
            )
            self._param_widgets[name] = row

    def _build_control(self, page: Adw.PreferencesPage) -> None:
        """Build the running toggle control group.

        Args:
            page: The preferences page to add the group to.
        """
        group = Adw.PreferencesGroup(title="Control")
        self._running_row = Adw.SwitchRow(
            title="Running", subtitle="Toggle the effect on/off"
        )
        self._running_row.set_active(self._cfg.get("running", True))
        self._running_row.connect("notify::active", self._on_changed)
        group.add(self._running_row)
        page.add(group)

    def _make_spin_row(
        self,
        group: Adw.PreferencesGroup,
        title: str,
        subtitle: str,
        lower: float,
        upper: float,
        step: float,
        digits: int,
        value: float,
    ) -> Adw.SpinRow:
        """Create and add an Adw.SpinRow to a preferences group.

        Args:
            group: The Adw.PreferencesGroup to add to.
            title: Row title.
            subtitle: Row subtitle.
            lower: Minimum value.
            upper: Maximum value.
            step: Step increment.
            digits: Decimal digits to display.
            value: Initial value.

        Returns:
            The created Adw.SpinRow.
        """
        adj = Gtk.Adjustment(value=value, lower=lower, upper=upper, step_increment=step)
        row = Adw.SpinRow(title=title, subtitle=subtitle, adjustment=adj, digits=digits)
        row.connect("notify::value", self._on_changed)
        group.add(row)
        return row

    def _on_effect_changed(self, *_args: Any) -> None:
        """Handle effect selection change.

        Args:
            *_args: GTK signal arguments, ignored.
        """
        effect_name = self._effect_names[self._effect_row.get_selected()]
        self._cfg["effect"] = effect_name
        self._build_param_widgets(effect_name)
        self._on_changed()

    def _on_changed(self, *_args: Any) -> None:
        """Save config when any widget value changes.

        Args:
            *_args: GTK signal arguments, ignored.
        """
        if self._saving:
            return
        self._saving = True

        effect_name = self._effect_names[self._effect_row.get_selected()]
        self._cfg["effect"] = effect_name
        self._cfg["fps"] = int(self._fps.get_value())
        self._cfg["brightness"] = int(self._brightness.get_value())
        self._cfg["running"] = self._running_row.get_active()

        effect_cls = EFFECTS.get(effect_name)
        if effect_cls:
            for name, widget in self._param_widgets.items():
                schema = effect_cls.PARAMS[name]
                self._cfg[name] = round(widget.get_value(), schema["digits"])

        save_config(self._cfg)
        self._saving = False

    def _check_service_status(self) -> None:
        """Check if the systemd user service is active and update banner."""
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "razer-effect.service"],
            capture_output=True,
            text=True,
        )
        active = result.stdout.strip() == "active"
        self._banner.set_revealed(not active)

    def _on_start_service(self, *_args: Any) -> None:
        """Start the systemd user service.

        Args:
            *_args: GTK signal arguments, ignored.
        """
        result = subprocess.run(
            ["systemctl", "--user", "start", "razer-effect.service"],
            capture_output=True,
        )
        self._check_service_status()
        if result.returncode == 0:
            self._toast_overlay.add_toast(Adw.Toast(title="Service started"))
        else:
            self._toast_overlay.add_toast(Adw.Toast(title="Failed to start service"))


class RazerEffectApp(Adw.Application):
    """GTK Application wrapper."""

    def __init__(self) -> None:
        """Initialize the application."""
        super().__init__(application_id="io.github.FrkAk.razer-effect")

    def do_activate(self) -> None:
        """Show the main window on activation."""
        win = self.get_active_window()
        if not win:
            win = RazerEffectWindow(application=self)
        win.present()


def main() -> None:
    """Entry point for razer-effect-gui."""
    app = RazerEffectApp()
    app.run(sys.argv)
