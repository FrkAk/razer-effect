#!/bin/bash
set -e

echo "==> Installing razer-effect..."
pip install --user --break-system-packages .

echo "==> Ensuring openrazer-daemon is enabled..."
systemctl --user enable openrazer-daemon.service 2>/dev/null || true
systemctl --user start openrazer-daemon.service 2>/dev/null || true
sleep 2

echo "==> Installing systemd user service..."
mkdir -p ~/.config/systemd/user
cp razer-effect.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now razer-effect.service

echo "==> Installing icon and desktop entry..."
mkdir -p ~/.local/share/icons/hicolor/scalable/apps
cp razer-effect.svg ~/.local/share/icons/hicolor/scalable/apps/
gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null || true
mkdir -p ~/.local/share/applications
GUI_PATH=$(which razer-effect-gui)
sed "s|Exec=razer-effect-gui|Exec=$GUI_PATH|" razer-effect-gui.desktop > ~/.local/share/applications/io.github.FrkAk.razer-effect.desktop

echo "==> Done! Service is running and will start on login."
echo "    GUI: razer-effect-gui (or search 'Razer Effect' in app launcher)"
echo "    Status: systemctl --user status razer-effect"
