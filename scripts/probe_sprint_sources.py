"""Read-only bounded discovery of candidate shops; local evidence is gitignored."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path

from app.adapters import ADAPTERS
from app.adapters.base import ShopClient
from app.config import Settings
from app.domain import classify

CANDIDATES = [
    {"slug": "senpai-cards", "name": "Senpai-Cards", "base_url": "https://senpai-cards.de", "adapter": "woocommerce", "config": {"page_size": 10, "max_pages": 1, "searches": ["One Piece", "Fusion World", "Pokemon"]}},
    {"slug": "johto-cards", "name": "Johto-Cards", "base_url": "https://johto-cards.de", "adapter": "woocommerce", "config": {"page_size": 10, "max_pages": 1, "searches": ["Pokemon", "One Piece", "Fusion World"]}},
    {"slug": "bulkparadise", "name": "BulkParadise TCG", "base_url": "https://bulkparadise-tcg.de", "adapter": "woocommerce", "config": {"page_size": 10, "max_pages": 1, "searches": ["Pokemon", "One Piece", "Fusion World"]}},
]


def probe(shop):
    client = ShopClient(shop["base_url"], Settings(_env_file=None, request_delay_seconds=2))
    try:
        result = ADAPTERS[shop["adapter"]](client, shop["config"]).discover()
        rows = []
        for offer in result.offers:
            identity = classify(offer, shop["slug"])
            rows.append({"offer": asdict(offer), "identity": asdict(identity) if identity else None})
        folder = Path("data/sprint-probes")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (shop["slug"] + ".json")).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        accepted = [r for r in rows if r["identity"]]
        return {"shop": shop["slug"], "scanned": result.scanned_count, "accepted": len(accepted), "games": dict(Counter(r["identity"]["game"] for r in accepted)), "warnings": result.warnings, "sample": [{"title": r["offer"]["title"], "price_minor": r["offer"]["price_minor"], "availability": r["offer"]["availability"], "type": r["identity"]["product_type"], "language": r["identity"]["language"]} for r in accepted[:3]]}
    except Exception as exc:
        return {"shop": shop["slug"], "error_type": type(exc).__name__, "error": str(exc) if type(exc).__name__ == "SourceError" else "Unexpected failure"}
    finally:
        client.close()


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(probe, CANDIDATES):
            print(json.dumps(result, ensure_ascii=True), flush=True)
