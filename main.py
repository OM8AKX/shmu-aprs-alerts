#!/usr/bin/env python3
"""
SHMÚ meteorologické výstrahy → APRS-IS
=====================================
Sťahuje oficiálne výstrahy (CAP 1.2) zo SHMÚ, filtruje podľa okresov/krajov,
prevádza na APRS objekty a vysiela cez APRS-IS každých 30 minút.
Po expirácii automaticky posiela kill objektu.

Použitie:
  python3 main.py --config /etc/shmu-aprs/config.yaml
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from shmu_aprs.service import ShmuAprsService


def main() -> int:
    parser = argparse.ArgumentParser(description="SHMÚ → APRS meteorologické výstrahy")
    parser.add_argument(
        "-c", "--config",
        default=os.environ.get("SHMU_APRS_CONFIG", "config/config.yaml"),
        help="Cesta k YAML konfigurácii",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Jeden beh (poll + vysielanie) a koniec – vhodné na test",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_file():
        print(f"Konfiguračný súbor neexistuje: {config_path}", file=sys.stderr)
        print("Skopíruj config/config.example.yaml → config/config.yaml a uprav.", file=sys.stderr)
        return 1

    svc = ShmuAprsService(config_path)

    if args.once:
        svc._setup_logging()
        import logging
        log = logging.getLogger("once")
        log.info("Režim --once")
        aprs_cfg = svc.cfg["aprs"]
        from shmu_aprs.aprs_tx import AprsTransmitter
        svc.tx = AprsTransmitter(
            callsign=aprs_cfg["callsign"],
            passcode=aprs_cfg["passcode"],
            server=aprs_cfg.get("server", "euro.aprs2.net"),
            port=aprs_cfg.get("port", 14580),
            software=aprs_cfg.get("software", "SHMU"),
        )
        try:
            svc.tx.connect()
            alerts = svc._poll_alerts()
            log.info("Nájdené výstrahy po filtri: %d", len(alerts))
            for a in alerts:
                log.info("  - %s | %s | %s | areas=%s", a.level.color_sk, a.event, a.identifier, a.areas)
            svc._send_or_update(alerts)
        finally:
            if svc.tx:
                svc.tx.disconnect()
        return 0

    svc.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
