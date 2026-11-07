"""Bounded public catalog/detail reads using schema.org and explicit shop markup."""
import hashlib
import json
import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from app.adapters.base import ScanResult, ShopAdapter, SourceError, SourceOffer
from app.adapters.shopify import decimal_minor


def value(node):
    return str(node.get("content") or node.get("href") or node.get_text(" ", strip=True)) if node else ""


def status(value):
    code = str(value).rsplit("/", 1)[-1].lower()
    return {"instock": "in_stock", "outofstock": "out_of_stock", "soldout": "out_of_stock",
            "discontinued": "out_of_stock", "preorder": "preorder", "presale": "preorder",
            "backorder": "preorder"}.get(code, "unknown")


def text_status(text):
    text = " ".join(text.lower().split())
    if any(t in text for t in ("ausverkauft", "nicht verfügbar", "nicht lieferbar", "nicht auf lager", "not in stock")):
        return "out_of_stock"
    if any(t in text for t in ("vorbestell", "preorder", "pre-order", "vorverkauf")):
        return "preorder"
    if any(t in text for t in ("auf lager", "sofort verfügbar", "sofort lieferbar", "online verfügbar")):
        return "in_stock"
    return "unknown"


def products(data):
    if isinstance(data, list):
        for item in data:
            yield from products(item)
    elif isinstance(data, dict):
        types = data.get("@type", [])
        types = [types] if isinstance(types, str) else types
        if "Product" in types:
            yield data
        else:
            for item in data.values():
                if isinstance(item, (dict, list)):
                    yield from products(item)


