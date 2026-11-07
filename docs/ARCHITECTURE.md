# Architektur und Open-Source-Entscheidung

## Mehrfachfilter und Regelbearbeitung

`GET /api/offers` akzeptiert wiederholte Query-Parameter, zum Beispiel
`?game=one-piece&game=pokemon&language=de&language=en`. Innerhalb einer Gruppe
gilt ODER, zwischen Gruppen UND; fehlende Gruppen schränken nicht ein.
Je Gruppe sind höchstens 50 Werte erlaubt. Stale-Angebote gelten auch bei
kombiniertem Bestandsfilter ausschließlich als unbekannt.

Regeln speichern `game_ids`, `merchant_ids`, `set_codes`, `languages` und
`product_types` als JSON-Listen. Ältere Einzelwertfelder bleiben kompatibel;
Einzelwert und Liste derselben Dimension dürfen nicht gleichzeitig gesetzt
werden. `PUT /api/rules/{id}` ersetzt die bearbeitbare Regel vollständig,
`PATCH` bleibt für Aktivieren/Pausieren zuständig. Vorlagen werden ausdrücklich
per Verwaltungsbefehl angelegt und sind zunächst pausiert.

Erneut abgelehnte historische Angebote erhalten `excluded=true`. Ihre Historie
bleibt erhalten; Radar, Übersicht, Vergleich, Ereignisliste und Alarm-Matching
schließen sie aus. Neue valide Quellzuordnungen können sie wieder zulassen.

## Modularer Monolith, zwei Prozesse

Ein Python-Paket enthält API, Domänenlogik, Datenzugriffe und Adapter. FastAPI
bedient API und gebautes Vue-Frontend. Ein eigenständig gestarteter Worker
entdeckt Produkte, prüft Links und verarbeitet die persistente Versandwarteschlange.
PostgreSQL ist die Produktionsdatenbank; SQLite unterstützt lokale Entwicklung
und schnelle Tests. Alembic verwaltet das Schema.

Es gibt keine Redis-/Celery-/Kafka-Abhängigkeit. Bei der vorgesehenen kleinen
Crew und wenigen Shops genügt ein Worker mit Datenbanksperren. Die API reiht
manuelle Shop-Prüfungen ein; sie startet keine unkoordinierten Hintergrundthreads.

Unter PostgreSQL hält jeder Shopabruf auf einer eigenen Verbindung eine
transaktionsgebundene Advisory-Sperre. Sie umfasst auch die ORM-Commits und wird
bei Verbindungsverlust automatisch freigegeben. So kann ein neuer Worker eine
nach einem Abbruch verwaiste Zeitmarkierung sofort übernehmen, während eine
wirklich aktive Prüfung weiterhin nicht überlappt. SQLite verwendet für die
lokale Entwicklung weiterhin die begrenzte Zeit-Lease.

## Wiederverwendung

| Komponente | Entscheidung |
| --- | --- |
| FastAPI, Pydantic, SQLAlchemy, Alembic | API, Validierung, Persistenz und Migrationen |
| HTTPX, Beautiful Soup | Öffentliche Kataloge abrufen und Beschreibungstext normalisieren |
| Vue 3, TypeScript, Vite, Lucide | Dashboard, Build und bestehendes Iconsystem |
| Shopify-Produktdaten und WooCommerce Store API | Wiederverwendbare Shop-Adapter statt individueller Browser-Skripte |
| changedetection.io | Nicht integriert: zusätzliche Oberfläche/Dienst, während Entdeckung, Varianten und gemeinsamer Katalog ohnehin eigene Logik brauchen; zusätzliche Hosting-Lizenzfrage laut Recherche |
| Apprise | Für nur zwei ausgehende HTTP-Ziele zunächst nicht nötig; die Versandwarteschlange lässt eine spätere Erweiterung zu |
| Öffentliche TCG-Monitore | Nur fachliche Inspiration; kein Code aus einem Repository mit unklarer Lizenz übernommen |

