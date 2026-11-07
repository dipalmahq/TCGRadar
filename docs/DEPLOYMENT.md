# Ubuntu-Deployment

## JoyBoyz auf dem vorhandenen Traefik-Server

Auf diesem Server läuft das Projekt separat unter
`/home/gabriel/dipalmaHQ/TCGRadar`. Die private `.env` enthält
`COMPOSE_FILE=compose.yaml:compose.traefik.yaml`, sodass auch die vorhandenen
Prüfskripte und normale `docker compose`-Befehle die richtige Konfiguration nutzen.
Compose v2.24.4 oder neuer ist für `!reset` erforderlich.

- `https://radar.joyboyz.de`: Dashboard und API mit Team-Schlüssel.
- `https://joyboyz.de` und `https://www.joyboyz.de`: permanente Weiterleitungen
  zum Radar, einschließlich Pfad und Query-String.
- Der bestehende Traefik übernimmt HTTP → HTTPS und Let's Encrypt mit seinem
  vorhandenen Resolver `letsencrypt`. Nur die API hängt zusätzlich am externen
  Netzwerk `proxy`; PostgreSQL und Worker bleiben im Projektnetzwerk.
- Es werden keine Hostports veröffentlicht. `compose.prod.yaml` ist die
  alternative Caddy-Konfiguration und darf hier nicht zusätzlich geladen werden.
- Zugangsdaten werden auf dem Server generiert und bleiben in `.env` (Modus 600).
  Benachrichtigungen bleiben zunächst deaktiviert.

```bash
cd /home/gabriel/dipalmaHQ/TCGRadar
docker compose config --quiet
docker compose up -d --build
python3 scripts/container_check.py
```

Für ein neues Checkout zuerst `python3 scripts/setup_env.py` ausführen und die
oben genannte `COMPOSE_FILE`-Zeile in `.env` ergänzen.

`python3 scripts/backup.py` sichert PostgreSQL als Custom-Format-Dump und die
Deployment-Konfiguration inklusive `.env` unter
`/home/gabriel/dipalmaHQ/backups/tcgradar/<UTC-Zeitstempel>/`.
Die Verzeichnisse sind privat; unvollständige Backups werden entfernt.
Backups enthalten Zugangsdaten und gehören nicht ins Repository.
Der Benutzer-Cronjob aus `deploy/backup.cron` läuft täglich um 04:15 Uhr
Serverzeit (Europe/Berlin); Ausgabe unter `backups/tcgradar/backup.log`.
Die Sicherungen liegen auf demselben Server; für Schutz bei Serververlust ist
zusätzlich eine externe Kopie erforderlich. Es gibt keine automatische Löschung.

Zur Wiederherstellung in eine separate, leere Datenbank den Abschnitt unten
verwenden. Vor Updates oder Schemaänderungen ein frisches Backup erstellen.

## Alternative: neuer Ubuntu-Server

1. Auf Ubuntu Docker Engine und das Compose-v2-Plugin aus den offiziellen Quellen
   einrichten. Projekt aus dem späteren GitHub-Repository auschecken oder die
   Quelldateien auf den Server übertragen. Keine lokale Entwicklungsdatenbank
   oder Zugangsdaten in ein Git-Repository aufnehmen.
2. `python3 scripts/setup_env.py` im Projektverzeichnis ausführen. `.env` nur für
   den Betreiber lesbar machen (`chmod 600 .env`). Die Zugangsdaten bleiben auf
   dem jeweiligen Server; lokale Entwicklungszugänge nicht wiederverwenden.
3. `docker compose config --quiet` und `docker compose build` ausführen.
4. Nach Freigabe `docker compose up -d` starten. API-Health unter
   `http://127.0.0.1:8000/api/health`, Worker-Logs und echte Angebote prüfen.
5. Alarmkanäle konfigurieren, Containerumgebung neu erstellen lassen und den
   Testalarm im Dashboard auslösen. Erst danach persönliche Regeln aktivieren.

## HTTPS mit Caddy

Domain auf den Server zeigen lassen und `RADAR_DOMAIN=radar.example.org` in `.env`
setzen. Ports 80 und 443 müssen für die Zertifikatsausstellung erreichbar sein.
Die API bleibt bei der Standardkonfiguration nur über Loopback veröffentlicht;
PostgreSQL hat keinen veröffentlichten Port.

```bash
docker compose -f compose.yaml -f compose.prod.yaml config --quiet
# Erst nach Produktionsfreigabe:
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

Alternativ kann ein vorhandener HTTPS-Reverse-Proxy an `127.0.0.1:8000` weiterleiten.
Für eine private Crew ist zusätzlich ein bestehendes VPN/privates Netzwerk
möglich. Einen erreichbaren Produktionsbetrieb nur mit gesetztem Team-Schlüssel
und HTTPS beziehungsweise dem vorhandenen privaten Zugang betreiben.

## Update

```bash
git pull --ff-only
docker compose build
docker compose run --rm migrate
docker compose up -d
```

Vor Schemaänderungen ein Backup erstellen. Die initiale Migration ist für
PostgreSQL und SQLite angelegt; weitere Änderungen bekommen eine neue
Alembic-Migration. Nicht einfach Modellklassen verändern und auf `create_all`
vertrauen.

## Backup und Wiederherstellung

Ubuntu-Bash, Backup außerhalb von Git ablegen:

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U radar -d radar -Fc > backups/radar.dump
```

Zum Wiederherstellen in eine bewusst ausgewählte, dafür vorbereitete Datenbank
API und Worker stoppen. Das folgende Beispiel ist für eine **leere** Ziel-
Datenbank gedacht; es enthält kein automatisches Löschen bestehender Daten:

```bash
docker compose stop api worker
docker compose exec -T db pg_restore -U radar -d radar < backups/radar.dump
docker compose start api worker
```

Zusätzlich `.env` und `config/shops.json` sicher außerhalb des Repositorys
sichern. Wiederherstellung in einer Testinstallation ausprobieren, bevor man
sich auf das Backup verlässt.

## GitHub

Ein Workflow liegt unter `.github/workflows/ci.yml`. Er führt Backendtests gegen
einen PostgreSQL-Service, Frontend-Build und Container-Smoke-Test aus.
Repository: `git@github.com:dipalmahq/TCGRadar.git`.
Ein Push führt nur die CI aus; es gibt keinen automatischen Produktionsdeploy.

## Betrieb und Einschränkungen

- Vorgesehen ist ein Worker. Während eines Shopabrufs verhindert eine
  PostgreSQL-Advisory-Sperre überlappende Prüfungen desselben Händlers. Sie wird
  auch bei hartem Abbruch mit der Verbindung freigegeben. Verwaiste Zeitmarkierungen
  blockieren den nächsten Worker dadurch nicht mehr.
- Shop-Ausfälle verlängern das Prüfintervall exponentiell, maximal auf 6 Stunden.
  Ein manueller Check im Dashboard kann nach mindestens einer Minute neu
  angefordert werden; eine noch aktive Lease wird dabei nicht umgangen.
- Daten im Dashboard veralten nach der konfigurierten Frist sichtbar. Ein
  erfolgreicher API-Healthcheck allein bestätigt keine funktionierende
  Shopverbindung; dafür die letzten erfolgreichen Händlerchecks kontrollieren.
- Quellen, Shopbedingungen, Produktdaten und Verfügbarkeit können sich ändern.
  Adapter regelmäßig anhand echter Angebote prüfen.
