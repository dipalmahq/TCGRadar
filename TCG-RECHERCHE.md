# TCG-Einkaufsradar für Streamer

Recherche vom 06.11.2026. Bestätigter Rahmen: Deutschland/EU; One Piece, Dragon Ball und Pokémon. Open Source soll verwendet werden, soweit es die Anforderungen erfüllt. Sprachen, Mengen und Lieblingsshops sind noch offen. Für Dragon Ball werden Masters und Fusion World vorläufig getrennt berücksichtigt, bis die gewünschte Produktreihe feststeht.

## Empfehlung

Ein gemeinsames Einkaufsradar bauen: verfügbare versiegelte Produkte finden, tatsächliche Einkaufskosten vergleichen und passende Angebote schnell an die Streamer melden. Für regelmäßigen Warenbedarf zusätzlich B2B-Angebote, Vorbestellungen und Lieferzusagen verwalten.

Zuerst einen kleinen Pilot mit 5–10 ausgewählten Shops und 20–50 Produkten umsetzen. Damit überprüfen, ob die Daten zuverlässig sind und die Jungs tatsächlich passende Ware bekommen. Erst danach die Shopanzahl erhöhen.

### Entscheidung zur Open-Source-Nutzung

Für den ersten Datenpilot ist changedetection.io der bevorzugte Kandidat für die Überwachung bekannter Produktseiten. Die Software ist nicht an ein bestimmtes TCG gebunden. Ihre dokumentierten Restock- und Preisfunktionen decken einen Teil des Vorhabens ab. Die tatsächliche Erkennung muss anhand der ausgewählten DE/EU-Shops geprüft werden. Bei einem eigenen Backend ist Apprise ein Kandidat für die Benachrichtigungen; changedetection.io bringt bereits eigene Benachrichtigungen mit, sodass keine zweite Zustellungsschicht nötig ist.

Eine direkt einsetzbare Komplettlösung für alle bestätigten Anforderungen wurde in dieser Recherche nicht nachgewiesen. Der gemeinsame Katalog, der präzise Abgleich von Produktvarianten, Versandkosten und Team-Bedarf benötigen eigene Konfiguration beziehungsweise Erweiterungen. Eine Übernahme bestehender Software hängt von ihrem praktischen Ergebnis und den konkreten Lizenzbedingungen ab.

