#!/bin/bash
set -e
echo "[Radar] Setting up venv..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo "[Radar] Installing Playwright Chromium..."
python -m playwright install chromium --with-deps || python -m playwright install chromium
echo "[Radar] Venv ready. Activate with: source .venv/bin/activate"
echo "Python: $(which python)"
echo "Version: $(python --version)"
