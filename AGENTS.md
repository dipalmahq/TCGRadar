# JoyBoyz: Projekt- und Deploymentregeln

## Dauerhafter Arbeitsablauf

Der Nutzer hat am 09.11.2026 diesen Standard beauftragt: Projektänderungen lokal
umsetzen, prüfen, sinnvoll committen und nach GitHub pushen; anschließend den
automatischen Produktionsdeploy bis zum überprüften Ergebnis begleiten.
Wenn ausdrücklich nur Analyse, Review, Entwurf oder lokale Änderungen verlangt
sind, entsprechend innerhalb dieses Umfangs bleiben.

- Repository: `https://github.com/dipalmahq/TCGRadar`, Produktionsbranch `main`.
- Ein Push auf `main` veröffentlicht nach erfolgreicher CI automatisch.
- Nicht bei „lokal fertig“ oder „gepusht“ stehen bleiben: CI und Deployment prüfen.
- Keine zusätzlichen Deploy-Bestätigungen für bereits beauftragte Änderungen
  einführen. Bei fehlenden Berechtigungen den konkreten Blocker nennen.
- Bestehende uncommittete Änderungen erhalten und vor einem Abgleich sichern.

## Produktion

- URL: `https://radar.joyboyz.de`.
- Administrativer SSH-Alias: `dipalmaHQ`, Benutzer `gabriel`.
- Projektverzeichnis: `/home/gabriel/dipalmaHQ/TCGRadar`.
- `.github/workflows/ci.yml` führt Tests aus und deployt danach den geprüften
  `main`-Commit über einen eingeschränkten SSH-Schlüssel.
- `scripts/deploy.py` baut das Image `joyboyz-tcg-radar:<commit-sha>` und schreibt
  den aktiven Image-Verweis in die private Server-`.env`.
- Der Produktionscheckout ist sauber und auf den veröffentlichten Commit fixiert
  (detached HEAD). Dort keine Quelltexte, Builddateien oder Containerinhalte patchen.
- Normale Änderungen ausschließlich über Git und den Deploymentworkflow liefern.
  SSH für Diagnose, dokumentierte Wiederherstellung und Deploymentwartung nutzen.
- Andere Anwendungen auf dem gemeinsamen Traefik-Server nicht verändern.

## Prüfungen und Wiederherstellung

- Frontend: `pnpm --dir frontend build`.
- Backend: `.venv/Scripts/python.exe -m pytest backend/tests` unter Windows;
  `python -m pytest backend/tests` in Linux/CI. PostgreSQL-Tests laufen in der CI.
- Nach Händleränderungen `python scripts/generate_merchant_workers.py` ausführen
  und `compose.workers.yaml` mitcommitten.
- CI wartet auf Backendtests, Frontendbuild und isolierte Containerprüfung.
- Nach Deploy öffentliche Seite, `/api/health`, Zugriffsschutz und Containerzustand
  kontrollieren; die mobile Loginansicht bei Layoutänderungen ebenfalls prüfen.
- Private Backups und Releasezustand:
  `/home/gabriel/dipalmaHQ/backups/tcgradar/`.
- `python3 scripts/deploy.py status` zeigt den aktiven Release.
- `python3 scripts/deploy.py rollback` setzt auf den vorherigen Release zurück,
  sofern sich das Datenbankschema nicht unterscheidet. Keine automatischen
  Datenbank-Downgrades oder Wiederherstellungen echter Daten ausführen.
- `.env`, SSH-Schlüssel, Tokens, Datenbank und Backups niemals committen oder
  in Toolausgaben ausgeben. Keine echten Testnachrichten ohne ausdrücklichen Auftrag.
- Betriebsdetails und Einrichtung: `docs/DEPLOYMENT.md`.
