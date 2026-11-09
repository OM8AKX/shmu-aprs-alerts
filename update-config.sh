#!/bin/bash
# Aktualizácia configu z GitHubu (okresy/kraje) so zachovaním callsign/passcode
#
# Použitie:
#   sudo ./update-config.sh              # stiahni vzor, zlúč filter, reštart
#   sudo ./update-config.sh --check      # len ukáž rozdiel (nepisuje)
#   sudo ./update-config.sh --no-restart # aktualizuj bez reštartu služby
#   sudo ./update-config.sh --replace-filter  # nahraď celý filter zo vzoru
#                                            # (default: zlúč – pridá chýbajúce)
#
# Cron (voliteľne po update.sh):
#   20 4 * * * /opt/shmu-aprs-alerts/update-config.sh >> /var/log/shmu-aprs-update.log 2>&1

set -euo pipefail

REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/OM8AKX/shmu-aprs-alerts/main}"
PREFIX="${PREFIX:-/opt/shmu-aprs-alerts}"
CONFIG_DIR="${CONFIG_DIR:-/etc/shmu-aprs}"
CONFIG="${CONFIG:-$CONFIG_DIR/config.yaml}"
EXAMPLE_LOCAL="$PREFIX/config/config.example.yaml"
SERVICE_NAME="${SERVICE_NAME:-shmu-aprs-alerts}"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

CHECK_ONLY=0
NO_RESTART=0
REPLACE_FILTER=0

for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --no-restart) NO_RESTART=1 ;;
    --replace-filter) REPLACE_FILTER=1 ;;
    -h|--help)
      sed -n '2,14p' "$0"
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

if [[ ! -f "$CONFIG" ]]; then
  log "Chýba $CONFIG – najprv spusti install.sh alebo skopíruj config.example.yaml"
  exit 1
fi

# Python interpreter (prefer venv)
PY="python3"
if [[ -x "$PREFIX/venv/bin/python" ]]; then
  PY="$PREFIX/venv/bin/python"
fi

# Stiahni najnovší vzor z GitHubu, fallback na lokálny example
EXAMPLE="$TMPDIR/config.example.yaml"
if command -v curl >/dev/null 2>&1; then
  if curl -fsSL "$REPO_RAW/config/config.example.yaml" -o "$EXAMPLE" 2>/dev/null; then
    log "Vzor stiahnutý z GitHubu"
  elif [[ -f "$EXAMPLE_LOCAL" ]]; then
    cp "$EXAMPLE_LOCAL" "$EXAMPLE"
    log "GitHub nedostupný – použijem lokálny $EXAMPLE_LOCAL"
  else
    log "Nepodarilo sa získať config.example.yaml"
    exit 1
  fi
elif [[ -f "$EXAMPLE_LOCAL" ]]; then
  cp "$EXAMPLE_LOCAL" "$EXAMPLE"
  log "Používam lokálny $EXAMPLE_LOCAL"
else
  log "Chýba curl aj lokálny example"
  exit 1
fi

OUT="$TMPDIR/config.merged.yaml"
REPORT="$TMPDIR/report.txt"

export CONFIG EXAMPLE OUT REPORT REPLACE_FILTER

"$PY" - <<'PY'
import os, sys, shutil
from copy import deepcopy
from datetime import datetime

try:
    import yaml
except ImportError:
    print("Chýba PyYAML – spusti: pip install PyYAML", file=sys.stderr)
    sys.exit(1)

config_path = os.environ["CONFIG"]
example_path = os.environ["EXAMPLE"]
out_path = os.environ["OUT"]
report_path = os.environ["REPORT"]
replace_filter = os.environ.get("REPLACE_FILTER", "0") == "1"

with open(config_path, "r", encoding="utf-8") as f:
    live = yaml.safe_load(f) or {}
with open(example_path, "r", encoding="utf-8") as f:
    example = yaml.safe_load(f) or {}

live_f = live.setdefault("filter", {})
ex_f = example.get("filter") or {}

old_regions = list(live_f.get("regions") or [])
old_districts = list(live_f.get("districts") or [])
ex_regions = list(ex_f.get("regions") or [])
ex_districts = list(ex_f.get("districts") or [])

added_regions = []
added_districts = []

