#!/bin/bash
set -e

echo "==> Stopping and removing service..."
systemctl --user disable --now razer-effect.service 2>/dev/null || true
rm -f ~/.config/systemd/user/razer-effect.service
systemctl --user daemon-reload

echo "==> Removing desktop entry, icon, and config..."
rm -f ~/.local/share/applications/io.github.FrkAk.razer-effect.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/razer-effect.svg
gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null || true
rm -rf ~/.config/razer-effect

echo "==> Uninstalling razer-effect..."
pip uninstall -y razer-effect 2>/dev/null || true

echo "==> Done!"
