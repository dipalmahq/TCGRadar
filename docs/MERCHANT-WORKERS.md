# Händler-Worker und Bestandsalter

Seit der Umstellung vom 08.11.2026 läuft pro konfiguriertem Händler ein eigener
Prozess (`--merchant SLUG`). Der separate Prozess `--notifications-only` versendet
Alarme und bereinigt täglich alte Beobachtungen. Der frühere gemeinsame Worker
ist nur noch über das Profil `legacy` verfügbar; beide Betriebsarten nicht
gleichzeitig starten.

## Zeitplan und Anzeige

- Direkte Beobachtungen und bereits bekannte Treffer aktiver Suchregeln haben
  einen eigenen Prüfplan mit einem Zielabstand von fünf Minuten. Auch ausverkaufte
  Treffer und Treffer oberhalb der Preisgrenze werden geprüft, damit Restocks und
  Preissenkungen entdeckt werden können. Preis- und Bestandsfilter gelten beim Alarm.
- Normale Bestandsprüfungen haben 30 Minuten Zielabstand und werden nach ältester
  fälliger Prüfung abgearbeitet. Sie wechseln sich mit Katalogabschnitten ab;
  fällige Watchlist-Prüfungen haben Vorrang. Zwölf Produktseiten pro Abschnitt
  begrenzen nur die einzelne Aufgabe, nicht den vollständigen Katalogdurchlauf.
- HTTP-Abstände, robots.txt und Retry-After gelten für alle Aufgaben desselben
  Händlers. Ein langer Katalogabschnitt oder ein Shopausfall kann die Zielabstände
  überschreiten. Neue, bisher unbekannte Suchregel-Treffer benötigen weiterhin
  die Katalogentdeckung.
- Bis 24 Stunden bleibt ein belegter letzter Bestand sichtbar; die Oberfläche
  nennt das Bestätigungsalter. „Auf Lager“ zählt alle gültigen Lagermeldungen
  innerhalb dieser Frist. Ausgeblendete Angebote und Quellenfehler zählen nicht.
  Unbekannte Versandkosten werden in Liste, Details und Vergleich nicht angezeigt.
- Nach mehr als 24 Stunden wird der angezeigte Bestand unbekannt. Quellenfehler
  machen ihn sofort unbekannt. Fehlversuche verändern die letzte erfolgreiche
  Bestätigung nicht; die letzte bekannte Verfügbarkeit bleibt separat erhalten.
- Produktalarme verlangen vor dem Versand einen weiterhin gültigen, fehlerfreien
  Bestand mit höchstens fünf Minuten Alter. Veraltete Warteschlangeneinträge
  werden als `muted` dokumentiert. Dies kann bei längerem Ausfall Alarme auslassen.

Native Shopify-Varianten werden pro Produktseite gemeinsam geprüft. Bei
HTML-Quellen bleiben konkrete Varianten-URLs erhalten. Eine fehlende Variante
wird nicht durch den Bestand einer Geschwistervariante bestätigt.

## Installation und weitere Händler

`setup_env.py` erzeugt `compose.workers.yaml` aus `config/shops.json`. Eine neue
`.env` enthält bereits `COMPOSE_FILE=compose.yaml:compose.workers.yaml` und
`COMPOSE_PATH_SEPARATOR=:`. Auf dem Traefik-Server bleibt zusätzlich
`compose.traefik.yaml` in der Liste. Compose ab 2.24.4 ist erforderlich.

Bei weiteren Händlern:

```bash
python3 scripts/generate_merchant_workers.py
docker compose config --quiet
docker compose run --rm migrate
docker compose up -d
```

Vorhandene `.env`-Dateien werden vom Setup nicht überschrieben. Beim Umstieg den
alten Worker stoppen, API vor der Schemaänderung anhalten und ein privates Backup
erstellen. Migration `b842f6d390a1` ergänzt separate Fristen und Heartbeats;
bestehende Bestände, Bestätigungszeiten und Katalog-Cursor werden nicht verändert.
Danach `compose.workers.yaml` in `COMPOSE_FILE` aufnehmen und alte explizite Werte
auf `RADAR_STALE_AFTER_MINUTES=1440`, `RADAR_REFRESH_INTERVAL_SECONDS=1800`,
`RADAR_WATCH_INTERVAL_SECONDS=300`, `RADAR_REFRESH_BATCH_SIZE=12` aktualisieren.
API und sämtliche Worker mit demselben neuen Image starten.

Jeder Worker hat einen Pool von zwei PostgreSQL-Verbindungen ohne Überlauf.
26 Händler plus Alarmprozess benötigen höchstens 54 Verbindungen, der API-Pool
zusätzlich höchstens zehn. Händler- und Alarm-Sperren werden bei Verbindungsverlust
automatisch freigegeben. SQLite bleibt die einfachere Entwicklungsvariante.

```bash
docker compose ps
docker compose logs --tail 50 worker-card-corner notifications
```

Die Händler-API liefert Heartbeat, Watchlist- und Bestandsprüfungsfortschritt;
Direktbeobachtungen liefern letzte Versuche und nächste Prüftermine.

## Verifikation

223 Tests gegen isoliertes PostgreSQL bestanden, darunter tatsächliche parallele
Produkteinfügungen, Händler-/Alarm-Sperren, unabhängige Watchlist-Termine,
Variantenprüfung, Fehlerpausen und Upgrade/Downgrade mit erhaltenen Altdaten.
Frontend-Typecheck und Produktionsbuild bestanden. Beim Produktivupgrade wurden
alle bereits vorhandenen Felder sämtlicher Anwendungstabellen vor und nach der
Migration über SHA-256 verglichen; sie blieben unverändert.

Die anschließende Live-Stichprobe fand einen fehlenden TCG-Kontext bei direkten
LottiCards-Detailabrufen. Der allgemeine HTML-Adapter berücksichtigt jetzt
eindeutige Breadcrumbs der aktuellen Produktseite, einschließlich JSON-LD.
Globale Navigation, widersprüchliche TCG-Pfade, Einzelkarten und fremde Spiele
liefern weiterhin keinen gültigen Sealed-Nachweis. Alle betroffenen 81 Artikel
wurden nach erfolgreichen frischen Einzelabrufen wiederhergestellt.

Bei der Live-Abnahme meldeten alle 26 Händler aktuelle Heartbeats; zusätzlich
lief genau ein Alarm-Worker mit bestätigter exklusiver Sperre. Kein Container
hatte einen automatischen Neustart. Die neun Direktbeobachtungen wurden nach
dem neuen Zeitplan erfolgreich geprüft. PostgreSQL hatte bei der Momentaufnahme
60 Verbindungen; sein Limit beträgt 100. HTTPS-Health und Zugangsschutz bestanden.
Der öffentliche HTML-/JavaScript-/CSS-Build stimmt mit dem gebauten Image überein.
Alte Card-Corner-Quellenfehler werden weiterhin durch echte Bestandsabrufe
abgearbeitet; die längere Altersgrenze hebt Quellenfehler nicht auf.
