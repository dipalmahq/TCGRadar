"""Read-only source checks. Raw responses stay in ignored data/live-probes/."""
import concurrent.futures
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

SOURCES = {
    "fantasiacards": "https://fantasiacards.de",
    "house-of-cards": "https://house-of-cards-and-games.de",
    "shiningtcg": "https://www.shiningtcg.at",
}


def probe(item):
    name, base = item
    folder = Path("data/live-probes") / name
    folder.mkdir(parents=True, exist_ok=True)
    paths = ["/robots.txt", "/wp-json/wc/store/v1/products?per_page=20"] if name == "house-of-cards" else ["/robots.txt", "/products.json?limit=50&page=1"]
    for index, path in enumerate(paths):
        req = urllib.request.Request(base + path, headers={"User-Agent": "JoyBoyzTCGRadar/0.1 (+local integration verification)", "Accept": "application/json,text/plain;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                raw = response.read(5_000_000)
                (folder / ("robots.txt" if index == 0 else "catalog.json")).write_bytes(raw)
                print(json.dumps({"source": name, "url": response.url, "status": response.status, "bytes": len(raw), "sample": raw[:500].decode(errors="replace")}, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(json.dumps({"source": name, "path": path, "error": str(exc)}), flush=True)
        time.sleep(2)


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(probe, SOURCES.items()))
