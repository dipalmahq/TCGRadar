# Fünf zusätzliche Händler – 07.11.2026

Die folgenden Quellen wurden mit den vorhandenen Shopify-Adaptern live geprüft
und zu `config/shops.json` hinzugefügt. Alle Abrufe verwenden HTTPS, prüfen vorher
`robots.txt` und halten mindestens zwei Sekunden Abstand je Shop ein.

| Händler | Öffentlicher Shop | Passende Varianten im geprüften Ausschnitt |
| --- | --- | ---: |
| New Era TCG | https://newera-tcg.shop | 40 |
| Gem Cards | https://gemcards.de | 67 |
| Xtreme Hits | https://www.xtremehits.de | 79 |
| cardcosmos | https://cardcosmos.de | 363 |
| YONKO TCG | https://yonko-tcg.com | 98 |

Insgesamt 647 zusätzliche passende Varianten im Probeabruf. Das sind
Shopbeobachtungen einschließlich ausverkaufter Artikel und Vorbestellungen,
keine Aussage über aktuell kaufbare Mengen oder die vollständige Marktgröße.
Die produktive Datenbank dedupliziert nach Händler und externer Varianten-ID.

## Umfang

- Je Händler sechs öffentlich verlinkte Kollektionen mit maximal zwei Seiten
  à 50 Produkten. Varianten werden getrennt importiert.
- New Era: Displays und Booster der drei Shopbereiche One Piece, Dragon Ball
  und Pokémon. Gem Cards: One Piece, Pokémon sowie getrennte Kollektionen für
  Dragon Ball Fusion World und Masters.
- Xtreme Hits: Pokémon-Displays, Booster, Trainerboxen, Blister, Kollektionen
  und Tins. cardcosmos: Pokémon-Displays, Booster und Trainerboxen, One-Piece-
  Displays und Booster sowie Dragon Ball. YONKO: One-Piece-Displays/-Booster,
  Pokémon-Displays/-Booster/-Boxen und Dragon-Ball-Displays.
- Prüfintervall 1.200 Sekunden. Die tatsächliche Ausführung hängt zusätzlich von
  der Warteschlange des einzelnen Workers und möglichen Shopfehlern ab.
- Titel ohne ausreichend belegtes Spiel oder Verpackungsart bleiben unberücksichtigt.
  Deshalb enthält beispielsweise der geprüfte Gem-Cards-Ausschnitt trotz
  konfigurierter Pokémon-Kollektionen nur One Piece und Dragon Ball.
- Keine Abdeckung von Einzelkarten oder Grading. Ein im allgemeinen
  cardcosmos-Katalog erkanntes Grading-Angebot mit dem Setnamen „Red Collection“
  führte zu einer zusätzlichen Sperre für Kartennummern und Grading-Marker.
  Fünf Regressionstests sichern diese Abgrenzung.
- CuxCards wurde geprüft und nicht aufgenommen: beide vorhandenen
  Katalogschnittstellen antworteten dort mit HTTP 404.

## Prüfung

Pro neuem Händler drei verschiedene Produkte aus dem Katalog frisch über
`/products/<handle>.js` abgerufen und die jeweilige Varianten-ID verglichen.
Alle 15 Stichproben stimmten bei Preis, Währung und Verfügbarkeit überein.
Rohprotokoll lokal unter `data/additional-source-probes.jsonl` (gitignoriert).

Wiederholbarer, rein lesender Probeabruf ohne Benachrichtigungen:

```bash
docker compose exec -T api python - < scripts/probe_additional_sources.py
# Optional nur ein Händler:
docker compose exec -T api python - --shop gemcards < scripts/probe_additional_sources.py
```

69 Tests mit einer separaten PostgreSQL-Testdatenbank bestanden.
Vor Aktivierung wurde ein privates Produktionsbackup erstellt. Die Erweiterung
benötigt keine Schemaänderung und verändert keine gespeicherten Suchregeln oder
Alarmkanäle. Ein separater Testalarm wurde nicht versandt.

## Produktionsabnahme

Der laufende Worker importierte alle fünf zusätzlichen Händler ohne Abruffehler.
Die produktiven Angebotszahlen entsprechen der Tabelle. Anschließender
Deployment-Check erfolgreich: zehn Händler, insgesamt 788 Angebote, davon
270 als verfügbar und drei als Vorbestellung gemeldet. Dashboard, Team-Zugang
und PostgreSQL geprüft. Es wurden bei dieser Abnahme keine Benachrichtigungen
erzeugt. Sämtliche Zahlen sind Momentaufnahmen des 07.11.2026.

Bei der abschließenden öffentlichen API-Prüfung waren 787 Angebote sichtbar:
Der nächste reguläre FantasiaCards-Abruf blendete mit der neuen Grading-Sperre
ein zuvor importiertes PSA-10-Angebot aus. Der historische Datensatz bleibt
erhalten. Alle 647 neuen Angebote sind vorhanden; alle zehn Händler melden
erfolgreiche Abrufe ohne Fehler. Öffentliche API und Datenbankbestand stimmen
überein.
