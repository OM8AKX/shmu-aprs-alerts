# SHMÚ → APRS Meteorologické výstrahy

Kompletný Python projekt pre **Raspberry Pi**, ktorý:

* sťahuje oficiálne meteorologické výstrahy zo **SHMÚ** (CAP 1.2 + HTML fallback)
* filtruje podľa **krajov / okresov** (Košice, Prešov, …)
* mapuje stupne na **farebné úrovne** (žltá / oranžová / červená)
* vysiela ich ako **APRS objekty** cez APRS-IS
* opakuje vysielanie každých **30 minút**
* po expirácii automaticky posiela **kill** objektu
* beží ako **systemd** služba s **watchdogom**
* alebo v **Dockeri**

## Požiadavky

* Raspberry Pi (alebo akýkoľvek Linux) s Python 3.9+ **alebo Docker**
* Platný ham radio callsign + APRS-IS passcode
* Internet

## Docker (odporúčané)

```bash
git clone https://github.com/OM8AKX/shmu-aprs-alerts.git
cd shmu-aprs-alerts

# Konfigurácia
cp config/config.example.yaml config/config.yaml
nano config/config.yaml          # callsign + passcode

# Spustenie
chmod +x docker-run.sh
./docker-run.sh up               # build + start na pozadí
./docker-run.sh logs             # sledovanie logov
./docker-run.sh once             # jednorazový test
./docker-run.sh down             # zastavenie
```

Alebo priamo s Compose:

```bash
cp config/config.example.yaml config/config.yaml
nano config/config.yaml
docker compose up -d --build
docker compose logs -f
```

## Inštalácia bez Dockeru (systemd)

```bash
git clone https://github.com/OM8AKX/shmu-aprs-alerts.git
cd shmu-aprs-alerts
sudo ./install.sh
sudo nano /etc/shmu-aprs/config.yaml   # callsign + passcode
sudo systemctl start shmu-aprs-alerts
```

## Konfigurácia – dôležité položky

```yaml
aprs:
  callsign: "OM0XXX-13"
  passcode: 12345           # https://apps.magicbug.co.uk/passcode/

filter:
  regions:
    - "KSK"
    - "PSK"
  districts:
    - "Košice"
    - "Prešov"
    - "Poprad"
  min_level: 1

beacon:
  interval_minutes: 30
  poll_interval_seconds: 300
```

## Testovanie

```bash
# Docker
./docker-run.sh once

# Bez Dockeru
./venv/bin/python main.py --config /etc/shmu-aprs/config.yaml --once
```

## Ako to funguje

1. Každých 5 minút sa stiahne CAP feed zo SHMÚ opendata.
2. Ak je CAP prázdny, použije sa HTML fallback.
3. Filtrácia podľa krajov/okresov a minimálneho stupňa.
4. Každých 30 minút APRS Object Report.
5. Po expirácii kill objektu.
6. systemd watchdog (alebo Docker restart policy).

| Úroveň | Prefix | Význam |
|--------|--------|--------|
| žltá (1) | — | bežné |
| oranžová (2) | `!!` | zvýšená pozornosť |
| červená (3) | `!!!` | kritická |

73!
