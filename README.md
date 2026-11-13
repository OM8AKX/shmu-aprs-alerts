# SHMÚ → APRS: výstrahy, povodne, blesky

Python projekt pre **Raspberry Pi**, ktorý posiela na **APRS-IS** (zobrazenie na [aprs.fi](https://aprs.fi/)):

1. **Meteorologické výstrahy** zo SHMÚ (podľa okresov)
2. **Povodňové stavy (SPA)** z vodomerných staníc SHMÚ
3. **Aktivitu bleskov** (SK + ~30 km za hranicami) – poloha na mape podľa GPS úderu

Beží ako **systemd** služba s watchdogom, voliteľne v Dockeri.

---

## Možnosti projektu

### Meteorologické výstrahy
- sťahovanie zo SHMÚ (CAP 1.2 + HTML fallback)
- **iba okresy** (nie kraje / celoslovenské)
- filter podľa zoznamu okresov v configu (KSK, PSK, ZSK, BBSK, …)
- stupne **1. / 2. / 3.** v popise (`Výstraha 1.st.` …)
- APRS objekt v **strede okresu**; pri viacerých výstrahách v okrese **posun ikon** (~5,5 km)
- opakované vysielanie každých **30 minút**
- po skončení platnosti automatický **kill** objektu

### Povodňové stavy (SPA)
- aktuálne vodné stavy zo SHMÚ
- detekcia **SPA 1.–3.**
- vysielanie od nastaveného minima (`min_spa`)
- objekt pri **súradniciach stanice**
- trvá **kým SPA trvá** (po poklese kill)
- stanice: Hornád, Poprad, Torysa, Laborec, Topľa, Slaná, Váh, Orava, Kysuca, Hron, …

### Aktivita bleskov
- live zber (Blitzortung) na **celé územie SR + ~30 km** za hranicami
- agregácia do buniek (ochrana APRS-IS pred zahltením)
- ikona na **skutočnej GPS** posledného úderu v klastri (`position_mode: last`)
- komentár napr. `Blesky 12/15min`
- test bez búrky: `simulate: true`
- dáta len pre **súkromné / hobby** použitie (podmienky Blitzortung.org)

### Prevádzka
- systemd + watchdog
- Docker (voliteľne)
- skripty aktualizácie kódu / configu

### Požiadavky
- Raspberry Pi / Linux, **Python 3.9+**
- ham radio **callsign** + [APRS-IS passcode](https://apps.magicbug.co.uk/passcode/)
- internet

---

## Kompletná inštalácia na Raspberry Pi

### 1. Klonovanie a inštalácia

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip

git clone https://github.com/OM8AKX/shmu-aprs-alerts.git
cd shmu-aprs-alerts
sudo ./install.sh
```

Skript vytvorí:
- používateľa `aprs`
- kód a venv v `/opt/shmu-aprs-alerts/`
- config v `/etc/shmu-aprs/config.yaml`
- systemd jednotku `shmu-aprs-alerts.service`

### 2. Konfigurácia (povinné)

```bash
sudo nano /etc/shmu-aprs/config.yaml
```

Minimálne nastav:

```yaml
aprs:
  callsign: "OM0XXX-13"   # tvoj volací znak + SSID
  passcode: 12345         # passcode k APRS-IS
```

Ostatné sekcie (`filter`, `hydro`, `lightning`, `beacon`) majú rozumné predvolené hodnoty – uprav podľa potreby.

### 3. Spustenie služby

```bash
sudo systemctl enable --now shmu-aprs-alerts
sudo systemctl status shmu-aprs-alerts
journalctl -u shmu-aprs-alerts -f
```

### 4. Overenie na mape

[aprs.fi](https://aprs.fi/) – vyhľadaj svoj callsign alebo objekty začínajúce na **`SH`**.

### 5. Aktualizácia projektu

```bash
# ak existuje update.sh:
sudo /opt/shmu-aprs-alerts/update.sh

# alebo ručne:
cd /tmp && rm -rf shmu-aprs-alerts
git clone https://github.com/OM8AKX/shmu-aprs-alerts.git
sudo systemctl stop shmu-aprs-alerts
sudo cp -a /tmp/shmu-aprs-alerts/shmu_aprs/* /opt/shmu-aprs-alerts/shmu_aprs/
sudo cp /tmp/shmu-aprs-alerts/requirements.txt /opt/shmu-aprs-alerts/
sudo /opt/shmu-aprs-alerts/venv/bin/pip install -r /opt/shmu-aprs-alerts/requirements.txt
sudo systemctl start shmu-aprs-alerts
```

`/etc/shmu-aprs/config.yaml` sa pri aktualizácii **neprepisuje**.

### 6. Test jedným behom

```bash
sudo -u aprs /opt/shmu-aprs-alerts/venv/bin/python /opt/shmu-aprs-alerts/main.py \
  --config /etc/shmu-aprs/config.yaml --once
```

### 7. Test bleskov bez búrky (simulačný režim)

V configu dočasne:

```yaml
lightning:
  enabled: true
  simulate: true
```

```bash
sudo systemctl restart shmu-aprs-alerts
journalctl -u shmu-aprs-alerts -f
```

Po teste nastav `simulate: false`.

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

## Konfigurácia – dôležité položky

Súbor: `/etc/shmu-aprs/config.yaml`  
Vzor: [`config/config.example.yaml`](config/config.example.yaml)

```yaml
aprs:
  callsign: "OM0XXX-13"
  passcode: 12345
  server: "euro.aprs2.net"
  port: 14580

filter:
  regions: ["KSK", "PSK", "ZSK", "BBSK"]   # pre HTML roll / výber krajov
  districts:                                 # len tieto okresy sa vysielajú
    - "Košice mesto"
    - "Prešov"
    - "Poprad"
    # … kompletný zoznam v config.example.yaml
  min_level: 1

hydro:
  enabled: true
  min_spa: 1
  url: "https://www.shmu.sk/sk/?page=765"
  stations: []                # [] = preddefinované stanice

lightning:
  enabled: true
  simulate: false             # true = fiktívne blesky na test
  window_minutes: 15
  grid_deg: 0.20              # veľkosť klastra (~22 km)
  min_strikes: 2
  max_objects: 15
  position_mode: last         # last = GPS posledného úderu | centroid
  # bbox SK + 30 km (predvolené):
  # south: 47.48
  # west: 16.50
  # north: 49.92
  # east: 22.90

beacon:
  interval_minutes: 30
  lead_hours: 0               # 0 = až od začiatku platnosti
  poll_interval_seconds: 300

logging:
  level: "INFO"
  file: "/var/log/shmu-aprs-alerts.log"
```

### Užitočné príkazy

| Úloha | Príkaz |
|--------|--------|
| Stav | `systemctl status shmu-aprs-alerts` |
| Logy (živé) | `journalctl -u shmu-aprs-alerts -f` |
| Reštart | `sudo systemctl restart shmu-aprs-alerts` |
| Config | `sudo nano /etc/shmu-aprs/config.yaml` |
| Stop | `sudo systemctl stop shmu-aprs-alerts` |

---

## Ako to funguje

1. Každých `poll_interval_seconds` (predvolene 5 min):
   - **meteo** – CAP, pri zlyhaní HTML tabuľky SHMÚ podľa okresov
   - **hydro** – vodomerné stanice, SPA
   - **blesky** – live collector na pozadí + agregácia buniek
2. Meteo filter: len rozpoznané **okresy** zo zoznamu `districts`.
3. Hydro: SPA ≥ `min_spa` → objekt pri stanici, kým stav trvá.
4. Blesky: ikona na GPS úderu (posledný / centroid), max `max_objects`.
5. Beacon každých `interval_minutes`; po skončení / poklese **kill**.

| Typ | Úroveň 1 | Úroveň 2 | Úroveň 3 |
|-----|----------|----------|----------|
| Meteo | Výstraha 1.st. | Výstraha 2.st. | Výstraha 3.st. |
| Hydro | SPA 1 | SPA 2 | SPA 3 |
| Blesky | žltá (málo) | oranžová | červená (veľa úderov) |

**Mapa:** [aprs.fi](https://aprs.fi/) – callsign alebo objekty `SH…`.

73!
