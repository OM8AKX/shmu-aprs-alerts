#!/bin/bash
# ============================================================
# Spustenie SHMÚ APRS Alerts v Dockeri
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG_SRC="${SCRIPT_DIR}/config/config.yaml"
CONFIG_EXAMPLE="${SCRIPT_DIR}/config/config.example.yaml"
IMAGE_NAME="shmu-aprs-alerts:latest"
CONTAINER_NAME="shmu-aprs-alerts"

usage() {
  cat <<EOF
Použitie: $0 [príkaz]

  build     Zostav Docker image
  up        Spusti kontajner na pozadí (compose)
  down      Zastav a odstráň kontajner
  logs      Sleduj logy (follow)
  once      Jeden testovací beh (--once) a koniec
  status    Stav kontajnera
  shell     Interaktívny shell v kontajneri
  help      Táto nápoveda

Príklady:
  $0 build
  $0 up
  $0 logs
  $0 once
EOF
}

ensure_config() {
  if [[ ! -f "$CONFIG_SRC" ]]; then
    if [[ -f "$CONFIG_EXAMPLE" ]]; then
      echo "==> Vytváram config/config.yaml zo vzoru…"
      cp "$CONFIG_EXAMPLE" "$CONFIG_SRC"
      echo ""
      echo "!! Uprav config/config.yaml – nastav callsign a passcode !!"
      echo "   nano $CONFIG_SRC"
      echo ""
      exit 1
    else
      echo "Chýba config/config.yaml aj config.example.yaml"
      exit 1
    fi
  fi
}

cmd_build() {
  echo "==> Building $IMAGE_NAME …"
  docker build -t "$IMAGE_NAME" .
  echo "==> Hotovo."
}

cmd_up() {
  ensure_config
  mkdir -p logs
  if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    docker compose up -d --build
  else
    cmd_build
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
    docker run -d \
      --name "$CONTAINER_NAME" \
      --restart unless-stopped \
      -e TZ=Europe/Bratislava \
      -e PYTHONUNBUFFERED=1 \
      -e SHMU_APRS_CONFIG=/app/config/config.yaml \
      -v "$CONFIG_SRC:/app/config/config.yaml:ro" \
      -v "${SCRIPT_DIR}/logs:/var/log" \
      "$IMAGE_NAME"
  fi
  echo "==> Beží. Logy: $0 logs"
}

cmd_down() {
  if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    docker compose down
  else
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
  fi
  echo "==> Zastavené."
}

cmd_logs() {
  if docker compose version &>/dev/null 2>&1 && [[ -f docker-compose.yml ]]; then
    docker compose logs -f --tail=100
  else
    docker logs -f --tail=100 "$CONTAINER_NAME"
  fi
}

cmd_once() {
  ensure_config
  cmd_build
  echo "==> Testovací beh (--once)…"
  docker run --rm \
    -e TZ=Europe/Bratislava \
    -e PYTHONUNBUFFERED=1 \
    -v "$CONFIG_SRC:/app/config/config.yaml:ro" \
    "$IMAGE_NAME" \
    --config /app/config/config.yaml --once
}

cmd_status() {
  docker ps -a --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
}

cmd_shell() {
  ensure_config
  docker run --rm -it \
    -v "$CONFIG_SRC:/app/config/config.yaml:ro" \
    --entrypoint /bin/bash \
    "$IMAGE_NAME"
}

case "${1:-help}" in
  build)  cmd_build ;;
  up|start) cmd_up ;;
  down|stop) cmd_down ;;
  logs)   cmd_logs ;;
  once|test) cmd_once ;;
  status) cmd_status ;;
  shell)  cmd_shell ;;
  help|-h|--help) usage ;;
  *)
    echo "Neznámy príkaz: $1"
    usage
    exit 1
    ;;
esac
