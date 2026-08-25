#!/bin/bash
# Double-click to open the setup window (macOS).
# On the first run this creates the virtual environment and installs the
# Python libraries, which can take a few minutes.
cd "$(dirname "$0")" || exit 1

echo "Preparing the Moodle Assistant setup..."

if ! command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "Python 3 was not found."
    echo "Install it from https://www.python.org/downloads/ and run this again."
    echo ""
    read -r -p "Press Enter to close..."
    exit 1
fi

if [ ! -d venv ]; then
    echo "First-time setup. This can take a few minutes..."
    python3 -m venv venv || {
        read -r -p "Could not create the virtual environment. Press Enter to close..."
        exit 1
    }
fi

# shellcheck disable=SC1091
source venv/bin/activate

# Reinstall only when requirements.txt is newer than the last install.
STAMP="venv/.requirements-stamp"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
    echo "Installing the required libraries..."
    pip install -q --upgrade pip
    pip install -q -r requirements.txt || {
        read -r -p "Installation failed. Press Enter to close..."
        exit 1
    }
    touch "$STAMP"
fi

echo "Opening the setup window."
python setup_gui.py

echo ""
read -r -p "Finished. Press Enter to close..."
