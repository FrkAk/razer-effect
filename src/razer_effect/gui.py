"""GTK4 + Adwaita settings UI for razer-effect."""

import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from razer_effect.config import load_config, save_config, ensure_config  # noqa: E402


class RazerEffectWindow(Adw.ApplicationWindow):
    """Main settings window."""

    def __init__(self, **kwargs):
        """Initialize the settings window.

        Args:
            **kwargs: Passed to Adw.ApplicationWindow.
        """
        super().__init__(**kwargs, title="Razer Effect", default_width=420, default_height=580)

        self._saving = False
        self._cfg = ensure_config()

        content = Adw.ToolbarView()
        content.add_top_bar(Adw.HeaderBar())

        toast_overlay = Adw.ToastOverlay()
        self._toast_overlay = toast_overlay

        page = Adw.PreferencesPage()

        # --- Service status banner ---
        self._banner = Adw.Banner(title="Effect service is not running")
        self._banner.set_button_label("Start Service")
        self._banner.connect("button-clicked", self._on_start_service)
        toast_overlay.set_child(page)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self._banner)
        box.append(toast_overlay)
        content.set_content(box)
        self.set_content(content)

        self._check_service_status()

        # --- Effect selector ---
        effect_group = Adw.PreferencesGroup(title="Effect")
        effects = Gtk.StringList.new(["Random Fade"])
        self._effect_row = Adw.ComboRow(title="Effect", model=effects)
        effect_group.add(self._effect_row)
        page.add(effect_group)

        # --- Parameters ---
        params_group = Adw.PreferencesGroup(title="Parameters")

        self._fade_duration = self._add_spin_row(
            params_group, "Fade Duration", "Seconds per fade transition",
            0.5, 5.0, 0.1, 1, self._cfg["fade_duration"],
        )
        self._fade_fps = self._add_spin_row(
            params_group, "FPS", "Frames per second",
            12, 60, 1, 0, self._cfg["fade_fps"],
        )
        self._brightness = self._add_spin_row(
            params_group, "Brightness", "Keyboard brightness (0-100)",
            0, 100, 1, 0, self._cfg.get("brightness", 75) or 75,
        )
        self._hold_min = self._add_spin_row(
            params_group, "Hold Min", "Minimum seconds before color change",
            0.5, 10.0, 0.1, 1, self._cfg["hold_min"],
        )
        self._hold_max = self._add_spin_row(
            params_group, "Hold Max", "Maximum seconds before color change",
            0.5, 10.0, 0.1, 1, self._cfg["hold_max"],
        )
        page.add(params_group)

        # --- Control ---
        control_group = Adw.PreferencesGroup(title="Control")
        self._running_row = Adw.SwitchRow(title="Running", subtitle="Toggle the effect on/off")
        self._running_row.set_active(self._cfg.get("running", True))
        self._running_row.connect("notify::active", self._on_changed)
        control_group.add(self._running_row)
        page.add(control_group)

    def _add_spin_row(self, group, title, subtitle, lower, upper, step, digits, value):
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

    def _on_changed(self, *_args):
        """Save config when any widget value changes."""
        if self._saving:
            return
        self._saving = True

        hold_min = self._hold_min.get_value()
        hold_max = self._hold_max.get_value()
        if hold_max < hold_min:
            self._hold_max.set_value(hold_min)
            hold_max = hold_min

        self._cfg.update({
            "effect": "random_fade",
            "fade_duration": round(self._fade_duration.get_value(), 1),
            "fade_fps": int(self._fade_fps.get_value()),
            "brightness": int(self._brightness.get_value()),
            "hold_min": round(hold_min, 1),
            "hold_max": round(hold_max, 1),
            "running": self._running_row.get_active(),
        })
        save_config(self._cfg)
        self._saving = False

    def _check_service_status(self):
        """Check if the systemd user service is active."""
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "razer-effect.service"],
            capture_output=True, text=True,
        )
        active = result.stdout.strip() == "active"
        self._banner.set_revealed(not active)

    def _on_start_service(self, *_args):
        """Start the systemd user service."""
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

    def __init__(self):
        """Initialize the application."""
        super().__init__(application_id="io.github.FrkAk.razer-effect")

    def do_activate(self):
        """Show the main window on activation."""
        win = self.get_active_window()
        if not win:
            win = RazerEffectWindow(application=self)
        win.present()


def main():
    """Entry point for razer-effect-gui."""
    app = RazerEffectApp()
    app.run(sys.argv)