class StructuredHtmlAdapter(ShopAdapter):
    def __init__(self, client, config):
        super().__init__(client, config)
        self.client.client.headers["Accept"] = "text/html,application/xhtml+xml;q=0.9"

    def identity(self, url):
        # URLs, unlike optional SKUs, exist in both listing and detail markup.
        path = urlsplit(self.client.safe_url(url)).path.rstrip("/")
        return hashlib.sha256(path.encode()).hexdigest()

    def offer(self, title, url, price, currency, availability, description="", labels="", gtin=None):
        url = self.client.safe_url(url).split("#")[0]
        if not title or urlsplit(url).path in ("", "/"):
            return None
        variant = parse_qs(urlsplit(url).query).get("variant", [""])[0]
        external_id = variant if self.config.get("markup") == "shopify" and variant.isdigit() else self.identity(url)
        return SourceOffer(external_id, title.strip(), url, decimal_minor(price),
                           currency or "EUR", availability, description=description,
                           labels=labels, gtin=gtin)

    def json_products(self, soup):
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                yield from products(json.loads(script.get_text()))
            except (ValueError, TypeError):
                continue

    def parse(self, html, page_url, detail=False):
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and any(t in soup.title.get_text().lower() for t in ("pardon our interruption", "just a moment", "access denied")):
            raise SourceError("Shop returned an access challenge instead of product data")
        offers = {}
        for product in self.json_products(soup):
            raw = product.get("offers", [])
            raw = [raw] if isinstance(raw, dict) else raw
            if not isinstance(raw, list):
                continue
            # Never assign an AggregateOffer/minimum price to a concrete pack.
            concrete = [o for o in raw if isinstance(o, dict) and o.get("@type") == "Offer"]
            if len(concrete) != 1:
                continue
            data = concrete[0]
            url = data.get("url") or product.get("url") or (page_url if detail else "")
            if not isinstance(url, str) or not url:
                continue
            brand = product.get("brand", "")
            brand = brand.get("name", "") if isinstance(brand, dict) else str(brand)
            offer = self.offer(str(product.get("name", "")), url, data.get("price"),
                               data.get("priceCurrency"), status(data.get("availability")),
                               str(product.get("description", "")), brand,
                               product.get("gtin13") or product.get("gtin12") or product.get("gtin14") or product.get("gtin"))
            if offer:
                offers[offer.external_id] = offer
        for node in soup.select('[itemtype$="/Product"]'):
            # Properties in related/recommended products must not leak into the main product.
            def prop(name):
                matches = [n for n in node.select(f'[itemprop="{name}"]')
                           if n.find_parent(attrs={"itemtype": re.compile(r"/Product$")}) is node
                           and not any(p.get("itemtype", "").endswith(("/Brand", "/Organization", "/Question"))
                                       for p in n.parents if p is not node)]
                # Some listings put a manufacturer name before the actual heading.
                if name == "name":
                    headings = [n for n in matches if n.name in ("h1", "h2", "h3") or n.select_one("a[href]")]
                    return next(iter(headings or matches), None)
                return next(iter(matches), None)
            title = value(prop("name"))
            url = value(prop("url")) or (page_url if detail else "")
            container = prop("offers")
            if not url or not container or "AggregateOffer" in container.get("itemtype", ""):
                continue
            # JTL tier/variant minimum prices are not necessarily a single product's price.
            minimum = container.select_one('[itemprop="minPrice"], [itemprop="lowPrice"]')
            maximum = container.select_one('[itemprop="maxPrice"], [itemprop="highPrice"]')
            if minimum and (not maximum or decimal_minor(value(minimum)) != decimal_minor(value(maximum))):
                continue
            availability = status(value(prop("availability")))
            if availability == "unknown":
                indicators = [n for n in node.select('.delivery-status, .stock-information')
                              if n.find_parent(attrs={"itemtype": re.compile(r"/Product$")}) is node]
                availability = text_status(" ".join(n.get_text(" ", strip=True) for n in indicators))
            offer = self.offer(title, url, value(prop("price")), value(prop("priceCurrency")),
                               availability, value(prop("description")), value(prop("brand")),
                               value(prop("gtin13")) or None)
            if offer:
                offers.setdefault(offer.external_id, offer)
        if self.config.get("markup") == "trader":
            if detail and soup.h1 and soup.select_one("#productPrice"):
                price_node = soup.select_one("#productPrice .price")
                match = re.search(r"([\d.]+)\s*,\s*(\d{2})", price_node.get_text(" ", strip=True) if price_node else "")
                price = match[1].replace(".", "") + "." + match[2] if match else None
                stock = soup.select_one(".info-delivery-stock")
                availability = text_status(stock.get_text(" ", strip=True) if stock else "")
                preorder = soup.select_one('.product-details [title*="Vorbestell"]')
                if preorder and availability != "out_of_stock":
                    availability = "preorder"
                if not soup.select_one('#productPrice .price-from:not(:empty), select[name="varselid[]"]'):
                    offer = self.offer(soup.h1.get_text(" ", strip=True), page_url, price, "EUR", availability,
                                       labels="Pokemon" if "/pokemon/" in page_url.lower() else "")
                    if offer:
                        offers[offer.external_id] = offer
            for node in ([] if detail else soup.select(".product-card")):
                link = node.select_one('a.stretched-link[href]')
                title = node.select_one(".card-title")
                if not link or not title:
                    continue
                price_text = node.select_one(".grid-price")
                match = re.search(r"([\d.]+)\s*,\s*(\d{2})", price_text.get_text(" ", strip=True) if price_text else "")
                price = match[1].replace(".", "") + "." + match[2] if match else None
                stock = node.select_one(".stockFlag")
                availability = text_status(stock.get_text(" ", strip=True) if stock else "")
                # A preorder badge overrides an otherwise buyable stock flag.
                if node.select_one('[title*="Vorbestell"], [title*="Preorder"]'):
                    availability = "preorder" if availability != "out_of_stock" else availability
                offer = self.offer(title.get_text(" ", strip=True), link["href"], price, "EUR", availability,
                                   labels="Pokemon" if "/pokemon/" in link["href"].lower() else "")
                if offer:
                    offers[offer.external_id] = offer
        if detail:
            # A product page's recommendations are not the requested product.
            wanted = self.identity(page_url)
            variant = parse_qs(urlsplit(page_url).query).get("variant", [None])[0] if self.config.get("markup") == "shopify" else None
            return [o for o in offers.values() if self.identity(o.url) == wanted
                    and (variant is None or o.external_id == variant)]
        return list(offers.values())

    def candidate_links(self, html, page_url):
        soup = BeautifulSoup(html, "html.parser")
        links = {o.url: o for o in self.parse(html, page_url)}
        for node in soup.select('[itemtype$="/Product"]'):
            name = node.select_one('h1[itemprop="name"], h2[itemprop="name"], h3[itemprop="name"], .productbox-title') or node.select_one('[itemprop="name"]')
            link = node.select_one('[itemprop="url"]')
            if name and link and value(link):
                url = self.client.safe_url(value(link))
                links.setdefault(url, self.offer(value(name), url, None, "EUR", "unknown"))
        if self.config.get("markup") == "shopify":
            for link in soup.select('a[href*="/products/"]'):
                safe = self.client.safe_url(link["href"])
                match = re.search(r"/products/([^/]+)$", urlsplit(safe).path.rstrip("/"))
                if not match:
                    continue
                url = self.client.safe_url("/products/" + match[1])
                image = link.select_one("img[alt]")
                name = link.get_text(" ", strip=True) or (image.get("alt", "") if image else "")
                if name:
                    links.setdefault(url, self.offer(name, url, None, "EUR", "unknown"))
        return [o for o in links.values() if o]

    def discover(self):
        from app.domain import classify

        result = ScanResult(coverage_limited=True)
        seen = set()
        limit = max(1, min(int(self.config.get("products_per_category", 6)), 10))
        categories = self.config.get("categories", [])[:6]
        if not categories:
            raise SourceError("No public catalog categories configured")
        for category in categories:
            response = self.client.get(category["path"])
            candidates = self.candidate_links(response.text, str(response.url))
            if not candidates:
                raise SourceError("Catalog page contains no recognizable products")
            checked = 0
            for candidate in candidates:
                candidate.labels += " " + category.get("game", "")
                if candidate.external_id in seen or not classify(candidate, "probe"):
                    continue
                seen.add(candidate.external_id)
                result.scanned_count += 1
                try:
                    fresh = self.fetch_url(candidate.url)
                    for offer in fresh:
                        offer.labels += " " + category.get("game", "")
                    result.offers.extend(fresh)
                except SourceError as error:
                    if "rate limit" in str(error) or "disallows" in str(error) or "access challenge" in str(error):
                        raise
                    result.warnings.append("Product detail skipped: " + str(error))
                checked += 1
                if checked >= limit:
                    break
        if not result.offers:
            raise SourceError("No concrete product details resolved in catalog window")
        return result

    def fetch_url(self, url):
        response = self.client.get(url)
        offers = self.parse(response.text, str(response.url), detail=True)
        if not offers:
            raise SourceError("No unambiguous product offer on detail page")
        return offers
