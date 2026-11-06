#!/bin/bash
# Automatická aktualizácia SHMÚ APRS Alerts z GitHubu
# Použitie:
#   sudo ./update.sh              # aktualizuj + reštart služby
#   sudo ./update.sh --check      # len skontroluj, či je nová verzia
#   sudo ./update.sh --no-restart # aktualizuj kód, nespúšťaj reštart
#   sudo ./update.sh --deps       # vždy preinštaluj pip závislosti
#
# Cron (každý deň o 4:15):
#   15 4 * * * /opt/shmu-aprs-alerts/update.sh >> /var/log/shmu-aprs-update.log 2>&1

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/OM8AKX/shmu-aprs-alerts.git}"
BRANCH="${BRANCH:-main}"
PREFIX="${PREFIX:-/opt/shmu-aprs-alerts}"
CONFIG_DIR="${CONFIG_DIR:-/etc/shmu-aprs}"
SERVICE_USER="${SERVICE_USER:-aprs}"
SERVICE_NAME="${SERVICE_NAME:-shmu-aprs-alerts}"
WORKDIR="${WORKDIR:-/tmp/shmu-aprs-alerts-update}"

CHECK_ONLY=0
NO_RESTART=0
FORCE_DEPS=0

for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --no-restart) NO_RESTART=1 ;;
    --deps) FORCE_DEPS=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "Neznámy argument: $arg (použi --help)"
      exit 1
      ;;
  esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Spusti ako root: sudo $0"
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  log "Inštalujem git…"
  apt-get update -qq
  apt-get install -y -qq git
fi

rm -rf "$WORKDIR"
log "Sťahujem $REPO_URL ($BRANCH)…"
git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$WORKDIR"

REMOTE_SHA=$(git -C "$WORKDIR" rev-parse HEAD)
REMOTE_SHORT=${REMOTE_SHA:0:7}

LOCAL_SHA=""
if [[ -f "$PREFIX/.git-revision" ]]; then
  LOCAL_SHA=$(cat "$PREFIX/.git-revision" 2>/dev/null || true)
fi
# fallback: skús z vnoreného .git ak existuje
if [[ -z "$LOCAL_SHA" && -d "$PREFIX/.git" ]]; then
  LOCAL_SHA=$(git -C "$PREFIX" rev-parse HEAD 2>/dev/null || true)
fi

if [[ -n "$LOCAL_SHA" && "$LOCAL_SHA" == "$REMOTE_SHA" ]]; then
  log "Už je aktuálne ($REMOTE_SHORT). Nič nerobím."
  rm -rf "$WORKDIR"
  exit 0
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
  log "Dostupná nová verzia: ${LOCAL_SHA:0:7:-unknown} → $REMOTE_SHORT"
  rm -rf "$WORKDIR"
  exit 2
fi

log "Aktualizujem $PREFIX  (${LOCAL_SHA:0:7:-none} → $REMOTE_SHORT)"

# Záloha configu nie je potrebná – žije v $CONFIG_DIR mimo PREFIX
mkdir -p "$PREFIX"

# Skopíruj kód (bez .git)
rsync -a --delete \
  --exclude '.git' \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'config/config.yaml' \
  "$WORKDIR/" "$PREFIX/"

echo "$REMOTE_SHA" > "$PREFIX/.git-revision"

# Venv + závislosti
if [[ ! -x "$PREFIX/venv/bin/python" ]]; then
  log "Vytváram venv…"
  if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /usr/sbin/nologin -d "$PREFIX" "$SERVICE_USER"
  fi
  sudo -u "$SERVICE_USER" python3 -m venv "$PREFIX/venv"
  FORCE_DEPS=1
fi

if [[ $FORCE_DEPS -eq 1 ]] || ! cmp -s "$WORKDIR/requirements.txt" "$PREFIX/requirements.txt.bak" 2>/dev/null; then
  log "Aktualizujem Python závislosti…"
  sudo -u "$SERVICE_USER" "$PREFIX/venv/bin/pip" install -q --upgrade pip wheel setuptools
  sudo -u "$SERVICE_USER" "$PREFIX/venv/bin/pip" install -q -r "$PREFIX/requirements.txt"
  cp "$PREFIX/requirements.txt" "$PREFIX/requirements.txt.bak"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX"

# systemd unit (ak sa zmenil)
if [[ -f "$PREFIX/systemd/${SERVICE_NAME}.service" ]]; then
  cp "$PREFIX/systemd/${SERVICE_NAME}.service" "/etc/systemd/system/${SERVICE_NAME}.service"
  sed -i "s|/opt/shmu-aprs-alerts|$PREFIX|g" "/etc/systemd/system/${SERVICE_NAME}.service"
  systemctl daemon-reload
fi

rm -rf "$WORKDIR"

if [[ $NO_RESTART -eq 1 ]]; then
  log "Hotovo (bez reštartu). Verzia $REMOTE_SHORT"
  exit 0
fi

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
  log "Reštartujem službu ${SERVICE_NAME}…"
  systemctl restart "$SERVICE_NAME"
  sleep 1
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "Služba beží. Verzia $REMOTE_SHORT"
    systemctl --no-pager -l status "$SERVICE_NAME" | head -n 12 || true
  else
    log "VAROVANIE: služba nebeží – skontroluj: journalctl -u $SERVICE_NAME -n 50"
    exit 1
  fi
else
  log "Služba ${SERVICE_NAME} nie je nainštalovaná – kód je aktualizovaný ($REMOTE_SHORT)."
fi

exit 0
