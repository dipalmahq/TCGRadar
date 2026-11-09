# Reguläre Quellen und Vorbestellungen – 07.11.2026

Die Implementierung enthält keine B32-spezifischen Bedingungen, Setnamen oder Produktlinks. B32 ist ausschließlich Recherche- und Betriebsdaten: eine gespeicherte Suchregel und neun normale Direktbeobachtungen. Alle fünf neuen Shops werden regulär im gesamten unterstützten TCG-Produktumfang abgefragt.

## Allgemeine Änderungen

- HTML-Kategorien wechseln sich pro Spiel an Seitengrenzen ab. Offene Produkte und bestehende Cursor bleiben erhalten; wiederholte Seiten werden auch nach einem Spielwechsel erkannt.
- Ein separater Aktualisierungsdurchgang prüft Direktbeobachtungen und ältere bekannte Angebote unabhängig von der Katalogposition. Standard: sechs Produktlinks pro Händlerabschnitt, fünf Minuten Zielintervall; bei Rückstand folgen weitere Abschnitte. Vorbestellungen haben Vorrang vor anderen alten Angeboten.
- Bis zu vier unterschiedliche Händler werden parallel bearbeitet. Jeder Händler bleibt durch dieselbe PostgreSQL-Prozesssperre geschützt; HTTP-Abstände, robots.txt, Abrufbudgets und Retry-After gelten weiter. Es gibt keinen Gesamtdeckel für Katalogprodukte oder Folgeseiten.
- Ein Zielintervall ist keine garantierte Aktualität aller Angebote großer Kataloge. Die vorhandene Anzeige veralteter Beobachtungen bleibt maßgeblich.
- Shopify und WooCommerce erkennen zusätzliche ausdrückliche Vorbestellungsmerkmale und zukünftige Release-Angaben aus Produktbeschreibungen. Ein Termin allein macht ein nicht bestellbares Produkt nicht verfügbar.
- Shopware-Kategorien unterstützen Produktkarten und beide öffentlichen Paginierungsformen. Auf Produktseiten entscheidet bei widersprüchlichem PreOrder-Markup der eigene Kaufbereich: reine Lieferbenachrichtigung ist ausverkauft; fehlender Kaufbeleg ist unbekannt. Empfehlungsprodukte beeinflussen diesen Status nicht.
- Nullpreis-Platzhalter von Shopify werden als unbekannter Preis behandelt. Displaygrößen werden nur aus expliziten Angaben gelesen; Cases übernehmen keine innere Displaygröße als Gesamtinhalt.
- Jede gespeicherte Suchregel kann ihre Treffer im Radar öffnen, einschließlich momentan nicht verfügbarer Produkte. Spiele, Sets, Händler, Sprache, Produkttyp, Preisgrenze und exakte Produktbindung werden berücksichtigt. Benachrichtigungen beachten weiterhin die vorhandenen Verfügbarkeitsregeln; eine erneut geöffnete Vorbestellung heißt im Alarm „Wieder vorbestellbar“.

## Fünf zusätzliche Händler

