# Server-Abnahme am 07.11.2026

Deployment unter `/home/gabriel/dipalmaHQ/TCGRadar` mit eigenem Compose-Projekt
`joyboyz-tcg-radar` und dem bestehenden Traefik-Netzwerk `proxy`.

- Produktionsbuild inklusive Vue-Typecheck und Vite-Build erfolgreich.
- 64 vorhandene Tests gegen eine separate PostgreSQL-Testdatenbank bestanden.
  Eine Deprecation-Warnung des FastAPI/Starlette-Testclients.
- `https://radar.joyboyz.de/` liefert HTTP 200 mit verifiziertem TLS-Zertifikat.
  JavaScript und CSS werden erfolgreich geladen.
- Hauptdomain und `www` liefern HTTP 301 zum Radar. Pfade und Query-Strings
  bleiben erhalten. HTTP wird nach HTTPS umgeleitet.
- API ohne beziehungsweise mit falschem Team-Schlüssel: HTTP 401.
  Richtiger Schlüssel: erfolgreicher Zugriff auf Metadaten und Angebote.
- PostgreSQL 16.15; API und Datenbank gesund, separater Worker läuft.
  Keine veröffentlichten Hostports für den Radar-Stack.
- Alle fünf aktivierten Händler erfolgreich abgerufen: 141 echte Angebote,
  141 Ereignisse, davon 63 Angebote als verfügbar und drei als Vorbestellung.
  Diese Zahlen sind eine Momentaufnahme; Shopbestände ändern sich laufend.
- Produktionscontainer mit `docker compose up -d --force-recreate` neu erstellt.
  Alle 282 zuvor gespeicherten Angebots-/Ereignis-IDs erhalten; öffentlicher
  Zugriff und Team-Anmeldung anschließend erneut erfolgreich geprüft.
- Erstes PostgreSQL-Backup in eine separate, leere Testdatenbank wiederhergestellt:
  141 Angebote, 141 Ereignisse, Alembic-Stand `f701c5b2d9a6`.
  Testcontainer und Testnetzwerk danach entfernt.
- Privater Backup-Ordner mit Modus 700; Dump und gesicherte `.env` mit Modus 600.
  Benutzer-Cronjob täglich um 04:15 Uhr Europe/Berlin installiert.
- Benachrichtigungen deaktiviert, keine Alarmkanäle konfiguriert und keine
  externen Testnachrichten versandt.

Die Deployment-Änderungen liegen im lokalen Checkout. Ein GitHub-Push ist
nicht Teil dieser Abnahme. Zugangsdaten sind nicht versioniert.
