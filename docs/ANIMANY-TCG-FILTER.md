# Animany auf TCG-Quellen beschränken

Der ursprüngliche Gesamtkatalog enthält 19.309 Einträge auf 387 Seiten, darunter
Manga, Bücher, Merchandise und Turniertickets. Die Entdeckung verwendet jetzt
gezielte TCG-Kategorien und das allgemeine TCG-Schlagwort. Alle Seiten und
Varianten dieser Bereiche werden weiterhin vollständig verarbeitet.

## Auswahl der Bereiche

Ein reiner Kategoriefilter verliert drei ältere, kategorielose One-Piece-Produkte.
Ein reiner TCG-Schlagwortfilter verliert vier andere bereits bekannte Kartenprodukte.
Deshalb werden die Ergebnisse beider Abfragen vereinigt und nach Produkt-ID
dedupliziert. Kategorien und Schlagwörter stehen nicht gemeinsam als UND-Filter
in einer einzelnen Anfrage.

| Kategorie-ID | Animany-Bezeichnung |
| --- | --- |
| 846 | TCG Produkte |
| 1082 | TCG |
| 1442 | Pokémon Sealed |
| 875 | One Piece Card Game |
| 1101 | One Piece |
| 1099 | Pokemon |
| 3151 | Pokemon TCG |
| 2298 | DB Fusion World |

Zusätzlich wird Schlagwort **316 – TCG** gelesen. Die Kategorie „Anime“ wird
nicht als breiter Ersatz verwendet. Die vorhandene Produktklassifikation
grenzt weiterhin die vier unterstützten TCG-Linien und Sealed-Produkte ab.

## Allgemeine Adapterfunktion

Der WooCommerce-Adapter unterstützt optionale Listen `category_ids` und `tag_ids`
mit positiven ganzzahligen IDs. Jede vorhandene Liste bildet einen Abfragezweig.
Cursor speichern Seite, Abfragezweig und bereits gelesene Produkt-IDs. Laufende
Variantenauflösungen und HTTP-429-Fortsetzungen behalten diesen Zustand.
Identische Ergebnisse in zwei verschiedenen Zweigen gelten nicht als
Seitenschleife. Ohne Filter bleibt das bisherige Verhalten erhalten.

Die Filter schränken nur die Katalogentdeckung ein. Bekannte Angebote,
Direktbeobachtungen und Regel-Treffer behalten ihre eigenen Prüfpläne.
Es gibt keinen produkt- oder setspezifischen Sondercode.

WooCommerce-Schlagwörter ergänzen die Belege für die Produktzuordnung. Explizite
Buch-/Manga-Belege ohne TCG-Beleg verhindern, dass ein Manga-Pack als Booster
klassifiziert wird. Ein TCG-Produkt mit Manga-Design bleibt dagegen zulässig.

## Verifikation am 08.11.2026

Der vollständige gefilterte Live-Durchlauf las **62 eindeutige Katalogeinträge
auf drei Seiten** und enthielt alle **22 bisher bekannten gültigen Kartenangebote**.
Die acht übrigen zuvor sichtbaren Angebote waren Pokémon-Manga-Packs. Alle
30 Bestandsartikel wurden frisch über ihre Produktadressen geprüft: 22 gültige
Kartenangebote bestätigt, acht Manga-Packs mit erhaltener Historie ausgeblendet.
Der erste produktive Filterdurchlauf wurde ebenfalls mit drei Seiten und
62 eindeutigen Einträgen abgeschlossen; es gab keinen Quellenfehler.

**236 Tests gegen isoliertes PostgreSQL bestanden.** Die neuen Regressionen
prüfen Vereinigung, Deduplizierung über Seiten und Zweige, Fortsetzung mitten
in Varianten, ungültige Filter und die Abgrenzung von Manga-Packs.

Bei der Umstellung beginnt nur Animanys Katalogfortschritt für den neuen Umfang
neu. Watchlist- und Retry-Fristen bleiben erhalten. Andere Händler behalten
ihre Konfiguration und ihren laufenden Katalogfortschritt.

Diese Abdeckung hängt von Animanys Kategorien und Schlagwörtern ab. Neue Artikel
ohne passende Quellzuordnung werden von diesem Filter nicht entdeckt; bereits
bekannte Produktlinks werden weiterhin unabhängig davon geprüft.
