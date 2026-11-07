"""Read-only reconnaissance; raw public pages stay in ignored data/."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from bs4 import BeautifulSoup

from app.adapters.base import ShopClient
from app.config import Settings

SOURCES = {
    "gate-to-the-games": "https://www.gate-to-the-games.de",
    "games-island": "https://games-island.eu",
    "collect-it": "https://www.collect-it.de",
    "trader-online": "https://trader-online.de",
    "card-corner": "https://www.card-corner.de",
    "smyths-toys": "https://www.smythstoys.com",
    "mueller": "https://www.mueller.de",
    "lotticards": "https://www.lotticards.de",
    "crispycards": "https://crispycards.de",
    "spielewelt": "https://spielewelt.de",
}


def inspect(item):
    slug, base = item
    folder = Path("data/requested-sources") / slug
    folder.mkdir(parents=True, exist_ok=True)
    client = ShopClient(base, Settings(_env_file=None, environment="development", api_key=""))
    client.client.headers["Accept"] = "text/html,application/xhtml+xml;q=0.9"
    try:
        response = client.get("/de/de-de" if slug == "smyths-toys" else "/")
        (folder / "home.html").write_text(response.text, encoding="utf-8")
        soup = BeautifulSoup(response.text, "html.parser")
        links = {a.get("href"): a.get_text(" ", strip=True) for a in soup.select("a[href]")}
        links = {url: text for url, text in links.items() if any(word in (text + " " + url).lower() for word in ("pokemon", "pokémon", "one-piece", "one piece", "dragon", "booster", "display"))}
        result = {"shop": slug, "url": str(response.url), "bytes": len(response.content),
                  "generator": [str(m) for m in soup.select('meta[name="generator"]')],
                  "jsonld": [s.get_text()[:800] for s in soup.select('script[type="application/ld+json"]')][:3],
                  "links": dict(list(links.items())[:80])}
    except Exception as error:
        result = {"shop": slug, "error": str(error)}
    finally:
        client.close()
    (folder / "inspection.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(inspect, SOURCES.items()))
