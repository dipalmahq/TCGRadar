# Spielewelt: Versandverfügbarkeit

Die Varianten `66340273488221` (EB05 Heroines Edition vol.2 Display EN) und
`65644686180701` (The World's Strongest Warriors Display EN) wurden im Radar
fälschlich als `in_stock` geführt.

Die Live-Prüfung am 07.11.2026 zeigte für beide:

- Produkt-JSON-LD: `schema.org/InStock`.
- Shopify Ajax `products/<handle>.js`: `available: true`.
- Zusätzliche Versandprüfung der echten Produktseite: `availableForSale: false`
  und `currentlyNotInStock: false`.

Die generischen Produktdaten reichen bei diesem Shop nicht aus, um die
Online-Lieferbarkeit zu bestätigen. Sein öffentliches Theme-Skript
`shipping-availability.js` sperrt die Kaufaktion anhand einer zusätzlichen,
tokenlosen Storefront-Abfrage. Der Radar verwendet jetzt dieselbe feste
Leseabfrage für jede konfigurierte Spielewelt-Variante:

```graphql
query ShippingAvailability($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on ProductVariant { id availableForSale currentlyNotInStock }
  }
}
```

Der Shop verlinkt dafür
`https://spielewelt-amberg.myshopify.com/api/2026-10/graphql.json`.
Es werden keine Tokens aus dem Browser übernommen und keine Warenkorb- oder
Bestellaktionen ausgeführt. Der Client erlaubt nur konfigurierte HTTPS-
Storefront-Endpunkte und diese fest definierte Leseabfrage, keine Mutationen.
Weiterleitungen und beliebige Fremdserver sind ausgeschlossen.

`availableForSale: false` ergibt `out_of_stock` für Online-Angebote. Bei
bestellbarer Ware ohne Lagerbestand wird die bestehende Kategorie `preorder`
verwendet. Fehlende, fehlerhafte oder widersprüchliche Antworten ergeben
`unknown` mit einem Hinweis; es gibt keinen Rückfall auf `InStock` aus JSON-LD.
Eine Drosselung bewahrt dieses unbekannte Ergebnis sowie den offenen Cursor
und pausiert den Durchlauf für den nächsten Versuch.

17 Regressionstests prüfen den abweichenden Versandstatus, tatsächlich lieferbare
Kontrollfälle, Nachbestellungen, fehlende Varianten, kaputte Antworten, erlaubte
Endpunkte sowie die Fortsetzung nach HTTP 429. Versteckte „Ausverkauft“-Texte
im HTML werden ausdrücklich nicht als Beweis für ausverkaufte Ware gewertet.

Bei der Kontrolle fiel außerdem auf, dass Akzente bei der Normalisierung
innerhalb eines Wortes als Trennzeichen behandelt wurden. Zusammengesetzte
und zerlegte Schreibweisen von „Pokémon“ werden jetzt wie „Pokemon“ erkannt;
zwei weitere Regressionstests sichern dies ab.

## Produktionsabnahme

Backup erstellt; **118 Tests gegen eine isolierte PostgreSQL-Datenbank bestanden**.
Alle 18 bereits gespeicherten Spielewelt-Angebote frisch mit Produktdetail und
zusätzlicher Versandabfrage geprüft: **14 online nicht lieferbar, vier lieferbar**,
keine verbleibenden Prüffehler. Beide gemeldeten Varianten sind `out_of_stock`.
Es wurden keine Benachrichtigungen erzeugt. Der Katalog-Cursor blieb erhalten.
API und Worker laufen mit dem geprüften Fix. Zahlen und Status sind Beobachtungen
vom 07.11.2026 und werden bei weiteren Abrufen aktualisiert.
