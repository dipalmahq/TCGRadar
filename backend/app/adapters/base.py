from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import time
import re
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import Settings


def retry_after_seconds(value, now=None):
    """RFC Retry-After supports both a delay and an absolute HTTP date."""
    value = value.strip()
    try:
        if value.isdigit():
            return int(value)
        deadline = parsedate_to_datetime(value)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return max(0, math.ceil((deadline - (now or datetime.now(timezone.utc))).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return 30


class SourceError(Exception):
    """A safe-to-display source error; never includes credentials or response bodies."""

    def __init__(self, message, retry_after_seconds=None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AvailabilityError(SourceError):
    """Retain price/product evidence while making unverified shipping stock unknown."""

    def __init__(self, message, offers, retry_after_seconds=None):
        super().__init__(message, retry_after_seconds)
        self.offers = offers


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
    availability_error: str | None = None


@dataclass
class ScanResult:
    offers: list[SourceOffer] = field(default_factory=list)
    scanned_count: int = 0
    warnings: list[str] = field(default_factory=list)
    # Absence from a bounded catalog is not proof of being sold out.
    coverage_limited: bool = False
    complete: bool = True
    next_cursor: dict | None = None
    pages_scanned: int = 0
    source_error: str | None = None
    retry_after_seconds: int | None = None


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

    def defer_until(self, deadline):
        if deadline is not None:
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                self.last_request = time.monotonic() + remaining - self.settings.request_delay_seconds

    def safe_url(self, path: str) -> str:
        url = urljoin(self.base_url + "/", path)
        parsed = urlsplit(url)
        if (parsed.scheme, parsed.hostname, parsed.port) != (self.origin.scheme, self.origin.hostname, self.origin.port) or parsed.username or parsed.password:
            raise SourceError("Request outside configured shop origin blocked")
        return url

    def _request(self, url: str, method="GET", json_body=None, form_body=None) -> httpx.Response:
        for attempt in range(3):
            self.requests += 1
            if self.requests > 80:
                raise SourceError("Per-scan request budget exceeded")
            delay = self.settings.request_delay_seconds - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
            try:
                kwargs = {"json": json_body, "headers": {"Accept": "application/json"}} if json_body is not None else {}
                if form_body is not None:
                    kwargs = {"data": form_body, "headers": {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}}
                with self.client.stream(method, url, **kwargs) as response:
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
            if result.status_code == 429 or (result.status_code == 503 and "Retry-After" in result.headers):
                # Honor long Retry-After by ending this scan; the worker backs off.
                value = result.headers.get("Retry-After", "5")
                wait = retry_after_seconds(value)
                if wait > 10 or attempt == 2:
                    label = "Source rate limit" if result.status_code == 429 else "Source temporarily unavailable"
                    raise SourceError(f"{label} (HTTP {result.status_code}; Retry-After {value[:30]})", retry_after_seconds=wait)
                time.sleep(max(1, wait))
                continue
            if result.status_code >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return result
        raise SourceError("Source request failed")

    def _check_robots(self, url):
        if self.robots is None:
            response = self._request(self.safe_url("/robots.txt"))
            if response.status_code not in (200, 404):
                raise SourceError(f"Unable to verify robots.txt (HTTP {response.status_code})")
            self.robots = RobotFileParser()
            self.robots.parse(response.text.splitlines() if response.status_code == 200 else [])
            crawl_delay = self.robots.crawl_delay(self.settings.user_agent) or self.robots.crawl_delay("*")
            if crawl_delay:
                self.settings = self.settings.model_copy(update={"request_delay_seconds": max(self.settings.request_delay_seconds, crawl_delay)})
        if not self.robots.can_fetch(self.settings.user_agent, url):
            raise SourceError("Source disallows this path in robots.txt")

    def get(self, path: str) -> httpx.Response:
        url = self.safe_url(path)
        for _ in range(4):
            self._check_robots(url)
            result = self._request(url)
            if result.is_redirect:
                url = self.safe_url(urljoin(url, result.headers.get("Location", "")))
                continue
            if result.status_code >= 400:
                raise SourceError(f"Source returned HTTP {result.status_code}")
            return result
        raise SourceError("Too many source redirects")

    def trader_catalog(self, fields):
        """Submit only the shop's read-only category filter, never a cart action."""
        allowed = {"cl", "fnc", "cnid", "lang", "ajax", "attrfilter[page]",
                   "attrfilter[itemsperpage]", "attrfilter[es_sort]"}
        if (set(fields) - allowed or fields.get("cl") != "alist" or fields.get("fnc") != "executefilter"
                or fields.get("ajax") != "1" or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", fields.get("cnid", ""))
                or not str(fields.get("attrfilter[page]", "")).isdigit()):
            raise SourceError("Invalid read-only Trader catalog request")
        url = self.safe_url("/index.php")
        self._check_robots(url)
        response = self._request(url, method="POST", form_body=fields)
        if response.status_code != 200:
            raise SourceError(f"Trader catalog returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise SourceError("Trader catalog returned invalid JSON") from None
        if not isinstance(data, dict) or not data or not all(isinstance(v, str) for v in data.values()):
            raise SourceError("Unexpected Trader catalog fragments")
        return "\n".join(data.values())

    def json(self, path: str):
        try:
            return self.get(path).json()
        except ValueError:
            raise SourceError("Source returned invalid JSON") from None

    def storefront_availability(self, endpoint, variant_ids):
        """The fixed, tokenless, read-only query used by the configured storefront."""
        try:
            parsed = urlsplit(endpoint)
            port = parsed.port
        except ValueError:
            raise SourceError("Invalid configured Shopify Storefront endpoint") from None
        if (parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", parsed.hostname or "")
                or not re.fullmatch(r"/api/20\d{2}-(?:01|04|07|10)/graphql\.json", parsed.path)
                or parsed.query or parsed.fragment):
            raise SourceError("Invalid configured Shopify Storefront endpoint")
        ids = list(dict.fromkeys(str(id) for id in variant_ids))
        if not ids or len(ids) > 50 or not all(re.fullmatch(r"\d{1,30}", id) for id in ids):
            raise SourceError("Invalid Storefront variant batch")
        gids = ["gid://shopify/ProductVariant/" + id for id in ids]
        query = "query ShippingAvailability($ids: [ID!]!) { nodes(ids: $ids) { ... on ProductVariant { id availableForSale currentlyNotInStock } } }"
        response = self._request(endpoint, method="POST", json_body={"query": query, "variables": {"ids": gids}})
        if response.status_code != 200:
            raise SourceError(f"Storefront availability returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise SourceError("Storefront availability returned invalid JSON") from None
        payload = data.get("data") if isinstance(data, dict) else None
        nodes = payload.get("nodes") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or data.get("errors") or not isinstance(nodes, list) or len(nodes) != len(ids):
            raise SourceError("Storefront availability response is incomplete")
        states = {}
        for id, gid, node in zip(ids, gids, nodes):
            if node is None:
                states[id] = "out_of_stock"
            elif (not isinstance(node, dict) or node.get("id") != gid
                  or type(node.get("availableForSale")) is not bool
                  or type(node.get("currentlyNotInStock")) is not bool):
                raise SourceError("Storefront availability variant schema mismatch")
            else:
                states[id] = ("preorder" if node["currentlyNotInStock"] else "in_stock") if node["availableForSale"] else "out_of_stock"
        return states


class ShopAdapter:
    def __init__(self, client: ShopClient, config: dict):
        self.client = client
        self.config = config

    def discover(self) -> ScanResult:
        raise NotImplementedError

    def fetch_url(self, url: str) -> list[SourceOffer]:
        raise NotImplementedError

    def discover_batch(self, cursor=None) -> ScanResult:
        return self.discover()

    def batch_error(self, result, cursor, error):
        result.complete = False
        result.next_cursor = cursor
        result.source_error = str(error)
        result.retry_after_seconds = error.retry_after_seconds
        return result