if replace_filter:
    live_f["regions"] = list(ex_regions)
    live_f["districts"] = list(ex_districts)
    if "min_level" in ex_f:
        live_f["min_level"] = ex_f["min_level"]
    added_regions = [r for r in ex_regions if r not in old_regions]
    added_districts = [d for d in ex_districts if d not in old_districts]
    removed_r = [r for r in old_regions if r not in ex_regions]
    removed_d = [d for d in old_districts if d not in ex_districts]
else:
    # merge: pridaj chýbajúce, nič nemazaj
    regions = list(old_regions)
    for r in ex_regions:
        if r not in regions:
            regions.append(r)
            added_regions.append(r)
    districts = list(old_districts)
    for d in ex_districts:
        if d not in districts:
            districts.append(d)
            added_districts.append(d)
    live_f["regions"] = regions
    live_f["districts"] = districts
    removed_r, removed_d = [], []

# beacon / sources / logging / watchdog – doplň len chýbajúce kľúče (neprepisuj existujúce)
for section in ("beacon", "sources", "logging", "watchdog"):
    if section in example:
        live_sec = live.setdefault(section, {})
        if not isinstance(live_sec, dict):
            continue
        for k, v in (example[section] or {}).items():
            if k not in live_sec:
                live_sec[k] = v

lines = []
lines.append(f"Režim: {'replace-filter' if replace_filter else 'merge'}")
lines.append(f"Regions: {len(old_regions)} → {len(live_f.get('regions') or [])}")
lines.append(f"Districts: {len(old_districts)} → {len(live_f.get('districts') or [])}")
if added_regions:
    lines.append("Pridané kraje: " + ", ".join(str(x) for x in added_regions))
if added_districts:
    lines.append("Pridané okresy: " + ", ".join(str(x) for x in added_districts))
if removed_r:
    lines.append("Odstránené kraje: " + ", ".join(str(x) for x in removed_r))
if removed_d:
    lines.append("Odstránené okresy: " + ", ".join(str(x) for x in removed_d))
if not added_regions and not added_districts and not removed_r and not removed_d:
    lines.append("Žiadne zmeny vo filtri.")

# aprs ostáva vždy z live
aprs = live.get("aprs") or {}
cs = aprs.get("callsign", "?")
lines.append(f"Zachovaný callsign: {cs}")

report = "\n".join(lines) + "\n"
open(report_path, "w", encoding="utf-8").write(report)
print(report, end="")

changed = bool(added_regions or added_districts or removed_r or removed_d)

class LiteralStr(str):
    pass

def _str_representer(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)

yaml.add_representer(str, _str_representer)

header = (
    "# SHMÚ → APRS config (aktualizované update-config.sh)\n"
    f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    "# Callsign/passcode sa pri aktualizácii nemenia.\n\n"
)

with open(out_path, "w", encoding="utf-8") as f:
    f.write(header)
    yaml.dump(
        live,
        f,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )

sys.exit(0 if changed else 3)
PY
RC=$?

# exit 3 = bez zmien, 0 = zmeny, iné = chyba
if [[ $RC -ne 0 && $RC -ne 3 ]]; then
  log "Zlúčenie zlyhalo (kód $RC)"
  exit "$RC"
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
  if [[ $RC -eq 3 ]]; then
    log "Config je už v súlade so vzorom (filter)."
    exit 0
  fi
  log "Kontrola: boli by zmeny (config sa nezapisal)."
  exit 2
fi

if [[ $RC -eq 3 ]]; then
  log "Žiadne zmeny – config nechávam."
  exit 0
fi

# Záloha + zápis
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="$CONFIG.bak.$STAMP"
cp -a "$CONFIG" "$BACKUP"
cp "$OUT" "$CONFIG"
chmod 640 "$CONFIG"
if id aprs &>/dev/null; then
  chown aprs:aprs "$CONFIG" 2>/dev/null || chown root:root "$CONFIG"
fi
log "Config aktualizovaný. Záloha: $BACKUP"

if [[ $NO_RESTART -eq 1 ]]; then
  log "Hotovo (bez reštartu)."
  exit 0
fi

if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
  log "Reštartujem $SERVICE_NAME…"
  systemctl restart "$SERVICE_NAME"
  sleep 1
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "Služba beží."
  else
    log "VAROVANIE: služba nebeží – journalctl -u $SERVICE_NAME -n 40"
    exit 1
  fi
else
  log "Služba nie je nainštalovaná – config je uložený."
fi

exit 0