Der TCG Restock Watcher beschreibt genau die drei gewünschten TCGs, ist aber wegen der überwiegend nordamerikanischen Händler und nicht eindeutig erkennbarer Lizenz vorerst fachliche Inspiration. Huginn bleibt eine Alternative für frei kombinierbare Abläufe unter MIT-Lizenz. Der ebenfalls untersuchte [Dam998/shopify-monitor](https://github.com/Dam998/shopify-monitor) ist laut GitHub seit April 2026 archiviert und wird deshalb nicht als bevorzugte Basis eingeplant.

Die folgenden Funktionen, Architekturentscheidungen und Zeitbudgets sind eigene Vorschläge aus der Recherche. Verifizierte Eigenschaften externer Angebote sind direkt verlinkt. Repositories und Dokumentation wurden recherchiert; die Tools wurden nicht installiert und ihre Shop-Anbindungen nicht im Betrieb getestet. Suchindex und gelieferte Seiten können zeitversetzt sein. Dies ist keine Zusicherung aktueller Lagerbestände.

## Was das Tool leisten kann

| Funktion | Nutzen | Einordnung |
| --- | --- | --- |
| Restock-Erkennung | Meldet ausverkauft → verfügbar | Gut für bekannte Produktseiten; Qualität hängt vom Shop ab |
| Neue Produkte entdecken | Findet neue Listings und Vorbestellungen | Kategorien, Suchseiten und verfügbare Feeds zusätzlich beobachten |
| Preisalarm | Meldet nur unter persönlichem Höchstpreis | Früh sinnvoll; Versandkosten einbeziehen |
| Preis pro Booster | Vergleicht Displays, Bundles und Kollektionen | Nur mit korrekt hinterlegten Inhalten; gemischte Sets getrennt behandeln |
| Shopübergreifende Suche | Filter nach Spiel, Set, Sprache und Verpackung | Gemeinsamen Produktkatalog aufbauen |
| Lieferbarkeit bis zum Stream | Priorisiert rechtzeitig lieferbare Ware | Lieferzeitangaben als Schätzung kennzeichnen |
| Kauflimits anzeigen | Zeigt, ob ein Angebot zum Mengenbedarf passt | Nur bekannte Limits zeigen; unbekannt bleibt unbekannt |
| Gemeinsame Einkaufsliste | Bedarf, Zuständigkeit und Bestellungen bündeln | Verhindert versehentliche Doppelkäufe |
| B2B-Angebote und Vorbestellungen | Unterstützt wiederkehrende Beschaffung | Abhängig von freigeschalteten Händlerkonten und zugesagten Mengen |
| Preisverlauf | Ordnet Angebote gegenüber eigenen Beobachtungen ein | Keine vollständige Markthistorie behaupten |
| Filialbestand | Zeigt gegebenenfalls lokale Alternativen | Gesonderte Integration pro Händler und Standort nötig |

Beispiel für eine Suchregel: „Pokémon, Set X, deutsch, versiegeltes Display mit 36 Boostern, bis 150 Euro inklusive Versand nach Deutschland; Vorbestellungen separat.“

Beispiel für einen Alarm, ausschließlich fiktive Werte: „Set X DE, 36 Booster; 144,90 Euro + 4,90 Euro Versand = 149,80 Euro / 4,16 Euro pro Booster. Laut Shop lieferbar. Zuletzt geprüft 14:32. Kauflimit unbekannt. Shop öffnen.“

## Datenquellen und realistische Grenzen

### Direkte Shops: erste Priorität

Shopify dokumentiert einen Produkt-JSON-Endpunkt unter `/{locale}/products/{product-handle}.js`. Damit lassen sich strukturierte Produktdaten verarbeiten. Die konkrete Nutzbarkeit, Varianten und Preiswährung müssen pro Shop geprüft werden. Ein öffentlicher Endpunkt ist keine pauschale Erlaubnis für beliebiges automatisiertes Abrufen. [Shopify Product API](https://shopify.dev/docs/api/ajax/reference/product)

WooCommerce stellt über die Store API öffentliche Produktdaten mit Preis-, Kaufbarkeits- und Bestandsfeldern bereit. Das ist ein zweiter sinnvoller Adapter, sofern der jeweilige Shop ihn anbietet. [WooCommerce Products API](https://developer.woocommerce.com/docs/apis/store-api/resources-endpoints/products)

Bei weiteren Shops: zunächst strukturierte Produktinformationen im HTML auswerten, danach gezielte HTML-Selektoren; einen gerenderten Browser nur einsetzen, wenn die Seite ihn benötigt. Änderungen an Shopseiten verursachen laufenden Wartungsaufwand. Abrufraten, Nutzungsbedingungen und gegebenenfalls vereinbarte Datenzugänge gehören zur Auswahl jedes Adapters.

Deutsche Kandidaten für eine spätere Machbarkeitsprüfung sind beispielsweise [Gate to the Games](https://www.gate-to-the-games.de/Pokemon-Karten/Pokemon-Displays/) und [Smyths Toys](https://www.smythstoys.com/de/de-de/spielzeug/action-spielzeug/pokemon/pokemon-karten/c/SM1001012002). Das sind recherchierte Produktquellen, keine geprüften Integrationen oder Händlerempfehlungen. Die Gate-Kategorie zeigt unterschiedliche Displaygrößen und Lieferstatus; genau diese Unterschiede muss der Produktabgleich erhalten.

### CardTrader: interessante zusätzliche API

Die offizielle Dokumentation beschreibt Spiele, Kategorien einschließlich Booster Box sowie Marktplatzangebote, Filter und Authentifizierung per Kontotoken. Der Marktplatz-Endpunkt ist leicht gecacht; Preis und Menge können daher abweichen. Für einen Pilot zuerst prüfen, ob die gesuchten versiegelten Produkte und passenden EU-Verkäufer ausreichend vertreten sind. [CardTrader API](https://www.cardtrader.com/en-US/docs/api/full/reference)

### Cardmarket: relevant, aber keine sichere Startabhängigkeit

Die offizielle Hilfe meldet derzeit, dass keine neuen API-Anträge angenommen werden. Vorhandene Zugänge haben Regeln zur Weitergabe. Daher neue API-Zugänge nicht für das MVP voraussetzen. Als Ausgangspunkt können manuell gepflegte Referenzen und Links dienen; automatisierte Datenübernahme benötigt einen geeigneten Zugang und geklärte Bedingungen. [Cardmarket API-Hilfe](https://help.cardmarket.com/en/cardmarket-api)

### eBay: spätere Option

Die Browse API kann Angebote suchen und Details liefern. Für den produktiven Einsatz der Buy APIs nennt eBay Zugangsvoraussetzungen und einen Freigabeprozess. Erst Zugang und Geschäftsmodell klären, bevor viel Integration gebaut wird. [eBay Browse API](https://developer.ebay.com/api-docs/buy/static/api-browse.html), [Produktionszugang](https://developer.ebay.com/api-docs/buy/static/buy-requirements.html)

### TCG-Metadaten sind kein Warenbestand

TCGdex bietet eine offene, mehrsprachige Pokémon-Datenbasis für Karten und Sets, auch auf Deutsch. Sie eignet sich für Setnamen und Katalogabgleich. Daraus folgt kein vollständiger Katalog aller versiegelten Handelsprodukte und keine Live-Verfügbarkeit deutscher Shops. Einen eigenen Katalog für Displays, Bundles, Cases und andere Verpackungen vorsehen. [TCGdex](https://tcgdex.dev/)

Für mehrere TCGs Shop-Adapter und Spielekataloge getrennt halten. Ein Shop-Adapter kann Angebote verschiedener Spiele liefern. Die fachliche Zuordnung hängt vom jeweiligen TCG ab:

| TCG | Recherchierte Katalogquelle | Konsequenz für das Tool |
| --- | --- | --- |
| Pokémon | [TCGdex](https://tcgdex.dev/) für Karten und Sets | Verpackungen, Packzahlen und Shopangebote ergänzen |
| One Piece | [Offizielle Produktübersicht](https://en.onepiece-cardgame.com/products/) mit Produktcodes und Kategorien | Region und Sprachversion getrennt führen; Herstellerkatalog liefert keinen Händlerbestand |
| Dragon Ball Fusion World | [Offizieller Produktkatalog](https://www.dbs-cardgame.com/fw/en/products/) mit eigenen Produktreihen und Codes | Eigenes Spiel im Katalog; Region, Sprache und Packungsinhalt erhalten |
| Dragon Ball Masters | [Offizielle Produktseite](https://www.dbs-cardgame.com/us-en/product/dbs-b31.php) mit Booster- und Box-Inhalt | Getrennt von Fusion World führen; Mengen am konkreten Produkt prüfen |

Eine Produktübersicht ist keine offene API und keine pauschale Weiterverwendungslizenz. Herstellerseiten zunächst als Referenz verwenden; Bilder und Inhalte nicht ungeprüft übernehmen. Für keinen dieser Kataloge wurde vollständige Abdeckung aller deutschen beziehungsweise europäischen Handelsvarianten nachgewiesen.

### B2B: für regelmäßige Stream-Mengen mitprüfen

Cards & Toys spricht ausdrücklich Ladengeschäfte, Wiederverkäufer und Streamer an. Der Anbieter verlangt Gewerbenachweis und manuelle Freischaltung; Vorbestellungen gehören zum Angebot. Das belegt eine mögliche Beschaffungsroute, garantiert aber weder Aufnahme noch Preise, Kontingente oder verfügbare Ware. [Geschäftskundenbedingungen](https://business.cardsandtoys.de/kunde-werden)

AMIGO bezeichnet sich selbst als offiziellen Pokémon-Vertrieb für Deutschland und Österreich. Daraus lässt sich keine automatische Direktbelieferung eines Streamers ableiten. [AMIGO International Sales](https://blog.amigo-spiele.de/export/)

Für Dragon Ball Masters nennt die offizielle Produktseite unter anderem ADC Blackfire als Distributor für europäische englischsprachige Ware. Das ist ein Lieferantenkontakt zur weiteren Prüfung, keine Bestätigung eines zugänglichen Kontos oder verfügbarer Zuteilungen. [Offizielle Distributorenangaben](https://www.dbs-cardgame.com/us-en/product/dbs-b31.php)

Eigener Produktvorschlag: Lieferantenliste, Freischaltungsstatus, Vorbestellfrist, Mindestabnahme, Angebotsimport und bestätigte Zuteilung abbilden. Angebote zunächst manuell oder als vom Lieferanten bereitgestellte CSV importieren. Ein reines Restock-Tool löst den wiederkehrenden Mengenbedarf nur teilweise.

## Open Source und öffentliche Projekte als Inspiration

| Projekt | Recherchierter Ansatz | Verwendung für uns |
| --- | --- | --- |
| [changedetection.io](https://github.com/dgtlmoon/changedetection.io) | Seitenänderungen, Preis-/Restock-Erkennung, Selektoren, Browser-Schritte und Benachrichtigungen | Schnell prüfen, ob ausgewählte Produktseiten zuverlässig beobachtbar sind |
| [Huginn](https://github.com/huginn/huginn) | Verknüpft Quellen, Filter und Aktionen über Ereignisse; MIT | Inspiration für Regeln und spätere Lieferanten-Workflows |
| [Apprise](https://github.com/caronc/apprise) | Benachrichtigungsbibliothek für viele Dienste; BSD-2-Clause | Discord, Telegram und E-Mail über eine gemeinsame Schnittstelle |
| [Sneaker-Monitors](https://github.com/yasserqureshi1/Sneaker-Monitors) | Shopbezogene Restock-Monitore mit Discord-Ausgabe; GPL-3.0 | Architektur für getrennte Shop-Adapter studieren; nicht als fertige DE-TCG-Anbindung behandeln |
| [TCG Restock Watcher](https://github.com/mrmadison14/tcg-restock-watcher) | Versiegelte Produkte mehrerer TCGs, Zustandsvergleich, neue Listings und Discord-Meldungen | Besonders passende fachliche Inspiration; dokumentierte Händler überwiegend Nordamerika |

changedetection.io wird im Repository als Apache-2.0 ausgewiesen, führt aber zusätzlich eine eigene Vereinbarung für kommerzielles Hosting. Vor einer Nutzung als angebotener Dienst die konkrete Version und beide Lizenzdateien klären. [Zusätzliche Hosting-Vereinbarung](https://github.com/dgtlmoon/changedetection.io/blob/master/COMMERCIAL_LICENCE.md)

Beim TCG Restock Watcher war in der geöffneten Repositoryübersicht keine eindeutige Lizenz erkennbar. Hier ist nur die öffentlich dokumentierte Idee als Inspiration eingeplant, keine Codeübernahme. Funktionen in READMEs und vorhandene Adapter sind keine Bestätigung, dass diese heute zuverlässig laufen.

## Umsetzungsvorschlag

### Stufe 1: Datenqualität und Nutzen beweisen

- One Piece, Pokémon und Dragon Ball mit wenigen Produkten je Spiel und den wichtigsten Sprachen aufnehmen; Masters und Fusion World als getrennte Produktreihen behandeln.
- 5–10 Shops einzeln auf Zugang, Datenfelder und Stabilität prüfen.
- 20–50 konkrete Produkte zuordnen; auch ausverkaufte Seiten überwachen.
- Restock, neue Listings und Preisgrenzen getrennt behandeln.
- Discord als ersten Alarmkanal verwenden; keine externe Nachricht wird ohne eingerichtete und autorisierte Verbindung verschickt.
- Zu jedem Angebot Quelle, Prüfzeitpunkt und bekannte beziehungsweise unbekannte Angaben anzeigen.
- Über eine kurze Pilotphase Fehlalarme, verpasste Ereignisse, Ausfälle und tatsächlich hilfreiche Funde erfassen.

Prüfkriterien für die Auswahl vorhandener Software: erkennt sie die konkrete Variante statt irgendeines verfügbaren Produkts, trennt sie Vorbestellung und Lagerware, behandelt sie Abruffehler als unbekannt, verhindert sie doppelte Alarme nach Neustart und lässt sie sich ohne manuelle Pflege jeder Einzelmeldung betreiben? Erst mit diesen Ergebnissen entscheidet sich, ob der Monitor dauerhaft übernommen oder durch eigene Adapter ergänzt wird.

### Stufe 2: Gemeinsames Einkaufsdashboard

- Filter nach Spiel, Set, Sprache, Produktform und Lieferstatus.
- Gesamtkosten für eine gewählte Menge und ein Lieferland berechnen.
- Persönliche Regeln, Favoriten und Preisverlauf.
- Bedarf pro Streamer, „übernehme ich“ und „bestellt“ als Teamstatus.
- Lieferanten und Vorbestellfenster aufnehmen.

### Stufe 3: Wiederkehrende Versorgung

- Freigegebene B2B-Daten und Lieferanten-CSV anbinden.
- Bestätigte Bestellung und Lieferzusage vom bloßen Angebot unterscheiden.
- Bestand, erwartete Lieferungen und geplanten Stream-Verbrauch gegenüberstellen.
- Optional Marktplätze und lokale Abholung ergänzen.

## Technisches Konzept für eine eigene App

Eigener Architekturvorschlag: Weboberfläche in TypeScript, unabhängiger Hintergrunddienst für Shopabrufe, relationale Datenbank für Produkte/Angebote/Beobachtungen und ein Benachrichtigungsdienst. Ein kleines Python-Backend mit HTTP-Parsern, optional Playwright und Apprise ist ebenso möglich. Die Wahl richtet sich nach dem späteren Team; kein Framework ist durch diese Recherche vorgeschrieben.

Die Verarbeitung folgt dieser Kette:

`Quelle abrufen → Daten normalisieren → Angebot zuordnen → Änderung erkennen → Suchregel prüfen → Alarm zustellen`

Ein gemeinsamer Abruf pro Quelle bedient alle Streamer. Nicht jeder Nutzer startet einen eigenen Crawler. Produktansicht und Hintergrundabruf müssen getrennt laufen, damit das Monitoring auch bei geschlossener Website funktioniert.

Wesentliche Datenobjekte:

- Produkt: TCG, Set, Sprache, Produktform, Packanzahl, gegebenenfalls GTIN/EAN, Ausführung.
- Angebot: Shop, URL, Variante, Währung, Preis, Lieferland, Versandinformation, Kauflimit und Vorbestellstatus.
- Beobachtung: Zeitpunkt, Erfolg/Fehler, Preis und Status einschließlich „unbekannt“.
- Suchregel: Nutzer/Team, Filter, Preisgrenze, Kanal und Wiederholungsregeln.
- Bedarf/Bestellung: gewünschte Menge, Zuständigkeit, bestellte und bestätigte Menge, Liefertermin.

Besonders wichtig: Ein Fehler oder eine blockierte Seite wird „unbekannt“, nicht „ausverkauft“. Neue Produkte und echte Restocks sind verschiedene Ereignisse. Bei einem neuen Monitor ist noch kein vorheriger Bestandswechsel bekannt. Bereits versendete Ereignisse speichern, damit Neustarts keine Alarmflut erzeugen.

Zuerst GTIN und Variantenmerkmale abgleichen. Wo diese fehlen, kontrollierte Zuordnungen verwenden. Ein deutsches 18er-Display, ein englisches 36er-Display und ein Mini-Tin-Display dürfen trotz ähnlicher Namen nicht als identisches Produkt zusammenfallen. Unbekannte Packzahlen nicht schätzen.

Versandkosten hängen unter anderem von Menge, Zielort und Freigrenzen ab. Ohne diese Angaben nur einen vorläufigen Vergleich zeigen. Für mehrere Produkte die Versandkosten auf Warenkorbebene berechnen, statt sie blind je Artikel zu addieren. Bei B2B die ausgewiesene Preisbasis speichern und Netto-/Bruttoangebote nicht direkt vermischen.

Ein möglicher Startwert für zulässige Shopabrufe sind einige Minuten Abstand, abhängig von Quelle, Umfang und Vereinbarung. Das ist kein garantierter oder universell zulässiger Takt. Bei Polling entspricht die Erkennungsverzögerung im günstigen Fall ungefähr der Zeit bis zum nächsten Abruf plus Verarbeitung; Shop-Caches und Ausfälle kommen hinzu. Ein Alarm garantiert keine Ware im Checkout.

GitHub weist darauf hin, dass zeitgesteuerte Actions verzögert werden und bei hoher Last entfallen können. Deshalb für verlässliche schnelle Alarme einen dauerhaft laufenden Hintergrunddienst bevorzugen. [GitHub-Dokumentation](https://docs.github.com/en/enterprise-cloud%40latest/actions/how-tos/troubleshoot-workflows)

## Was KI beitragen kann

Optional sinnvoll: ähnliche Produktnamen vorschlagen, Set-Aliase erkennen, bereitgestellte Lieferantenangebote strukturieren und Änderungen verständlich zusammenfassen. Vorschläge kontrollieren und Unsicherheit sichtbar lassen. Bestandsstatus, Preis und Kaufentscheidung auf nachvollziehbare Quelldaten und Regeln stützen.

## Aufwand und Betrieb

Eigene grobe Planungsschätzung, keine Anbieterpreise oder Zusage:

| Umfang | Größenordnung unter günstigen Bedingungen |
| --- | --- |
| Kleiner Monitor-Pilot auf gut lesbaren Seiten | Einige Arbeitstage |
| Nutzbares Team-MVP mit Dashboard, Regeln und mehreren Adaptern | Etwa 2–4 Wochen Entwicklungsarbeit |
| Breite Abdeckung inklusive schwieriger Shops und B2B | Mehrere weitere Wochen, anschließend laufende Pflege |

Der größte Unsicherheitsfaktor sind Shopzugänge und Datenqualität. Ein kleiner selbst gehosteter Betrieb kann als vorläufiges Budget mit etwa 10–40 Euro monatlich angesetzt werden, muss aber nach Messung des tatsächlichen Browserbedarfs und Auswahl eines Hosters neu kalkuliert werden. Datenlizenzen, kostenpflichtige Kanäle und Entwicklungszeit sind darin nicht enthalten.

## Noch zu entscheiden

1. Welche Sprachen und Sets brauchen die Jungs; bei Dragon Ball Masters, Fusion World oder beide?
2. Welche Mengen kaufen sie pro Woche und zu welchen Höchstpreisen?
3. Welche Shops und Lieferanten nutzen sie bereits?
4. Bestehen Gewerbe- oder Händlerkonten?
5. Ist das Tool nur für die Gruppe oder später ein Dienst für weitere Nutzer?

Diese Antworten bestimmen die ersten Adapter und die Suchregeln. Der sinnvollste nächste Umsetzungsschritt ist ein überprüfbarer kleiner Datenpilot mit echten Wunschprodukten.
