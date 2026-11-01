#!/bin/bash
# Rýchla inštalácia na Raspberry Pi / Debian
set -euo pipefail

PREFIX="${PREFIX:-/opt/shmu-aprs-alerts}"
CONFIG_DIR="${CONFIG_DIR:-/etc/shmu-aprs}"
SERVICE_USER="${SERVICE_USER:-aprs}"

echo "==> Inštalácia SHMÚ APRS Alerts do $PREFIX"

if [[ $EUID -ne 0 ]]; then
  echo "Spusti ako root (sudo ./install.sh)"
  exit 1
fi

apt-get update -qq
apt-get install -y -qq python3-venv python3-pip

if ! id "$SERVICE_USER" &>/dev/null; then
  useradd -r -s /usr/sbin/nologin -d "$PREFIX" "$SERVICE_USER"
fi

mkdir -p "$PREFIX"
cp -a . "$PREFIX/"
chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX"

echo "==> Vytváram Python venv v $PREFIX/venv …"
if [[ -d "$PREFIX/venv" ]]; then
  echo "    (venv už existuje – preinštalujem závislosti)"
else
  sudo -u "$SERVICE_USER" python3 -m venv "$PREFIX/venv"
fi
sudo -u "$SERVICE_USER" "$PREFIX/venv/bin/pip" install --upgrade pip wheel setuptools
sudo -u "$SERVICE_USER" "$PREFIX/venv/bin/pip" install -r "$PREFIX/requirements.txt"
echo "==> Venv pripravený: $PREFIX/venv/bin/python"

mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
  cp "$PREFIX/config/config.example.yaml" "$CONFIG_DIR/config.yaml"
  echo "!! Uprav $CONFIG_DIR/config.yaml (callsign + passcode) !!"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR"
chmod 640 "$CONFIG_DIR/config.yaml"

touch /var/log/shmu-aprs-alerts.log
chown "$SERVICE_USER:$SERVICE_USER" /var/log/shmu-aprs-alerts.log

cp "$PREFIX/systemd/shmu-aprs-alerts.service" /etc/systemd/system/
sed -i "s|/opt/shmu-aprs-alerts|$PREFIX|g" /etc/systemd/system/shmu-aprs-alerts.service

systemctl daemon-reload
systemctl enable shmu-aprs-alerts.service

echo ""
echo "Hotovo. Ďalšie kroky:"
echo "  1. nano $CONFIG_DIR/config.yaml   # nastav callsign a passcode"
echo "  2. systemctl start shmu-aprs-alerts"
echo "  3. journalctl -u shmu-aprs-alerts -f"
echo ""
echo "Test: $PREFIX/venv/bin/python $PREFIX/main.py -c $CONFIG_DIR/config.yaml --once"
