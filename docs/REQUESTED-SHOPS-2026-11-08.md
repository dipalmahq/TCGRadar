# Angefragte Shops – 08.11.2026

Die Zuordnung der verkürzten Namen wurde vom Nutzer bestätigt. Neue Händler
werden als reguläre Quellen für den vorhandenen TCG-Produktumfang angebunden.
Bestehende Händler werden nicht doppelt angelegt.

| Anfrage | Zugeordneter Shop | Ergebnis |
| --- | --- | --- |
| Game Island | [Games Island](https://games-island.eu) | Weiterhin keine verifizierte öffentliche Produktquelle: TCG-Kategorien liefern eine Validierungs-/reCAPTCHA-Seite ohne Produkte. Bleibt in `config/shops.pending.json`. |
| Rocket card | [RocketCardStore](https://www.rocketcardstore.de) | Neue reguläre Shopify-Quelle, vollständiger öffentlicher Katalog in fortsetzbaren Seiten. |
| Tobistoys | [TobisToys](https://tobistoys.de) | Neue reguläre Shopify-Quelle, vollständiger öffentlicher Katalog in fortsetzbaren Seiten. |
| Anymani | [Animany](https://animany.de) | Neue reguläre WooCommerce-Store-API-Quelle, vollständiger öffentlicher Katalog, neueste Produkt-IDs zuerst. |
| Cosmicplanet | [ComicPlanet](https://www.comicplanet.de) | Bereits aktiv; keine zweite Quelle angelegt. |
| Crispycards | [CrispyCards](https://crispycards.de) | Bereits aktiv; keine zweite Quelle angelegt. |

## Liveprüfung

- RocketCardStore: 250 Produkte auf Seite eins und 100 auf Seite zwei. 201
  passende Varianten im ersten Abschnitt; drei Varianten separat über ihre
  Produktadresse nachgeprüft. Preis, Währung und Verfügbarkeit stimmten überein.
- TobisToys: 250 Produkte auf Seite eins und 52 auf Seite zwei. 74 passende
  Varianten im ersten Abschnitt; drei Varianten separat nachgeprüft, ebenfalls
  übereinstimmend.
- Animany: Die Store API meldete 19.309 Katalogeinträge, darunter Bücher,
  Merchandise und Turniertickets. Zwei unterschiedliche Seiten mit jeweils 50
  Einträgen wurden geprüft; relevante Angebote werden durch die vorhandene
  Produktklassifikation übernommen. Es gibt keine Gesamtgrenze für Seiten.
  Die konfigurierbare ID-Reihenfolge `desc` bringt aktuelle Veröffentlichungen
  früh in den ersten Durchlauf, während der restliche Katalog weiterläuft.
- Zwei passende Animany-Displays wurden separat nachgeprüft: Das normale OP18-
  Display ist laut Quelle vorbestellbar. Beim „COMMUNITY ONLY“-Artikel ist
  `is_purchasable=false`; sein Status bleibt deshalb `unknown`, obwohl
  `is_in_stock=true` gemeldet wird. Eine Kaufberechtigung wird nicht angenommen.
- Games Island: Die Startseite ist lesbar. `/c/Pokemon`, `/m/Pokemon` und
  `/c/Pokemon/Tins` lieferten HTTP 200 mit „Validating please wait“ und einem
  reCAPTCHA-Hinweis, ohne erkennbare Produktangebote. Eine lesbare Startseite
  genügt nicht für eine funktionierende Bestandsquelle. Die Sperre wurde nicht
  umgangen.
- ComicPlanet und CrispyCards waren bereits aktiviert und meldeten bei der
  Prüfung erfolgreiche letzte Abrufe ohne Quellenfehler.

## Implementierung und Prüfung

Einzige Änderung am Adapter ist eine allgemeine, validierte Option
`catalog_order` für vollständige WooCommerce-Kataloge. Die Vorgabe bleibt `asc`;
Animany verwendet `desc`. Fortsetzung, Variantenauflösung, Seitenende,
Origin-Prüfung, robots.txt, HTTP-Abstände und Retry-After bleiben erhalten.
Die Reihenfolge begrenzt weder Produkte noch Seiten.

Sechs neue Regressionen prüfen beide Reihenfolgen über mehrere Abschnitte,
ungültige Konfiguration sowie die Kombination aus Kategoriebelegen und
tatsächlicher Kaufbarkeit. **182 Tests gegen eine separate PostgreSQL-
Testdatenbank bestanden**. Lokal bestanden 180 Tests, zwei PostgreSQL-Sperrtests
wurden übersprungen. Der Frontend-Code wurde nicht geändert.

Vor der Installation wurden Datenbank und Konfiguration gesichert, die
ersetzten Quelldateien kopiert und das vorherige Image für einen Rückwechsel
aufbewahrt. Änderungen an bestehenden Beobachtungen oder Suchregeln sind für
diese Erweiterung nicht erforderlich.

## Produktive Abnahme

API und Worker laufen mit dem geprüften Image. Die öffentliche HTTPS-Prüfung
bestätigte 26 aktive, eindeutige Händler sowie die neuen Angebote. Nicht
authentifizierter Zugriff auf Händlerdaten liefert weiterhin HTTP 401.

| Neue Quelle | Sichtbare passende Angebote beim Start | Erster Durchlauf |
| --- | ---: | --- |
| RocketCardStore | 327 | Abgeschlossen: 350 Katalogprodukte auf zwei Seiten, keine ungeklärten Detailangebote. |
| TobisToys | 80 | Abgeschlossen: 302 Katalogprodukte auf zwei Seiten, keine ungeklärten Detailangebote. |
| Animany | 2 | Laufend: 100 Katalogeinträge auf zwei Seiten geprüft; weitere Seiten bleiben gespeichert und werden fortgesetzt. |

Diese Zahlen sind Momentaufnahmen und enthalten auch ausverkaufte bzw. nicht
öffentlich kaufbare Angebote. Varianten können dazu führen, dass ein einzelnes
Katalogprodukt mehrere Angebote liefert. Alle bestehenden Katalogcursor wurden
unverändert erhalten; bei der Erstimport-Verifikation wurden keine zusätzlichen
Benachrichtigungen angelegt. Games Island ist nicht als aktive Quelle aufgeführt.
