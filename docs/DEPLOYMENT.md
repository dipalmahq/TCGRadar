# Ubuntu-Deployment

## JoyBoyz auf dem vorhandenen Traefik-Server

Auf diesem Server läuft das Projekt separat unter
`/home/gabriel/dipalmaHQ/TCGRadar`. Die private `.env` enthält
`COMPOSE_FILE=compose.yaml:compose.traefik.yaml:compose.workers.yaml`, sodass auch die vorhandenen
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
docker compose ps
python3 scripts/deploy.py status
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
docker compose -f compose.yaml -f compose.prod.yaml -f compose.workers.yaml config --quiet
# Erst nach Produktionsfreigabe:
docker compose -f compose.yaml -f compose.prod.yaml -f compose.workers.yaml up -d --build
```

Alternativ kann ein vorhandener HTTPS-Reverse-Proxy an `127.0.0.1:8000` weiterleiten.
Für eine private Crew ist zusätzlich ein bestehendes VPN/privates Netzwerk
möglich. Einen erreichbaren Produktionsbetrieb nur mit gesetztem Team-Schlüssel
und HTTPS beziehungsweise dem vorhandenen privaten Zugang betreiben.

## Update

Seit dem 09.11.2026 werden Änderungen über GitHub ausgeliefert:

1. Lokal ändern und prüfen; nach Händleränderungen die Worker-Konfiguration mit
   `python scripts/generate_merchant_workers.py` regenerieren und mitcommitten.
2. Änderungen committen und nach `main` pushen.
3. `.github/workflows/ci.yml` prüft Backend inklusive PostgreSQL, Frontend und
   Container. Erst wenn beide Prüfjobs erfolgreich sind, startet der Deployjob.
4. Der Deployjob sendet ausschließlich `deploy <vollständiger-commit-sha>` über
   SSH. Der Server akzeptiert nur den aktuellen `origin/main`-Commit, lehnt einen
   schmutzigen Checkout ab und verhindert überlappende Deployments mit einer Sperre.
5. Vor dem Update werden Datenbank und Deploymentkonfiguration privat gesichert.
   Das Image wird auf dem Server aus genau diesem geprüften Commit gebaut und
   als `joyboyz-tcg-radar:<commit-sha>` gespeichert. Es trägt zusätzlich das
   OCI-Label `org.opencontainers.image.revision`.
6. API und Händler-/Alarm-Worker werden für Migrationen angehalten; PostgreSQL
   bleibt aktiv. Danach starten die Anwendungsdienste mit dem neuen Image.
7. Der Deploy prüft Containerzustände, Team-Zugang innerhalb des Containers,
   öffentliche Startseite, Healthcheck und den Schutz der Angebots-API. Die CI
   prüft den öffentlichen Healthcheck zusätzlich.

Der Servercheckout bleibt auf dem veröffentlichten Commit fixiert (detached
HEAD). Keine Quelltexte oder gebauten Dateien direkt auf dem Server bzw. in
Containern verändern. Ein Push nach GitHub startet automatisch die Veröffentlichung;
PRs und andere Branches werden nur geprüft. Bereits überholte Commits werden übersprungen.

Status und Rückwechsel per administrativem SSH:

```bash
cd /home/gabriel/dipalmaHQ/TCGRadar
python3 scripts/deploy.py status
python3 scripts/deploy.py rollback
```

`rollback` setzt auf den unmittelbar vorherigen Release zurück. Vorhandene
Images werden nicht automatisch gelöscht. Ein fehlgeschlagener Build lässt die
laufende Anwendung unangetastet. Schlägt ein umgeschalteter Release fehl, wird
das vorherige Image automatisch wieder gestartet, sofern die Alembic-Version
unverändert ist.

Nach einer Schemaänderung erfolgt kein automatischer Datenbank-Downgrade oder
Restore. In diesem Fall wird die Anwendung gestoppt und die private
Sicherungsreferenz ausgegeben. Dann vorwärts reparieren oder die Datenbank
bewusst aus dem Backup wiederherstellen. Neue Schemaänderungen benötigen eine
Alembic-Migration; nicht auf `create_all` vertrauen.

Die private `.env` enthält den aktiven `RADAR_IMAGE`-Verweis. Releasezustand und
Wiederherstellungsmetadaten liegen unter
`/home/gabriel/dipalmaHQ/backups/tcgradar/deployments/`; `current.json` benennt
den aktiven Commit und das Image. Diese Dateien werden nicht nach Git übernommen.

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
docker compose stop
docker compose up -d --wait db
docker compose exec -T db pg_restore -U radar -d radar < backups/radar.dump
docker compose up -d
```

Zusätzlich `.env` und `config/shops.json` sicher außerhalb des Repositorys
sichern. Wiederherstellung in einer Testinstallation ausprobieren, bevor man
sich auf das Backup verlässt.

## GitHub

Ein Workflow liegt unter `.github/workflows/ci.yml`. Er führt Backendtests gegen
einen PostgreSQL-Service, Frontend-Build und Container-Smoke-Test aus.
Repository: `git@github.com:dipalmahq/TCGRadar.git`.
Pushes nach `main` und manuelle Workflowstarts auf `main` deployen nach allen
erfolgreichen Prüfungen automatisch. Der Deploymentverlauf steht in GitHub
Actions und in der Umgebung `production`. Die Deploymentgruppe
`joyboyz-production` wird nicht während eines laufenden Updates abgebrochen.

Vier verschlüsselte Repository-Secrets sind eingerichtet:

- `DEPLOY_SSH_HOST`: Produktionshost.
- `DEPLOY_SSH_USER`: Deploymentbenutzer.
- `DEPLOY_SSH_KEY`: eigener Ed25519-Schlüssel ausschließlich für diesen Ablauf.
- `DEPLOY_SSH_KNOWN_HOSTS`: über den vorhandenen vertrauenswürdigen SSH-Zugang
  gelesener Hostschlüssel; die CI verwendet strikte Hostprüfung.

Der öffentliche Deployment-Schlüssel ist in `~/.ssh/authorized_keys` mit
`restrict,command="/home/gabriel/.local/bin/joyboyz-deploy-ssh"` beschränkt.
Der installierte Dispatcher stammt aus `deploy/ssh-entrypoint.py`, akzeptiert
keine beliebigen Shellkommandos und lädt das Deployskript ausschließlich aus
dem aktuellen `main`-Commit. Das funktioniert auch nach einem Rückwechsel auf
eine ältere Version ohne eigenes Deployskript. Die Einschränkung wurde bei der
Einrichtung mit einem abgewiesenen Shellkommando geprüft.

Bei einer Schlüsselrotation einen neuen separaten Schlüssel erzeugen, nur diesen
Eintrag in `authorized_keys` ersetzen und `DEPLOY_SSH_KEY` aktualisieren.
Keine privaten Schlüssel, Server-`.env` oder Datenbankdumps ins Repository legen.

Die dauerhaften Arbeitsregeln für Codex stehen in der Projekt-`AGENTS.md`.

## Betrieb und Einschränkungen

- Vorgesehen sind ein Worker je Händler und ein separater Alarm-Worker;
  [Planung, Migration und Prüfintervalle](MERCHANT-WORKERS.md).
  Während eines Shopabrufs verhindert eine
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
