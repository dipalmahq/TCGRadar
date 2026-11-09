# Vollständige Katalogdurchläufe

Die aktive Konfiguration verwendet für alle 26 Händler `full_catalog: true`.
`products_per_category` und `max_pages` sind entfernt. `page_size` bestimmt nur
die Antwortgröße einer Seite, nicht die Gesamtzahl der eingelesenen Produkte.

Seit dem 08.11.2026 hat jeder Händler einen eigenen Worker. Watchlist- und
Bestandsprüfungen haben eigene Fristen und setzen den Katalog-Cursor nicht zurück.
Die Altersgrenze beträgt jetzt 24 Stunden; Details: [Händler-Worker](MERCHANT-WORKERS.md).

## Abdeckung

- Shopify: Gesamtkatalog `/products.json`, bis zur letzten Seite. Keine Auswahl
  von sechs Kollektionen und keine Beschränkung auf die ersten drei Seiten.
- WooCommerce: Gesamtkatalog nach aufsteigender Produkt-ID, alle Seiten und
  alle veröffentlichten Varianten. Die bisherige Grenze von zwölf Varianten
  pro Produkt entfällt. Mindestpreise von Elternartikeln werden weiterhin nicht
  einer konkreten Packung zugeordnet.
  Optional werden vollständige Kategorie-/Schlagwortbereiche statt des gesamten
  Sortiments gelesen. Mehrere Filterbereiche bilden eine Vereinigung; doppelte
  Produkt-IDs werden innerhalb des Durchlaufs nur einmal verarbeitet.
  [Animany: 62 TCG-Katalogeinträge statt 19.309 Shop-Einträgen](ANIMANY-TCG-FILTER.md).
- HTML-Shops: alle Folgeseiten der TCG-Bereiche; bei JTL zusätzlich die
  verlinkten Unterkategorien im Inhaltsbereich. Globale Navigationsmenüs und
  Empfehlungen führen nicht zu einem Wechsel in fremde TCG-Bereiche.
- CrispyCards und Spielewelt: vollständige öffentliche `collections/all`-Seiten.
- Müller: gesamte Sammelkarten-Kategorie mit verifizierter `?page=N`-Navigation.
- Trader-Online: schreibgeschützter AJAX-Kategoriefilter mit gespeicherter
  Seitennummer. Die unbrauchbaren relativen `rel=next`-Links werden nicht verwendet.

Das Radar berücksichtigt weiterhin versiegelte Produkte für One Piece,
Pokémon, Dragon Ball Fusion World und Dragon Ball Masters. Einzelkarten,
Grading, Zubehör und andere TCGs gehören nicht zu diesem Produktumfang.
Öffentlich nicht angebotene, gesperrte oder nicht eindeutig zuordenbare Varianten
können nicht als belegte Angebote erscheinen. Solche Zuordnungslücken werden
gezählt; ein beendeter Seitendurchlauf garantiert keine vollständigen Shopdaten.
Games Island und Smyths bleiben wegen der dokumentierten Abrufsperren inaktiv.

## Fortsetzung statt Gesamtlimit

Der Worker verarbeitet einen Katalog in Abschnitten. Nach einer API-Seite oder
einem HTML-/Variantenabschnitt speichert er den Fortschritt und die gültigen
Angebote in PostgreSQL. Die nächsten Produkte/Seiten folgen im nächsten
Worker-Durchgang. Es gibt keine Gesamtobergrenze für Produkte, Seiten oder
Kategorien innerhalb des konfigurierten Umfangs.

Die Begrenzung auf kurze HTTP-Abschnitte schützt die anderen Händler vor
langen Wartezeiten. Sie schneidet den Katalog nicht ab: `crawl_state` hält die
offenen Seiten, bereits besuchte Produkte und noch offene Varianten fest.
Nach Neustarts wird genau dort fortgesetzt. Ein HTTP-429-Fehler speichert die
bereits erfolgreich eingelesenen Angebote und den noch offenen Abruf; der
Worker wartet mindestens die angegebene Retry-After-Zeit. Er beginnt nicht
wieder bei den ersten sechs Produkten. Wiederholte identische Seiten und
Navigationsschleifen gelten als Fehler, nicht als vollständiger Katalog.

