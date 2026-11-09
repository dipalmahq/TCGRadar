# Card-Corner: Pokémon-Übersichtsseiten – 08.11.2026

## Ursache

Der produktive Katalogdurchlauf blieb nach 81 Seiten und 1.107 geprüften
Produkten an `/Pokemon-Alle-Erweiterungen` hängen. Card-Corner zeigte dort
keine Produktliste, sondern drei Sprachbereiche als Kategorie-Kacheln.
Diese verwendeten Bilder unter `media/image/storage/opc` statt des bisherigen
Kategorie-Bildpfads. Der Parser fand weder Produkte noch bekannte Navigation
und meldete deshalb einen Quellenfehler. Nach elf fehlgeschlagenen Versuchen
war der nächste Abruf entsprechend verzögert.

Eine zweite Navigationsform lag auf den deutschen und englischen Set-Übersichten:
Ihre OPC-Schaltflächen heißen „ZUM SET“ und besitzen nicht den zuvor erkannten
`set-card`-Container. Japanische Übersichten verwenden zusätzlich „ALLE PRODUKTE“.

## Korrektur

- Sprach-Kacheln aus `.category-slider-wrapper` werden im Inhaltsbereich erkannt.
- OPC-Schaltflächen mit „ZUM SET“ oder „ALLE PRODUKTE“ werden unabhängig vom
  umgebenden Layout erkannt und doppelte Ziele zusammengeführt.
- Kontakt-, Kartenlisten- und ausgeschlossene Zubehörlinks werden nicht als
  Produktnavigation übernommen. Navigation außerhalb des Inhaltsbereichs sowie
  aus Header, Navigation und Footer bleibt ausgeschlossen.
- Alle Ziele unterliegen weiterhin der Prüfung auf denselben Shop-Ursprung.
  Leere, unbekannte oder gesperrte Seiten gelten weiterhin als Fehler.
- Der vorhandene Katalogcursor bleibt gültig. Es ist weder ein Zurücksetzen
  des Fortschritts noch eine Änderung der Händlerkonfiguration notwendig.

## Verifikation

Alle zehn zuvor gespeicherten offenen Kategorien sowie die drei zusätzlichen
Sprachübersichten wurden live mit dem korrigierten Parser geprüft. Jede Seite
lieferte erkennbare Produkte oder gültige Katalognavigation. Die allgemeine
Übersicht lieferte drei Sprachlinks; die deutschen, englischen und japanischen
Übersichten lieferten 24, 23 beziehungsweise vier erkannte Set-Ziele.
Die beispielhaft geprüften Set-Seiten Delta Herrschaft, Delta Reign und Aura
Seeker enthielten ebenfalls konkrete Produktlisten.

Acht zusätzliche Regressionen prüfen diese Navigationsformen, die Fortsetzung
eines bestehenden Cursors über beide Übersichtsebenen, die Begrenzung auf den
Inhaltsbereich, fremde Ursprünge und weiterhin fehlschlagende Kontakt-/Leerseiten.
**190 Tests gegen eine separate PostgreSQL-Testdatenbank bestanden**; lokal
bestanden 188 Tests und zwei PostgreSQL-Sperrtests wurden übersprungen.

Vor der Installation wurden Datenbank, Konfiguration, die ersetzten Quelldateien
und das vorherige Image gesichert. Frontend und Datenbankschema bleiben unverändert.
Nicht erneut bestätigte Angebote werden nicht pauschal auf verfügbar gesetzt;
ihre Bestände werden beim weiteren Abruf individuell geprüft.

## Produktive Abnahme

Vier echte Katalogabschnitte setzten den gespeicherten Durchlauf von Seite 81
auf Seite 85 fort. Die alten 1.107 geprüften Produkte und die bereits besuchten
Ziele blieben erhalten. Bereits früher gesehene Produkte wurden dabei nicht
erneut als neue Katalogfunde importiert. Eine anschließende getrennte
Produktaktualisierung bestätigte sechs gespeicherte Angebote frisch.

Der Fehlerzähler sank durch erfolgreiche Abrufe von elf auf null; die aktuelle
Fehlermeldung ist leer. Die Cursor aller anderen Händler blieben unverändert.
Während der Verifikation wurden keine Benachrichtigungen erzeugt. API und Worker
laufen mit dem korrigierten Image. Die abschließende öffentliche HTTPS-Prüfung
bestätigte den fehlerfreien Händlerstatus und den fortgesetzten Fortschritt.
Der vollständige Katalogdurchlauf ist weiterhin offen und wird regulär fortgesetzt.
