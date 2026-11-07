"""Read-only, bounded checks of additional merchant candidates. No alerts sent."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import argparse
import json

from app.adapters import ADAPTERS
from app.adapters.base import ShopClient, SourceError
from app.config import Settings
from app.domain import classify

NEW_SHOPS = {"newera-tcg", "gemcards", "yonko-tcg", "xtremehits", "cardcosmos"}


def probe(shop):
    slug, base = shop["slug"], shop["base_url"]
    adapter_name = shop["adapter"]
    settings = Settings(_env_file=None, environment="development", api_key="", request_delay_seconds=2)
    client = ShopClient(base, settings)
    config = shop["config"]
    try:
        adapter = ADAPTERS[adapter_name](client, config)
        result = adapter.discover()
        accepted = [(offer, classify(offer, slug)) for offer in result.offers]
        accepted = [(offer, identity) for offer, identity in accepted if identity]
        samples = []
        seen_handles = set()
        for offer, identity in accepted:
            handle = offer.url.split("?")[0]
            if handle in seen_handles:
                continue
            seen_handles.add(handle)
            fresh = adapter.fetch_url(offer.url)
            match = next((o for o in fresh if o.external_id == offer.external_id), None)
            samples.append({"title": offer.title, "url": offer.url,
                "price_minor": offer.price_minor, "currency": offer.currency,
                "availability": offer.availability, "type": identity.product_type,
                "language": identity.language,
                "fresh_detail_matches": bool(match and
                    (offer.price_minor, offer.currency, offer.availability) ==
                    (match.price_minor, match.currency, match.availability))})
            if len(samples) == 3:
                break
        return {"shop": slug, "base_url": base, "adapter": adapter_name,
            "scanned": result.scanned_count, "accepted": len(accepted),
            "games": dict(Counter(identity.game for _, identity in accepted)),
            "warnings": result.warnings,
            "samples": samples}
    except SourceError as exc:
        return {"shop": slug, "adapter": adapter_name, "error": str(exc)}
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop")
    args = parser.parse_args()
    settings = Settings()
    shops = json.loads(settings.shops_file.read_text())
    candidates = [s for s in shops if s["slug"] in NEW_SHOPS and (not args.shop or s["slug"] == args.shop)]
    if not candidates:
        parser.error("No configured additional shop matched")
    failed = False
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(probe, candidates):
            print(json.dumps(result, ensure_ascii=True), flush=True)
            failed |= bool(result.get("error") or not result.get("accepted") or
                len(result.get("samples", [])) < 3 or
                not all(s["fresh_detail_matches"] for s in result.get("samples", [])))
    raise SystemExit(1 if failed else 0)
