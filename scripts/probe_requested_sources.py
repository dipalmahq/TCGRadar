"""Verify the requested merchants without database writes or notifications."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

from probe_additional_sources import probe

REQUESTED = {"gate-to-the-games", "collect-it", "trader-online", "card-corner",
             "lotticards", "mueller", "crispycards", "spielewelt"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop", choices=sorted(REQUESTED))
    parser.add_argument("--output", default="data/requested-source-verification.json")
    args = parser.parse_args()
    shops = json.loads(Path("config/shops.json").read_text(encoding="utf-8"))
    shops = [s for s in shops if s["slug"] in REQUESTED and (not args.shop or s["slug"] == args.shop)]
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(probe, shops):
            results.append(result)
            print(json.dumps(result, ensure_ascii=True), flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "shops": results},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(1 if any(r.get("error") or not r.get("accepted") or not r.get("samples") or
                             not all(s["fresh_detail_matches"] for s in r.get("samples", []))
                             for r in results) else 0)
