#!/usr/bin/env bash
# Ubuntu: installs system libraries, creates .venv-app in the repository root and installs the dependencies.
# X11 session: works out of the box. Wayland: also needs ydotool 1.x (+ running ydotoold).
set -e
cd "$(dirname "$0")/.."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip xdotool pulseaudio-utils \
    libgl1 libglib2.0-0 libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 libxcb-icccm4 \
    libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0
python3 -m venv .venv-app
.venv-app/bin/pip install --upgrade pip
.venv-app/bin/pip install -r requirements.txt
chmod +x scripts/run.sh
echo "Done. Start: ./scripts/run.sh"
echo "Note: on GNOME the tray icon needs the 'AppIndicator' extension; the camera needs your user in the 'video' group."
