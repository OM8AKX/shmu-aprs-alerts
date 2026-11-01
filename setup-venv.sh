#!/bin/bash
# ============================================================
# Vytvorenie Python venv a inštalácia závislostí
# Použitie (bez root):  ./setup-venv.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/venv}"
PYTHON="${PYTHON:-python3}"

echo "==> SHMÚ APRS Alerts – setup venv"
echo "    Projekt: $SCRIPT_DIR"
echo "    Venv:    $VENV_DIR"
echo "    Python:  $PYTHON"

if ! command -v "$PYTHON" &>/dev/null; then
  echo "Chyba: $PYTHON nie je nainštalovaný."
  echo "  Debian/Ubuntu/RPi:  sudo apt install python3 python3-venv python3-pip"
  exit 1
fi

if ! "$PYTHON" -c "import venv" 2>/dev/null; then
  echo "Chyba: modul venv nie je dostupný."
  echo "  sudo apt install python3-venv"
  exit 1
fi

if [[ -d "$VENV_DIR" ]]; then
  echo "==> Venv už existuje – aktualizujem pip a závislosti"
else
  echo "==> Vytváram venv…"
  "$PYTHON" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "==> pip upgrade…"
pip install --upgrade pip wheel setuptools

echo "==> Inštalácia requirements.txt…"
pip install -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "Hotovo."
echo ""
echo "Aktivácia venv:"
echo "  source $VENV_DIR/bin/activate"
echo ""
echo "Test (jednorazový beh):"
echo "  cp -n config/config.example.yaml config/config.yaml"
echo "  nano config/config.yaml    # callsign + passcode"
echo "  $VENV_DIR/bin/python main.py --config config/config.yaml --once"
echo ""
echo "Systémová inštalácia (systemd):"
echo "  sudo ./install.sh"