Bei einem Abruffehler erhalten nicht bestätigte Angebote sofort den Status
`unknown` und einen Quellenfehler. Erfolgreich bestätigte Angebote desselben
Teilimports behalten ihren belegten Status. `Retry-After` berücksichtigt sowohl
Sekunden als auch HTTP-Datumsangaben; auch Direktbeobachtungen warten diese Frist ab.
Die HTML-Vorauswahl berücksichtigt Klassifikationsbelege aus Beschreibung und
Kategorie. Eindeutig benannte Shopify-Varianten werden mit ihrem jeweiligen Preis
und ihrer Packungsgröße aufgelöst; uneindeutige Mindestpreise bleiben ausgeschlossen.

Im Händlerbereich stehen erfasste Angebote, Seiten-/Produktfortschritt,
laufender bzw. beendeter Durchlauf und ungeklärte Zuordnungen. Während eines
Durchlaufs sind die Zahlen ausdrücklich Zwischenstände. Ein neuer vollständiger
Durchlauf startet nach dem normalen Händlerintervall. Angaben zur Verfügbarkeit
behalten ihre individuellen Beobachtungszeiten und veralten weiterhin sichtbar.

## Betrieb

Die Migration `81a4f3c26b90` ergänzt ausschließlich `merchants.crawl_state`.
Vor der Migration ein Backup erstellen und den Worker anhalten. Danach Migration,
API und Worker mit demselben Image starten. Ein Schema- oder Konfigurationswechsel
setzt den Katalogfortschritt zurück, wenn sich die Händlerkonfiguration ändert;
gespeicherte Angebote und Regeln bleiben erhalten.

Die Tests prüfen Durchläufe jenseits der früheren Grenzen, alle Varianten über
mehrere Worker-Abschnitte, Fortsetzung nach Drosselung ohne doppelte Ereignisse,
Teilimporte, Seitenschleifen, letzte kurze Seiten und die Abgrenzung fremder TCGs.

## Verifikation am 07.11.2026

97 lokale Backendtests bestanden; die beiden PostgreSQL-Sperrtests wurden lokal
übersprungen. Auf dem Server bestanden **99 Tests gegen eine separate
PostgreSQL-Testdatenbank**. Frontend-Typecheck und Produktionsbuild erfolgreich.
Die vollständige Migrationskette wurde separat ausgeführt; Alembic meldete
anschließend keine ausstehenden Modelländerungen.

Nach privatem Datenbank-/Konfigurationsbackup und Sicherung des bisherigen
Images wurde die Migration produktiv ausgeführt. API und Worker laufen mit
der neuen Version; alle 18 Händler wurden für vollständige Katalogdurchläufe
eingereiht. Die öffentliche HTTPS-API liefert die neuen Fortschrittsfelder.
Der erste Durchlauf ist kein abgeschlossener Gesamtimport: Zwischenstände
werden aktualisiert, solange noch Seiten oder Varianten offen sind.

Bei der abschließenden HTTPS-Prüfung waren **alle 18 Durchläufe gestartet**,
drei bereits abgeschlossen. Insgesamt **1.348 sichtbare Angebote**, keine
Händler-Abruffehler und keine ausstehenden Benachrichtigungen. FantasiaCards
hatte bereits 500 Katalogeinträge über zwei Seiten geprüft. Card-Corner meldete
fünf uneindeutige Produktangebote; diese bleiben als Zuordnungslücken sichtbar.
Der geladene öffentliche JavaScript-Build enthält die neue Fortschrittsanzeige.
Diese Zahlen sind eine Momentaufnahme des noch laufenden ersten Durchlaufs.

Die anschließenden fünf Befunde des Qualitätschecks wurden mit 24 zusätzlichen
Regressionstests korrigiert. **142 Tests gegen die separate PostgreSQL-Testdatenbank
bestanden**. Die Liveprüfung der Trader-Paginierung lieferte vier unterschiedliche
Pokémon-Seiten (50/50/50/2 Produkte) und anschließend 41 One-Piece-Produkte.
Weitere Details und verbleibende Betriebsgrenzen stehen in
`docs/QUALITY-CHECK-2026-11-07.md`.