| Händler | Land | Reguläre Erfassung | B32-Momentaufnahme |
| --- | --- | --- | --- |
| [JustNerdsTCG](https://justnerdstcg.de) | DE | Gesamter öffentlicher Shopify-Katalog | Display ausverkauft, Nullpreis ist ein Platzhalter |
| [Miki’s Card Shop](https://www.mikiscardshop.at) | AT | Gesamter öffentlicher Shopify-Katalog | Display ausverkauft |
| [S-Games](https://s-games.at) | AT | Gesamter öffentlicher Shopify-Katalog | Display ausverkauft |
| [Evolution TCG](https://evlutcg.com) | NL | Gesamter öffentlicher Shopify-Katalog | Display und Case ausverkauft |
| [ComicPlanet](https://www.comicplanet.de) | DE | Alle Folgeseiten der Pokémon-, One-Piece- und Dragon-Ball-Bereiche | Booster vorbestellbar; Display nur Lieferbenachrichtigung |

Zusätzlich wurde die öffentlich verifizierte Dragon-Ball-Kategorie von Card-Corner in dessen regulären Umfang aufgenommen. Der vorhandene offene Cursor wurde um diese Kategorie ergänzt.

## Gezielter Quellen-Audit

Der schreibgeschützte Audit suchte in öffentlichen Katalogtiteln nach B32/BT32/B-32 und Chromatic Ascension. API-Kataloge wurden bis zur letzten Seite gelesen; HTML-Quellen in den relevanten konfigurierten Bereichen. Gefundene HTML-Produkte wurden über ihre Detailseiten bestätigt. „Kein Treffer“ beschreibt diesen Umfang und beweist keine weltweite oder vom Shop nicht veröffentlichte Abwesenheit.

| Händler | Gelesene Katalogseiten | Treffer | Umfang / Grenze |
| --- | ---: | ---: | --- |
| FantasiaCards | 5 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| House of Cards & Games | 12 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| Senpai-Cards | 1 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| Johto-Cards | 2 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| BulkParadise TCG | 4 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| New Era TCG | 1 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| Gem Cards | 2 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| Xtreme Hits | 1 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| cardcosmos | 16 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| YONKO TCG | 3 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| Gate to the Games | 3 | 2 | Relevanter öffentlicher Katalog durchlaufen |
| collect-it | 3 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| Trader-Online | 0 | 0 | Kein Dragon-Ball-Bereich konfiguriert; auch in der geprüften Hauptnavigation keiner gefunden. Keine Aussage über unverlinkte Produkte. |
| Card-Corner | 1 | 0 | Dragon-Ball-Kategorie separat vollständig geprüft: vier Produkte, kein B32-Treffer; regulär ergänzt |
| LottiCards | 0 | 0 | Kein Dragon-Ball-Bereich konfiguriert; auch in der geprüften Hauptnavigation keiner gefunden. Keine Aussage über unverlinkte Produkte. |
| Müller | 8 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| CrispyCards | 61 | 0 | Relevanter öffentlicher Katalog durchlaufen |
| Spielewelt | 79 | 0 | 79 Seiten geprüft; Abrufbudget erreicht. Rest nicht geprüft, daher keine vollständige Abwesenheitsaussage. |
| JustNerdsTCG | 1 | 1 | Relevanter öffentlicher Katalog durchlaufen |
| Miki's Card Shop | 3 | 1 | Relevanter öffentlicher Katalog durchlaufen |
| S-Games | 29 | 1 | Relevanter öffentlicher Katalog durchlaufen |
| Evolution TCG | 10 | 2 | Relevanter öffentlicher Katalog durchlaufen |
| ComicPlanet | 3 | 2 | Relevanter öffentlicher Katalog durchlaufen |

## Verifizierte B32-Angebote

| Händler | Einheit | Preis | Status | Produkt |
| --- | --- | --- | --- | --- |
| Gate to the Games | booster | 4.99 EUR | preorder | [Produkt](https://www.gate-to-the-games.de/Dragon-Ball-Super-Chromatic-Ascension-Booster-DBS-B32-englisch) |
| Gate to the Games | display | 99.90 EUR | preorder | [Produkt](https://www.gate-to-the-games.de/Dragon-Ball-Super-Chromatic-Ascension-Booster-Display-DBS-B32-englisch) |
| JustNerdsTCG | display | Unbekannt | out_of_stock | [Produkt](https://justnerdstcg.de/products/dragon-ball-super-card-game-masters-booster-display-set-05-dbs-b32-englisch?variant=58038550954316) |
| Miki's Card Shop | display | 89.99 EUR | out_of_stock | [Produkt](https://www.mikiscardshop.at/products/dragon-ball-super-card-game-masters-booster-display-ub05-dbs-b32-englisch-vorbestellung?variant=57429256503631) |
| Evolution TCG | display | 175.00 EUR | out_of_stock | [Produkt](https://evlutcg.com/products/dragon-ball-super-card-game-masters-booster-display-ub05-dbs-b-32-20-packs-en?variant=52887341564251) |
| Evolution TCG | case | 2100.00 EUR | out_of_stock | [Produkt](https://evlutcg.com/products/dragon-ball-super-card-game-masters-b32-ultra-bout-set-5-sealed-case-12x-booster-boxes-english?variant=52935663255899) |
| ComicPlanet | booster | 4.99 EUR | preorder | [Produkt](https://www.comicplanet.de/sammelkarten/dragon-ball/display-db/dragonball-super-card-game-masters-ub05-b32-booster-englisch) |
| ComicPlanet | display | 94.99 EUR | out_of_stock | [Produkt](https://www.comicplanet.de/sammelkarten/dragon-ball/display-db/dragonball-super-card-game-masters-ub05-b32-booster-display-englisch) |
| S-Games | display | 140.00 EUR | out_of_stock | [Produkt](https://s-games.at/products/preorder-dragon-ball-super-box-zenkai-new-series-ultra-bout-5-b32-eng-20-packs?variant=53936023142741) |

Alle neun Angebote wurden als Dragon Ball Masters / B-32 klassifiziert. Bei Gate to the Games waren Booster (4,99 EUR) und Display (99,90 EUR) vorbestellbar. Die bisherige Importlücke entstand dort durch den noch laufenden Pokémon-Abschnitt.

## Betrieb und Verifikation

- **168 Backendtests gegen eine separate PostgreSQL-Testdatenbank bestanden.** Die Testcontainer wurden anschließend entfernt. Lokal: 166 bestanden, zwei PostgreSQL-Sperrtests übersprungen.
- Frontend-Typecheck und Produktionsbuild bestanden. Die Liveprüfung der Shopware-Paginierung bestätigte unterschiedliche Pokémon-Seiten eins und zwei; Seite drei wurde als nächste Seite erkannt.
- Fünf neue Quellen wurden mit ihren konkreten Produktvarianten live geprüft. Bestellbare Booster und nicht bestellbare Displays wurden getrennt bestätigt. Für die Verifikation wurden keine Benachrichtigungen erzeugt.
- Vor der Installation wurden Datenbank, Konfiguration, alte Quelldateien und bisheriges Image gesichert. Schemaänderungen sind nicht erforderlich.
- Bestehende Suchregeln werden nicht überschrieben. Die neue normale Suchregel „Dragon Ball Masters B32 - Displays & Cases“ enthält Masters, B-32, Englisch sowie ausdrücklich ungeklärte Sprachen, Display/Case und Vorbestellungen. Ein Evolution-Display nennt die Sprache nicht in den verwendeten Produktmetadaten; es bleibt `unknown` und wird nicht mit bestätigten englischen Produkten zusammengeführt. Die Regel nutzt den bereits konfigurierten Discord-Kanal. Die neun Direktbeobachtungen haben selbst keine zusätzlichen Benachrichtigungskanäle, damit keine parallelen Alarme für dieselbe Wunschliste entstehen.
- Der normale Katalogimport der fünf neuen Händler wird zusätzlich zu den neun Direktbeobachtungen ausgeführt. Damit sind diese Händler allgemeine Quellen und keine nur auf das recherchierte Set beschränkten Beobachtungen.
- API und Worker laufen produktiv mit der geprüften Version. Alle fünf neuen Händler haben bereits einen normalen Katalogabschnitt erfolgreich importiert, ohne Quellenfehler. Bestehende offene Cursor wurden erhalten; Card-Corner wurde um den neuen Bereich ergänzt.
- Die abschließende öffentliche HTTPS-Prüfung bestätigte 23 aktive Händler, neun B32-Angebote, drei vorbestellbare Varianten und sieben Treffer der gespeicherten Display-/Case-Suche. Nicht authentifizierte Händlerabfragen liefern weiterhin 401. Der geladene Frontend-Build enthält die neue Aktion „Treffer anzeigen“.
- Der Worker hat die getrennte Aktualisierung mit gespeichertem nächsten Prüfzeitpunkt produktiv ausgeführt; alle neun Direktbeobachtungen wurden erfolgreich geprüft. Das offene Katalogverfahren bleibt davon unabhängig. Die vollständigen neuen Katalogdurchläufe laufen weiter.
