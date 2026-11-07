# Verifikation des MVPs

Dieser Bericht dokumentiert die erste Entwicklungsabnahme mit SQLite.
Die anschließende erfolgreiche Docker-/PostgreSQL-Abnahme einschließlich echtem
Discord-Versand steht in [CONTAINER-VERIFICATION.md](CONTAINER-VERIFICATION.md).
Die dortigen Ergebnisse ersetzen die damaligen Angaben zu noch offenen Prüfungen.

Stand: **07.11.2026, Europe/Berlin**. Alle nachfolgenden Live-Ergebnisse stammen
aus tatsächlich ausgeführten Abrufen mit den implementierten Adaptern.

## Echte Shop-Integrationen

| Shop | Weg | Letzter erfolgreicher Check (Berlin) | Umfang des Abrufs | Passende Angebote |
| --- | --- | --- | --- | --- |
| FantasiaCards, Deutschland | Shopify `/products.json`, 3 Seiten à 50 | 07.11., 00:29 | 150 Katalogeinträge | 46 |
| House of Cards & Games, Deutschland | WooCommerce Store API, drei Suchbegriffe plus Einzelvarianten | 07.11., 00:31 | 60 Produkt-/Varianten-Datensätze | 42 |

Beide Shops lieferten in diesen Prüfungen gültiges JSON und keine Abruffehler.
`robots.txt` wurde vorher abgerufen. Die Katalogfenster sind begrenzt; diese
Zahlen belegen keine vollständige Händler- oder Marktabdeckung.

Im lokalen Entwicklungsbestand liegen **92 echte Angebotsdatensätze**: 44 One
Piece, 31 Pokémon und 17 Dragon Ball Fusion World. Nach der konservativeren
Produktzuordnung wurden zuletzt **88 bestätigt**. Vier historisch importierte
Angebote haben keine ausreichend belegte Verpackungsart und stehen ausdrücklich
auf `unknown`; für sie werden keine Boosterpreise oder automatischen Vergleiche
angegeben.

Bestandsaufnahme nach dem letzten Worker-Lauf: 53 auf Lager, 32 ausverkauft,
3 Vorbestellungen und 4 unbekannt. Dies sind zeitgebundene Quellbeobachtungen,
keine Zusicherung für einen späteren Checkout.

## Direkte Produktlinks

Zusätzlich am 07.11. gegen 00:22 erfolgreich ausgeführt:

- FantasiaCards: englisches One-Piece-OP17-Display, externe Variante
  `58187830985044`; Produktpreis 329,99 EUR, als verfügbar geliefert. Die
  Einzelprodukt-Überwachung verwendet die dokumentierte Shopify-Ajax-API
  `products/<handle>.js` und interpretiert deren Preiswerte als Cent.
- House of Cards & Games: deutscher Pokémon-Delta-Herrschaft-Booster, externe
  Variante `37871`; Produktpreis 7,99 EUR, als verfügbar geliefert. Der Link
  mit `attribute_pa_auswahl=booster` lieferte ausschließlich die gewählte
  Variante, nicht den Preis eines vollständigen Displays.

Das wiederholbare Prüfskript ist `scripts/verify_live.py`. Die Rohantworten und
lokalen Ergebnisdateien stehen unter `data/` und sind aus Git ausgeschlossen.

## Worker und Ereignisse

Im Dashboard wurden beide Händlerchecks angefordert. Danach arbeitete ein
separater Prozess `python -m app.worker --once` diese ab und aktualisierte die
letzten erfolgreichen Checkzeiten. Unveränderte Angebote erzeugten dabei **0 neue
Ereignisse**. Ein echter spontaner Restock oder eine Preisänderung wurde in der
kurzen Live-Probe nicht beobachtet; diese Zustandswechsel sind automatisiert mit
kontrollierten HTTP-Antworten geprüft.

## Automatisierte Tests und Build

Tatsächlich erfolgreich ausgeführt:

```text
python -m pytest backend/tests --basetemp=data/pytest-run-06 --tb=short -x
42 passed

pnpm --dir frontend run build
vue-tsc --noEmit && vite build: erfolgreich

python -m alembic -c backend/alembic.ini check
No new upgrade operations detected.
```

Die Backend-Tests prüfen unter anderem Sprach-/Packungsgrenzen,
unsichere Zuordnungen, Variantenpreise, verschachtelte Cases, Discovery bis API,
Restocks, veraltete und fehlgeschlagene Quellen, Preisgrenzen, Vorbestellungs-
Opt-in, doppelte Regeln, Neustart-Deduplizierung, Shop-Leases, ausgehende
Discord-/Telegram-Payloads, Rate Limits, unklare Zustellung und Team-Zugang.
Es gibt eine Deprecation-Warnung der installierten Starlette-TestClient-Version
zur künftigen Nutzung von HTTPX2; die Tests bestehen.

Die PostgreSQL-Migration ließ sich zusätzlich im Offline-Modus als SQL erzeugen.
Das ersetzt keinen ausgeführten PostgreSQL-Migrationstest.

## Browserprüfung

Mit dem gebauten Frontend und der lokal laufenden FastAPI:

- Echte Angebotsdaten und Händlerstatus sichtbar.
- TCG-/Produktsuche, Verfügbarkeitsfilter und Preissortierung geprüft.
- Produktdetails, Preis-/Bestandsverlauf und Vergleichshinweis bei unsicherer
  Identität geprüft.
- Eine Preisbeobachtung über das Formular angelegt und gespeichert; die eigene
  temporäre QA-Regel anschließend wieder entfernt.
- Händlerprüfung über das Dashboard eingereiht und vom Worker abgearbeitet.
- Mobile Ansicht bei 390 × 844 sowie Menü-/Händlernavigation geprüft;
  Seitenbreite 375 Pixel bei 390 Pixel Viewport inklusive Scrollleiste, kein
  horizontaler Überlauf. Temporäre Viewport-Einstellung danach zurückgesetzt.
- Keine JavaScript-Konsolenfehler in der abschließenden Sichtprüfung.

Die gespeicherte [Dashboard-Vorschau](preview.png) zeigt echte Daten des letzten
Imports. Sie ist ein Screenshot und kein Live-Verfügbarkeitsversprechen.

## Noch nicht live bestätigt

- **Docker / PostgreSQL:** Auf diesem Windows-Rechner ist kein Docker-Kommando
  verfügbar. Die Compose-Dateien wurden als YAML geladen und die Dienststruktur
  geprüft; kein Containerbuild oder Compose-Start wurde hier behauptet.
- **Discord / Telegram:** Keine echten Zugangsdaten vorgegeben. Die Zustellung
  ist gegen simulierte Dienstantworten geprüft; es wurde keine echte Nachricht
  an einen Crew-Kanal verschickt. Nach Einrichtung bleibt der echte Testalarm
  als Inbetriebnahmeprüfung erforderlich.
- **Shopübergreifende Identität:** Im begrenzten Live-Ausschnitt noch kein sicher
  zusammenführbares Händlerpaar. Der API-Vergleich gleicher Produkte über zwei
  Händler und das Trennen abweichender Sprachen/Packformen sind automatisiert
  getestet.
- **Ubuntu / GitHub:** Lokales Git-Repository angelegt. Kein Remote-Repository,
  kein Push, kein ausgeführter GitHub-CI-Lauf und kein Produktionsdeployment.

Der Vorschauprozess wird nach der Prüfung beendet. Für eigene lokale Nutzung
stehen `scripts/dev.ps1` und die Docker-Anleitung in der README bereit.
