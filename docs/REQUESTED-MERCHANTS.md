# Angefragte Händler vom 07.11.2026

Dieser Bericht beschreibt die erste Abnahme mit Katalogausschnitten. Die aktive
Version liest inzwischen vollständige Kataloge in fortsetzbaren Durchläufen;
siehe [Vollständige Katalogdurchläufe](FULL-CATALOG.md).

Die erneute Games-Island-Prüfung und weitere Nutzeranfragen vom 08.11.2026 stehen
im [aktuellen Abnahmebericht](REQUESTED-SHOPS-2026-11-08.md). Games Island liefert
inzwischen eine lesbare Startseite, jedoch weiterhin keine lesbaren TCG-Kataloge.

Acht zusätzliche Quellen sind implementiert. Die beiden weiteren angefragten
Shops stehen mit dem konkreten Hindernis in `config/shops.pending.json`, nicht
in der aktiven Händlerkonfiguration.

| Händler | Geprüfter Katalogausschnitt | Passende Angebote im Probeabruf |
| --- | --- | ---: |
| Gate to the Games | Pokémon-Displays/-Booster, One Piece Englisch | 18 |
| collect-it | Pokémon-Booster und -Displays | 6 |
| Trader-Online | Pokémon-Displays/-Booster | 12 |
| Card-Corner | Pokémon-Booster/-Displays, One Piece | 18 |
| LottiCards | Pokémon-Booster/-Displays, One Piece | 7 |
| Müller | Dragon-Ball-Suche und Sammelkarten-Kategorie | 4 |
| CrispyCards | Pokémon-/One-Piece-Displays, Dragon Ball | 18 |
| Spielewelt | Pokémon-Displays/-Booster, One Piece | 18 |

Alle acht verwenden `structured_html`: begrenzte Kategorieseiten, danach maximal
sechs relevante Produktdetails je Kategorie. Prüfintervall: 20 Minuten zuzüglich
Worker-Warteschlange. Es handelt sich um Katalogausschnitte, keine vollständigen
Händlersortimente. Die 101 Angebote enthalten ausverkaufte Produkte; sie sind
keine Zusicherung aktuell kaufbarer Ware. Der Müller-Ausschnitt lieferte nur
Dragon Ball Fusion World, keinen belegten Pokémon-Treffer.

Die Shopify-JSON-Katalogrouten von CrispyCards und Spielewelt meldeten bei
weiteren Seiten/Kollektionen HTTP 429. Deshalb verwendet die Erweiterung die
normalen HTML-Seiten mit `Accept: text/html` und ihren eingebetteten JSON-LD-
Produktangeboten. Beide Quellen wurden zusätzlich vom Betriebsserver lesend
geprüft: je 18 konkrete Angebote, keine Warnungen, je drei frische Produktproben
mit übereinstimmendem Preis, Währung und Verfügbarkeit. Lokale Drosselungen
bleiben im Rohprotokoll erkennbar; sie werden nicht als erfolgreiche Checks gezählt.

## Nicht aktiviert

- **Games Island:** Die Kategorieseite liefert Hinweise auf
  `crawlme.games-island.eu` statt eines Produktkatalogs. Dessen `robots.txt`
  enthält `User-agent: *` und `Disallow: /`; der Client bricht den Abruf ab.
  Es fehlt eine für den Radar freigegebene Datenquelle.
- **Smyths Toys:** Der öffentliche Abruf liefert die Bot-Prüfseite
  „Pardon Our Interruption“ ohne Produktangebote; der Betriebsserver erhält
  stattdessen eine Incapsula-Sperrseite („Request unsuccessful“, HTTP 200).
  Keine aktive Anbindung und
  keine behauptete Bestandsabdeckung.

## Datenqualität und Tests

- JSON-LD und Microdata werden auf konkrete Produkte und genau ein konkretes
  Angebot begrenzt. AggregateOffer, mehrere unaufgelöste Angebote und abweichende
  Mindest-/Höchstpreise werden ausgelassen.
- Detailabrufe dürfen Empfehlungen weder als angefragtes Produkt übernehmen noch
  deren Lagerstatus verwenden. Ein entsprechender Trader-Online-Fehler wurde
  korrigiert und durch einen Regressionstest abgedeckt.
- Unbekannte Verfügbarkeit bleibt unbekannt; Müller-Filialverfügbarkeit gilt
  nicht als Beleg für Onlinebestand. Unbelegte Sprachen/Packzahlen werden nicht geraten.
- Shopify-Einzelvarianten behalten ihre Varianten-ID, damit Direktlink-Regeln
  dieselbe Variante treffen. Unaufgelöste Mehrfachvarianten werden ausgelassen.
- HTTPS, Origin-Prüfung, robots.txt, mindestens zwei Sekunden Abstand,
  Antwort-/Requestlimits und Backoff bleiben aktiv. HTTP 429 beendet den Scan.
- Lokaler kompletter Testlauf: **84 bestanden, zwei PostgreSQL-Tests übersprungen**.
  17 neue Tests sichern Parser, Varianten, Empfehlungen, Drosselung und Direktlinks.
  Die bestehende Starlette-Testclient-Deprecation-Warnung bleibt unverändert.

Lesende Wiederholung ohne Datenbankänderung oder Benachrichtigungen:

```bash
python scripts/probe_requested_sources.py
python scripts/probe_requested_sources.py --shop crispycards
```

Rohprotokolle und HTML-Antworten liegen lokal unter `data/` und bleiben aus Git
ausgeschlossen.

## Produktionsprüfung

Das neue Container-Image wurde auf dem bestehenden Server gebaut. **86 Tests
gegen eine getrennte PostgreSQL-Testdatenbank bestanden**, einschließlich der
beiden PostgreSQL-Sperrtests. Das temporäre Testprojekt wurde anschließend entfernt.
Vor der Erweiterung wurden ein privates PostgreSQL-/Konfigurationsbackup, eine
Quellensicherung und ein Rückfall-Tag des bisherigen Container-Images erstellt.

Der kontrollierte Erstimport übernahm alle **acht Quellen und 101 zusätzliche
Angebote**. Die Erzeugung von Alarmnachrichten war ausschließlich im einmaligen
Importprozess unterdrückt: **null neue Benachrichtigungen**, gespeicherte Regeln
unverändert. Anschließend wurden API und regulärer Worker mit dem neuen Image
gestartet.

Öffentliche HTTPS-Abnahme am **07.11.2026 um 19:22 Uhr, Europe/Berlin**:
Dashboard und Healthcheck erfolgreich; Händler-API ohne Team-Schlüssel HTTP 401,
mit Schlüssel erfolgreich. **18 Händler aktiv, alle mit erfolgreichem Abruf und
Fehlerzähler null.** Insgesamt 888 sichtbare Angebote, davon 338 als verfügbar
und drei als Vorbestellung gemeldet. Keine ausstehenden Benachrichtigungen.
Diese Zahlen sind Momentaufnahmen und keine vollständige Sortimentsabdeckung.
