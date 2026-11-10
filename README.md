# SHMÚ → APRS Meteorologické výstrahy + povodňové stavy

Kompletný Python projekt pre **Raspberry Pi**, ktorý:

* sťahuje oficiálne meteorologické výstrahy zo **SHMÚ** (CAP 1.2 + HTML fallback)
* filtruje podľa **krajov / okresov** (Košice, Prešov, Žilina, Banská Bystrica, …)
* mapuje stupne na **farebné úrovne** (žltá / oranžová / červená) a popis „Výstraha N.st.“
* vysiela ich ako **APRS objekty** do stredu každého okresu (s posunom pri viacerých výstrahách)
* opakuje vysielanie každých **30 minút**
* po expirácii automaticky posiela **kill** objektu
* beží ako **systemd** služba s **watchdogom**, alebo v **Dockeri**

### Novinka: povodňové stavy (SPA)

* sťahuje aktuálne **vodné stavy** z vodomerných staníc SHMÚ
* počíta / deteguje **stupeň povodňovej aktivity (SPA 1.–3.)**
* pri SPA ≥ nastaveného minima vysiela APRS objekty pri stanici
* komentár napr.: `SPA 2.st. Hornád` + hladina v cm
* preddefinované stanice: Hornád (KE, Kysak, Margecany), Poprad, Torysa, Laborec, Topľa, Slaná, Váh, Orava, Kysuca, Hron a ďalšie

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
  regions: ["KSK", "PSK", "ZSK", "BBSK"]
  districts: ["Košice mesto", "Prešov", "Poprad"]
  min_level: 1

hydro:
  enabled: true
  min_spa: 1              # vysielať od 1. stupňa SPA
  url: "https://www.shmu.sk/sk/?page=765"
  stations: []            # prázdne = preddefinované stanice
  lifetime_hours: 2

beacon:
  interval_minutes: 30
  lead_hours: 0           # 0 = až od začiatku platnosti výstrahy
  poll_interval_seconds: 300
```

## Ako to funguje

1. Poll CAP feed (HTML fallback) každých 5 minút + hydro tabuľka staníc.
2. Filter meteo výstrah podľa krajov/okresov.
3. Hydro: SPA ≥ `min_spa` → APRS objekt pri súradniciach stanice.
4. Meteo: jeden APRS objekt do **stredu každého** postihnutého okresu (s posunom pri viacerých).
5. Symbol podľa úrovne/javu; po expirácii kill (`_`).

| Úroveň | Popis | Symbol (príklad) |
|--------|--------|------------------|
| žltá (1) | Výstraha 1.st. / SPA 1 | podľa javu |
| oranžová (2) | Výstraha 2.st. / SPA 2 | podľa javu |
| červená (3) | Výstraha 3.st. / SPA 3 | Emergency / flood |

## Mapa

Po odoslaní: [aprs.fi](https://aprs.fi/) – hľadaj svoj callsign alebo objekty `SH…`.

73!
