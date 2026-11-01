# SHMÚ → APRS Meteorologické výstrahy

Kompletný Python projekt pre **Raspberry Pi**, ktorý:

* sťahuje oficiálne meteorologické výstrahy zo **SHMÚ** (CAP 1.2 + HTML fallback)
* filtruje podľa **krajov / okresov** (Košice, Prešov, …)
* mapuje stupne na **farebné úrovne** (žltá / oranžová / červená)
* vysiela ich ako **APRS objekty** do stredu každého okresu
* začína vysielať **12 h pred** začiatkom platnosti
* opakuje vysielanie každých **30 minút**
* po expirácii automaticky posiela **kill** objektu
* beží ako **systemd** služba s **watchdogom**, alebo v **Dockeri**

## Požiadavky

* Raspberry Pi / Linux s **Python 3.9+**
* Platný ham radio callsign + [APRS-IS passcode](https://apps.magicbug.co.uk/passcode/)
* Internet

## 1. Lokálny vývoj – venv (bez root)

```bash
git clone https://github.com/OM8AKX/shmu-aprs-alerts.git
cd shmu-aprs-alerts

# Vytvorí ./venv a nainštaluje závislosti
chmod +x setup-venv.sh
./setup-venv.sh

# Aktivácia (voliteľné)
source venv/bin/activate

# Konfigurácia
cp config/config.example.yaml config/config.yaml
nano config/config.yaml          # callsign + passcode

# Test
./venv/bin/python main.py --config config/config.yaml --once
```

Manuálne namiesto `setup-venv.sh`:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2. Systémová inštalácia (systemd + venv)

```bash
git clone https://github.com/OM8AKX/shmu-aprs-alerts.git
cd shmu-aprs-alerts
sudo ./install.sh
# vytvorí používateľa aprs, venv v /opt/shmu-aprs-alerts/venv,
# config v /etc/shmu-aprs/ a systemd službu

sudo nano /etc/shmu-aprs/config.yaml   # callsign + passcode
sudo systemctl start shmu-aprs-alerts
journalctl -u shmu-aprs-alerts -f
```

## 3. Docker

```bash
cp config/config.example.yaml config/config.yaml
nano config/config.yaml
chmod +x docker-run.sh
./docker-run.sh up
./docker-run.sh logs
```

## Konfigurácia – dôležité položky

```yaml
aprs:
  callsign: "OM0XXX-13"
  passcode: 12345

filter:
  regions: ["KSK", "PSK"]
  districts: ["Košice", "Prešov", "Poprad"]
  min_level: 1

beacon:
  interval_minutes: 30
  lead_hours: 12          # vysielať už X h pred začiatkom platnosti
  poll_interval_seconds: 300
```

## Ako to funguje

1. Poll CAP feed (HTML fallback) každých 5 minút.
2. Filter podľa krajov/okresov a `lead_hours`.
3. Jeden APRS objekt do **stredu každého** postiženého okresu.
4. Symbol podľa úrovne/javu (NWS Advisory, Emergency, búrka…).
5. Po expirácii kill (`_`).

| Úroveň | Prefix | Symbol (príklad) |
|--------|--------|------------------|
| žltá (1) | — | NWS Advisory |
| oranžová (2) | `!!` | NWS Site |
| červená (3) | `!!!` | Emergency |

## Mapa

Po odoslaní: [aprs.fi](https://aprs.fi/) – hľadaj svoj callsign alebo objekty `SH…`.

73!
