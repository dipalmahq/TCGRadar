from dataclasses import dataclass, field
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import Settings


class SourceError(Exception):
    """A safe-to-display source error; never includes credentials or response bodies."""


@dataclass
class SourceOffer:
    external_id: str
    title: str
    url: str
    price_minor: int | None
    currency: str
    availability: str
    description: str = ""
    labels: str = ""
    variant_label: str = ""
    language_hint: str = ""
    gtin: str | None = None
    product_type_hint: str = ""


@dataclass
class ScanResult:
    offers: list[SourceOffer] = field(default_factory=list)
    scanned_count: int = 0
    warnings: list[str] = field(default_factory=list)
    # Absence from a bounded catalog is not proof of being sold out.
    coverage_limited: bool = False


class ShopClient:
    def __init__(self, base_url: str, settings: Settings, transport=None):
        self.base_url = base_url.rstrip("/")
        self.origin = urlsplit(self.base_url)
        if self.origin.scheme != "https" or not self.origin.hostname or self.origin.username:
            raise SourceError("Shops must use a configured HTTPS origin")
        self.settings = settings
        self.client = httpx.Client(
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": settings.user_agent, "Accept": "application/json,text/plain;q=0.8"},
            transport=transport,
        )
        self.last_request = 0.0
        self.requests = 0
        self.robots = None

    def close(self):
        self.client.close()

    def safe_url(self, path: str) -> str:
        url = urljoin(self.base_url + "/", path)
        parsed = urlsplit(url)
        if (parsed.scheme, parsed.hostname, parsed.port) != (self.origin.scheme, self.origin.hostname, self.origin.port) or parsed.username or parsed.password:
            raise SourceError("Request outside configured shop origin blocked")
        return url

    def _request(self, url: str) -> httpx.Response:
        for attempt in range(3):
            self.requests += 1
            if self.requests > 80:
                raise SourceError("Per-scan request budget exceeded")
            delay = self.settings.request_delay_seconds - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
            try:
                with self.client.stream("GET", url) as response:
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 8_000_000:
                            raise SourceError("Response exceeds 8 MB limit")
                    headers = {key: value for key, value in response.headers.items() if key.lower() not in ("content-encoding", "content-length")}
                    result = httpx.Response(response.status_code, headers=headers, content=bytes(data), request=response.request)
            except httpx.RequestError as exc:
                if attempt == 2:
                    raise SourceError(f"Source connection failed ({type(exc).__name__})") from None
                time.sleep(2 ** attempt)
                continue
            if result.status_code == 429:
                # Honor long Retry-After by ending this scan; the worker backs off.
                value = result.headers.get("Retry-After", "5")
                wait = int(value) if value.isdigit() else 30
                if wait > 10 or attempt == 2:
                    raise SourceError(f"Source rate limit (HTTP 429; Retry-After {value[:30]})")
                time.sleep(max(1, wait))
                continue
            if result.status_code >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return result
        raise SourceError("Source request failed")

    def get(self, path: str) -> httpx.Response:
        url = self.safe_url(path)
        if self.robots is None:
            response = self._request(self.safe_url("/robots.txt"))
            if response.status_code not in (200, 404):
                raise SourceError(f"Unable to verify robots.txt (HTTP {response.status_code})")
            self.robots = RobotFileParser()
            self.robots.parse(response.text.splitlines() if response.status_code == 200 else [])
            crawl_delay = self.robots.crawl_delay(self.settings.user_agent) or self.robots.crawl_delay("*")
            if crawl_delay:
                self.settings = self.settings.model_copy(update={"request_delay_seconds": max(self.settings.request_delay_seconds, crawl_delay)})
        for _ in range(4):
            if not self.robots.can_fetch(self.settings.user_agent, url):
                raise SourceError("Source disallows this path in robots.txt")
            result = self._request(url)
            if result.is_redirect:
                url = self.safe_url(urljoin(url, result.headers.get("Location", "")))
                continue
            if result.status_code >= 400:
                raise SourceError(f"Source returned HTTP {result.status_code}")
            return result
        raise SourceError("Too many source redirects")

    def json(self, path: str):
        try:
            return self.get(path).json()
        except ValueError:
            raise SourceError("Source returned invalid JSON") from None


class ShopAdapter:
    def __init__(self, client: ShopClient, config: dict):
        self.client = client
        self.config = config

    def discover(self) -> ScanResult:
        raise NotImplementedError

    def fetch_url(self, url: str) -> list[SourceOffer]:
        raise NotImplementedError
