# SHMÚ → APRS Meteorologické výstrahy + povodňové stavy

Python projekt pre **Raspberry Pi**: meteorologické výstrahy a povodňové stavy zo **SHMÚ** ako objekty do siete **APRS-IS** (zobrazenie na [aprs.fi](https://aprs.fi/)).

---

## Možnosti projektu

### Meteorologické výstrahy
- sťahovanie zo SHMÚ (CAP 1.2 + HTML fallback)
- filter podľa **krajov a okresov** (KSK, PSK, ZSK, BBSK a ďalšie)
- stupne **1. / 2. / 3.** (žltá / oranžová / červená) v popise objektu
- APRS objekt v **strede okresu**; pri viacerých výstrahách v jednom okrese **posun ikon**
- opakované vysielanie každých **30 minút**
- po skončení platnosti automatický **kill** objektu

### Povodňové stavy (SPA)
- aktuálne **vodné stavy** z vodomerných staníc SHMÚ
- detekcia **stupňa povodňovej aktivity (SPA 1.–3.)**
- vysielanie až od nastaveného minima (predvolene SPA ≥ 1)
- objekt pri súradniciach stanice (napr. Hornád – Košice)
- preddefinované stanice: Hornád, Poprad, Torysa, Laborec, Topľa, Slaná, Váh, Orava, Kysuca, Hron, …

### Prevádzka
- **systemd** služba s watchdogom
- **Docker** (voliteľne)
- skripty `update.sh` a `update-config.sh` na aktualizáciu kódu a configu

### Požiadavky
- Raspberry Pi / Linux, **Python 3.9+**
- ham radio **callsign** + [APRS-IS passcode](https://apps.magicbug.co.uk/passcode/)
- internet

---

## Inštalácia na Raspberry Pi

### Rýchla systémová inštalácia (odporúčané)

```bash
git clone https://github.com/OM8AKX/shmu-aprs-alerts.git
cd shmu-aprs-alerts
sudo ./install.sh
```

Skript vytvorí používateľa `aprs`, virtuálne prostredie v `/opt/shmu-aprs-alerts/venv`, config v `/etc/shmu-aprs/` a systemd službu.

```bash
sudo nano /etc/shmu-aprs/config.yaml   # nastav callsign + passcode
sudo systemctl enable --now shmu-aprs-alerts
journalctl -u shmu-aprs-alerts -f
```

### Aktualizácia kódu

```bash
sudo /opt/shmu-aprs-alerts/update.sh
```

Alebo ručne:

```bash
cd /tmp && rm -rf shmu-aprs-alerts
git clone https://github.com/OM8AKX/shmu-aprs-alerts.git
sudo systemctl stop shmu-aprs-alerts
sudo cp -a /tmp/shmu-aprs-alerts/shmu_aprs/* /opt/shmu-aprs-alerts/shmu_aprs/
sudo /opt/shmu-aprs-alerts/venv/bin/pip install -r /tmp/shmu-aprs-alerts/requirements.txt
sudo systemctl start shmu-aprs-alerts
```

### Test jedným behom

```bash
sudo -u aprs /opt/shmu-aprs-alerts/venv/bin/python /opt/shmu-aprs-alerts/main.py \
  --config /etc/shmu-aprs/config.yaml --once
```

### Docker (voliteľne)

```bash
git clone https://github.com/OM8AKX/shmu-aprs-alerts.git
cd shmu-aprs-alerts
cp config/config.example.yaml config/config.yaml
nano config/config.yaml
chmod +x docker-run.sh
./docker-run.sh up
./docker-run.sh logs
```

### Lokálny vývoj (venv bez root)

```bash
git clone https://github.com/OM8AKX/shmu-aprs-alerts.git
cd shmu-aprs-alerts
chmod +x setup-venv.sh && ./setup-venv.sh
cp config/config.example.yaml config/config.yaml
nano config/config.yaml
./venv/bin/python main.py --config config/config.yaml --once
```

---

## Dôležité konfiguračné údaje

Súbor: `/etc/shmu-aprs/config.yaml` (po inštalácii) alebo `config/config.yaml`.

Vzor: [`config/config.example.yaml`](config/config.example.yaml).

```yaml
aprs:
  callsign: "OM0XXX-13"      # tvoj callsign (SSID napr. -13)
  passcode: 12345            # APRS-IS passcode
  server: "euro.aprs2.net"
  port: 14580

filter:
  regions: ["KSK", "PSK", "ZSK", "BBSK"]
  districts:                 # len tieto okresy (prázdne + regions = celé kraje)
    - "Košice mesto"
    - "Prešov"
    - "Poprad"
  min_level: 1               # minimálny stupeň meteo výstrahy (1–3)

hydro:
  enabled: true
  min_spa: 1                 # vysielať od 1. stupňa SPA
  url: "https://www.shmu.sk/sk/?page=765"
  stations: []               # [] = všetky preddefinované v hydro.py
  lifetime_hours: 2

beacon:
  interval_minutes: 30       # opakovanie APRS objektov
  lead_hours: 0              # 0 = až od začiatku platnosti výstrahy
  poll_interval_seconds: 300 # interval sťahovania dát

logging:
  level: "INFO"
  file: "/var/log/shmu-aprs-alerts.log"
```

### Užitočné príkazy

| Úloha | Príkaz |
|--------|--------|
| Stav služby | `systemctl status shmu-aprs-alerts` |
| Logy (živé) | `journalctl -u shmu-aprs-alerts -f` |
| Reštart | `sudo systemctl restart shmu-aprs-alerts` |
| Úprava configu | `sudo nano /etc/shmu-aprs/config.yaml` |

**Poznámka:** `update.sh` neprepisuje `/etc/shmu-aprs/config.yaml` (callsign a passcode ostanú).

---

## Ako to funguje

1. **Poll** každých `poll_interval_seconds` (predvolene 5 min):
   - meteo: CAP feed, pri zlyhaní HTML stránka výstrah SHMÚ
   - hydro: tabuľka vodomerných staníc SHMÚ
2. **Filter** meteo výstrah podľa krajov/okresov a minimálneho stupňa.
3. **Hydro:** stanice so SPA ≥ `min_spa` sa premenia na APRS objekty pri GPS stanice.
4. **Meteo:** jeden objekt na okres (stred okresu); viac výstrah v okrese → posun ikon na mape.
5. **Beacon** každých `interval_minutes`; po skončení platnosti **kill** (`_`).

| Úroveň | Meteo | Hydro |
|--------|--------|--------|
| 1 | Výstraha 1.st. | SPA 1.st. |
| 2 | Výstraha 2.st. | SPA 2.st. |
| 3 | Výstraha 3.st. | SPA 3.st. |

Na mape: [aprs.fi](https://aprs.fi/) – hľadaj svoj callsign alebo objekty začínajúce na `SH`.

73!