Quellen: [Shopify Ajax Product API](https://shopify.dev/docs/api/ajax/reference/product),
[WooCommerce Store Products API](https://developer.woocommerce.com/docs/apis/store-api/resources-endpoints/products),
[Discord Webhooks](https://discord.com/developers/docs/resources/webhook),
[Telegram Bot API](https://core.telegram.org/bots/api#sendmessage).

Die Paketversionen sind über `backend/requirements.lock` und
`frontend/pnpm-lock.yaml` festgehalten. Die Bibliotheken behalten ihre jeweiligen
Lizenzen; es wurde kein fremdes Gesamtprojekt unter eigener Lizenz umetikettiert.

## Produktidentität

TCG/Produktlinie → Set → kanonisches Produkt → Händlerangebot → Beobachtungen
und Ereignisse. Der Angebotsschlüssel ist `(merchant_id, external_id)`; Varianten
haben ihre eigenen externen IDs. Der Produktvergleich verwendet dieselbe
kanonische Produkt-ID.

Automatisches Zusammenführen erfolgt nur anhand einer gültigen GTIN plus
kompatiblen Merkmalen oder einer engen Kombination expliziter Setcodes, Sprache,
Produktform, Packanzahl, Zustand und Standardausführung. Unsichere Zuordnungen
bekommen einen eigenen Schlüssel je Händler und Variante. Es gibt kein Fuzzy-
Matching auf bloß ähnlich klingende Namen und keine angenommene universelle
Displaygröße. Pokémon-Set-Aliase sind eine kleine, erweiterbare Liste.

Shopify-Listenpreise sind Dezimalbeträge, die Einzelprodukt-Ajax-API liefert
Centbeträge. WooCommerce berücksichtigt seine ausgewiesene Währungseinheit.
Variable WooCommerce-Eltern dürfen nie ihren Mindestpreis als Displaypreis liefern.
Sind Einzelvarianten nicht lesbar, wird der Elternpreis übersprungen.

## Ereignisse und Alarme

Ein erfolgreicher Abruf schreibt Beobachtungen. Zustandsänderungen erzeugen ein
Ereignis pro Angebotsrevision, gegebenenfalls mit mehreren Änderungen. Die
Benachrichtigungswarteschlange ist durch `(event_id, channel)` eindeutig. Zwei
passende Suchregeln erzeugen dadurch keine zwei Nachrichten. Zustellversuche
werden gespeichert und atomar beansprucht.

HTTP 429 wird zeitversetzt wiederholt. Verbindungsaufbaufehler werden begrenzt
wiederholt. Bei verlorener Antwort oder einem während des Versands unterbrochenen
Worker wird der Status `uncertain`; kein automatisches Replay. Dies priorisiert
die Vermeidung doppelter Nachrichten und kann einen manuell zu prüfenden Alarm
offenlassen. Eine absolute Exactly-once-Zustellung ist ohne Idempotenzunterstützung
des Empfängers nicht zugesichert.

## Fehler- und Zugangsmodell

Abrufe bleiben auf die konfigurierten HTTPS-Ursprünge beschränkt. Produktlinks
können keinen beliebigen internen Host hinzufügen; Weiterleitungen auf fremde
Ursprünge werden abgewiesen. `robots.txt`, Request-Abstände, Antwortgrößen und
ein Request-Budget werden berücksichtigt. Kein Login, CAPTCHA-Umgehen,
Proxy-Rotation, Auto-Kauf oder Warenkorbtest wird ausgeführt.

Ein begrenzter Katalogausschnitt beweist bei Nichtauftauchen keinen Ausverkauf.
Abruffehler machen Bestand unbekannt, erhalten aber den letzten bekannten Zustand,
damit eine Erholung keinen falschen Restock erfindet. Alte Daten werden von der
API als veraltet und unbekannt gekennzeichnet. Preis-/Bestandsbeobachtungen werden
nach der konfigurierten Aufbewahrungszeit gelöscht; Ereignisse bleiben erhalten.
