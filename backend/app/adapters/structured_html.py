"""Bounded public catalog/detail reads using schema.org and explicit shop markup."""
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict
from html import unescape
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.adapters.base import AvailabilityError, ScanResult, ShopAdapter, SourceError, SourceOffer
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


def breadcrumb_context(soup):
    """Only the current page's category path can supply missing TCG evidence."""
    from app.domain import identify_game
    names = []
    for node in soup.select('.breadcrumb, [itemtype$="/BreadcrumbList"], nav[aria-label="breadcrumb" i]'):
        names.extend(n.get_text(' ', strip=True) for n in (node.select('a, [itemprop="name"]') or [node]))
    def collect(data):
        if isinstance(data, list):
            for item in data: collect(item)
        elif isinstance(data, dict):
            types = data.get('@type', [])
            if types == 'BreadcrumbList' or isinstance(types, list) and 'BreadcrumbList' in types:
                for item in data.get('itemListElement', []):
                    if isinstance(item, dict):
                        nested = item.get('item')
                        names.append(str(item.get('name') or (nested.get('name') if isinstance(nested, dict) else '') or ''))
            else:
                for item in data.values():
                    if isinstance(item, (list, dict)): collect(item)
    for script in soup.select('script[type="application/ld+json"]'):
        try: collect(json.loads(script.get_text()))
        except (ValueError, TypeError): pass
    games = {identify_game(name) for name in names}
    games.add(identify_game(' '.join(names)))
    games.discard(None)
    return next(iter(games)) if len(games) == 1 else ''


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
        requested_variant = parse_qs(urlsplit(page_url).query).get("variant", [None])[0] if detail and self.config.get("markup") == "shopify" else None
        for product in self.json_products(soup):
            raw = product.get("offers", [])
            raw = [raw] if isinstance(raw, dict) else raw
            if not isinstance(raw, list):
                continue
            # Never assign an AggregateOffer/minimum price to a concrete pack.
            concrete = [o for o in raw if isinstance(o, dict) and o.get("@type") == "Offer"]
            multiple = len(concrete) > 1
            if multiple:
                if self.config.get("markup") != "shopify":
                    continue
                valid = []
                for data in concrete:
                    url = data.get("url", "")
                    variant = parse_qs(urlsplit(url).query).get("variant", [""])[0] if isinstance(url, str) else ""
                    if not variant.isdigit() or self.identity(url) != self.identity(product.get("url") or page_url):
                        continue
                    if requested_variant and variant != requested_variant:
                        continue
                    # A variant URL proves its identity, but mixed pack sizes still need a label.
                    mixed = re.search(r"\b(?:boosters?|displays?|cases?|bundles?)\s*(?:/|&|or|and|oder)\s*(?:boosters?|displays?|cases?|bundles?)\b",
                                      unescape(str(product.get("name", ""))), re.I)
                    if mixed:
                        from app.domain import identify_type
                        if not identify_type(str(data.get("name") or "")):
                            continue
                    valid.append(data)
                ids = [parse_qs(urlsplit(d["url"]).query)["variant"][0] for d in valid]
                if len(ids) != len(set(ids)) or (requested_variant and len(valid) != 1) or (not requested_variant and len(valid) != len(concrete)):
                    continue
                concrete = valid
            if not concrete:
                continue
            for data in concrete:
                url = data.get("url") or product.get("url") or (page_url if detail else "")
                if not isinstance(url, str) or not url:
                    continue
                brand = product.get("brand", "")
                brand = brand.get("name", "") if isinstance(brand, dict) else str(brand)
                title = str(product.get("name", ""))
                label = str(data.get("name") or "") if multiple else ""
                if label and label != title:
                    title += " · " + label
                gtin = data.get("gtin13") or data.get("gtin12") or data.get("gtin")
                if not multiple:
                    gtin = gtin or product.get("gtin13") or product.get("gtin12") or product.get("gtin14") or product.get("gtin")
                offer = self.offer(title, url, data.get("price"), data.get("priceCurrency"),
                                   status(data.get("availability")), str(product.get("description", "")), brand, gtin)
                if offer:
                    offer.variant_label = label
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
            selected = [o for o in offers.values() if self.identity(o.url) == wanted
                        and (variant is None or o.external_id == variant)]
            context = breadcrumb_context(soup)
            if context:
                for offer in selected:
                    offer.labels += ' ' + context
            # Shopware stock-notification widgets can coexist with schema.org/PreOrder.
            # Inspect only this product's buy box, never recommendation cart forms.
            buy = soup.select_one('.product-detail-buy')
            if buy:
                button = buy.select_one('form[data-add-to-cart] button:not([type="button"]):not([type="reset"]):not([disabled]):not([aria-disabled="true"])')
                notification = buy.select_one('[data-stock-notification-form]')
                for offer in selected:
                    if not button:
                        offer.availability = "out_of_stock" if notification else "unknown"
                    elif offer.availability != "out_of_stock" and text_status(button.get_text(" ", strip=True)) == "preorder":
                        offer.availability = "preorder"
            return selected
        return list(offers.values())

    def candidate_links(self, html, page_url):
        soup = BeautifulSoup(html, "html.parser")
        links = {}
        for offer in self.parse(html, page_url):
            if self.config.get("markup") == "shopify":
                # Discovery visits the whole product; exact watches retain their selected variant.
                parts = urlsplit(offer.url)
                offer.url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            links.setdefault(offer.url, offer)
        for node in soup.select('[itemtype$="/Product"]'):
            name = node.select_one('h1[itemprop="name"], h2[itemprop="name"], h3[itemprop="name"], .productbox-title') or node.select_one('[itemprop="name"]')
            link = node.select_one('[itemprop="url"]')
            if name and link and value(link):
                url = self.client.safe_url(value(link))
                links.setdefault(url, self.offer(value(name), url, None, "EUR", "unknown"))
        for node in soup.select('.product-box'):
            link = node.select_one('a.product-name[href]')
            if link:
                url = self.client.safe_url(link['href'])
                links.setdefault(url, self.offer(link.get_text(' ', strip=True), url, None, 'EUR', 'unknown'))
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
        if self.config.get("full_catalog"):
            return self.discover_batch()
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
                    if isinstance(error, AvailabilityError) or "rate limit" in str(error) or "disallows" in str(error) or "access challenge" in str(error):
                        raise
                    result.warnings.append("Product detail skipped: " + str(error))
                checked += 1
                if checked >= limit:
                    break
        if not result.offers:
            raise SourceError("No concrete product details resolved in catalog window")
        return result

    def trader_fields(self, soup):
        form = soup.select_one("#esFilterList")
        if not form:
            raise SourceError("Trader category filter form missing")
        fields = {n["name"]: n.get("value", "") for n in form.select("input[name]")
                  if n["name"] in ("cl", "fnc", "cnid", "lang")}
        fields.update({"ajax": "1", "attrfilter[itemsperpage]": "50", "attrfilter[es_sort]": "es_relevance desc"})
        return fields

    def page_key(self, category):
        url = self.client.safe_url(category["path"])
        return url + "#trader-page=" + str(category["trader_page"]) if "trader_page" in category else url

    def page_links(self, html, page_url, game, category=None):
        soup = BeautifulSoup(html, "html.parser")
        links = []
        if self.config.get("pagination") == "trader_ajax":
            category = category or {"path": page_url}
            active = soup.select_one(".pagination .active [data-page-number]")
            current = int(active["data-page-number"]) if active else category.get("trader_page", 1)
            pages = {int(n["data-page-number"]) for n in soup.select(".pagination [data-page-number]")
                     if n["data-page-number"].isdigit()}
            later = sorted(page for page in pages if page > current)
            if later:
                fields = category.get("trader_form") or self.trader_fields(soup)
                links.append({"path": page_url, "game": game, "pagination": True,
                              "trader_page": later[0], "trader_form": fields})
            return links
        if self.config.get("pagination") == "shopware":
            parts = urlsplit(page_url)
            params = parse_qs(parts.query)
            current = int(params.get('p', ['1'])[0])
            pages = [int(n.get('value', '0')) for n in soup.select('.pagination input[name="p"][value]')
                     if str(n.get('value', '')).isdigit()]
            pages.extend(int(n['data-page']) for n in soup.select('.pagination a[data-page][href]:not([aria-disabled="true"])')
                         if str(n.get('data-page', '')).isdigit())
            later = sorted(p for p in pages if p > current)
            if later:
                params['p'] = [str(later[0])]
                links.append({'path': self.client.safe_url(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params, doseq=True), ''))),
                              'game': game, 'pagination': True})
            return links
        if self.config.get("crawl_subcategories"):
            # JTL editorial categories can sit beside an empty product list.
            content = soup.select_one("#content") or soup.select_one("main") or soup.select_one("#result-wrapper") or soup
            def add_category(link, image=None):
                if not link or not link.get("href") or link.find_parent(["header", "nav", "footer"]):
                    return
                text = (link.get_text(" ", strip=True) + " " + str(image.get("alt", "") if image else "") + " " + link["href"]).lower()
                if any(t in text for t in ("einzelkarten", "single cards", "zubeh", "zubehoer", "merchandise", "plüsch", "pluesch", "kartenlisten", "sammelsticker")):
                    return
                entry = {"path": self.client.safe_url(urljoin(page_url, link["href"])), "game": game}
                if entry not in links:
                    links.append(entry)

            for image in content.select('img[src*="/media/image/category/"]'):
                if image.find_parent(["header", "nav", "footer"]):
                    continue
                link = image.find_parent("a")
                if not link:
                    container = image.find_parent(class_="sub-categories")
                    link = container.select_one("a[href]") if container else None
                add_category(link, image)
            # Language overview cards use storage images rather than category images.
            for link in content.select('.category-slider-wrapper a.stretched-link[href]'):
                add_category(link, link.select_one('img'))
            # OPC set tiles have several layouts and use both product/set buttons.
            # Card lists and contact buttons are not catalog navigation.
            for link in content.select('.opc-Button a[href]'):
                if not re.match(r"^(?:alle\s+produkte|zum\s+set)\b", link.get_text(" ", strip=True), re.I):
                    continue
                add_category(link)
        next_node = soup.select_one('[rel="next"][href]')
        next_url = self.client.safe_url(urljoin(page_url, next_node["href"])) if next_node else None
        if not next_url and self.config.get("pagination") == "page":
            # Müller renders page buttons without links; its ItemList supplies the total.
            for script in soup.select('script[type="application/ld+json"]'):
                try:
                    data = json.loads(script.get_text())
                except ValueError:
                    continue
                if not isinstance(data, dict) or data.get("@type") != "ItemList":
                    continue
                total, items = data.get("numberOfItems"), data.get("itemListElement", [])
                parts = urlsplit(page_url)
                params = parse_qs(parts.query)
                page = int(params.get("page", ["1"])[0])
                page_size = int(self.config.get("html_page_size", 60))
                if isinstance(total, int) and items and page * page_size < total:
                    params["page"] = [str(page + 1)]
                    next_url = self.client.safe_url(urlunsplit((parts.scheme, parts.netloc, parts.path,
                                                               urlencode(params, doseq=True), "")))
                    break
        if next_url:
            if next_url == page_url:
                raise SourceError("Catalog pagination points to the current page")
            links.insert(0, {"path": next_url, "game": game, "pagination": True})
        return links

    def discover_batch(self, cursor=None):
        if not self.config.get("full_catalog"):
            return self.discover()
        from app.domain import classify, identify_type

        state = deepcopy(cursor or {"frontier": self.config.get("categories", []),
                                    "visited": [], "seen_products": []})
        result = ScanResult()
        try:
            if not state.get("pending"):
                if not state["frontier"]:
                    return result
                # Rotate configured games at page boundaries, preserving pending products
                # and old cursors. A large category cannot monopolize discovery.
                games = list(dict.fromkeys(c.get('game', '') for c in self.config.get('categories', [])))
                previous_game = state.get('game')
                if previous_game in games:
                    start = games.index(previous_game) + 1
                    for next_game in games[start:] + games[:start]:
                        index = next((i for i, c in enumerate(state['frontier']) if c.get('game', '') == next_game), None)
                        if index is not None:
                            state['frontier'].insert(0, state['frontier'].pop(index))
                            break
                category = state["frontier"][0]
                game = category.get("game", "")
                if self.config.get("pagination") == "trader_ajax":
                    category = dict(category)
                    if "trader_form" not in category:
                        response = self.client.get(category["path"])
                        category["path"] = str(response.url)
                        category["trader_form"] = self.trader_fields(BeautifulSoup(response.text, "html.parser"))
                    category.setdefault("trader_page", 1)
                    fields = {**category["trader_form"], "attrfilter[page]": str(category["trader_page"] - 1)}
                    html = self.client.trader_catalog(fields)
                    url = self.client.safe_url(category["path"])
                else:
                    response = self.client.get(category["path"])
                    html, url = response.text, str(response.url)
                all_candidates = self.candidate_links(html, url)
                # Keep all packaging candidates, including headings whose game is only in the detail metadata.
                for candidate in all_candidates:
                    candidate.labels += " " + game
                candidates = [c for c in all_candidates if classify(c, "discovery") is not None
                              or identify_type(c.title) or c.product_type_hint]
                signature = hashlib.sha256(str(sorted(self.identity(c.url) for c in all_candidates)).encode()).hexdigest()
                previous_signature = state.get('game_signatures', {}).get(game)
                if previous_signature is None and state.get('game') == game:
                    previous_signature = state.get('last_signature')
                if all_candidates and category.get("pagination") and previous_signature == signature:
                    raise SourceError("Catalog pagination repeated the previous product page; full scan not completed")
                additions = self.page_links(html, url, game, category)
                if any(entry.get("pagination") and self.page_key(entry) in state["visited"] for entry in additions):
                    raise SourceError("Catalog pagination loops to an already visited page")
                if not candidates and not additions:
                    soup = BeautifulSoup(html, "html.parser")
                    # Non-relevant product pages still count; a blank/challenge page must not.
                    if not self.candidate_links(html, url) and not soup.select('.productbox, .product-card, [data-product-id]'):
                        raise SourceError("Catalog contains no recognizable products or category navigation")
                state["frontier"].pop(0)
                state["visited"].append(self.page_key(category))
                if "trader_page" not in category:
                    state["visited"].append(url)
                queued = {self.page_key(entry) for entry in state["frontier"]} | set(state["visited"])
                for entry in reversed(additions):
                    if self.page_key(entry) not in queued:
                        state["frontier"].insert(0, entry)
                        queued.add(self.page_key(entry))
                seen = set(state["seen_products"])
                state["pending"] = list({self.identity(c.url): asdict(c) for c in candidates
                                         if self.identity(c.url) not in seen}.values())
                state.update(game=game, last_signature=signature, last_url=url)
                state['game_signatures'] = {**state.get('game_signatures', {}), game: signature}
                result.pages_scanned = 1
            while state["pending"]:
                if self.client.requests >= 24:
                    result.complete, result.next_cursor = False, state
                    return result
                candidate = SourceOffer(**state["pending"][0])
                try:
                    offers = self.fetch_url(candidate.url)
                    for offer in offers:
                        offer.labels += " " + state.get("game", "")
                    result.offers.extend(offers)
                except SourceError as error:
                    if "No unambiguous" not in str(error) and "HTTP 404" not in str(error):
                        raise
                    result.warnings.append("Product detail skipped: " + str(error))
                    result.coverage_limited = True
                result.scanned_count += 1
                state["seen_products"].append(self.identity(candidate.url))
                state["pending"].pop(0)
            result.complete = not state["frontier"]
            if not result.complete:
                result.next_cursor = state
            return result
        except SourceError as error:
            result.offers.extend(getattr(error, "offers", []))
            return self.batch_error(result, state, error)

    def fetch_url(self, url):
        response = self.client.get(url)
        offers = self.parse(response.text, str(response.url), detail=True)
        if not offers:
            raise SourceError("No unambiguous product offer on detail page")
        endpoint = self.config.get("shipping_availability_endpoint")
        if endpoint:
            try:
                states = {}
                for offset in range(0, len(offers), 50):
                    states.update(self.client.storefront_availability(endpoint, [o.external_id for o in offers[offset:offset + 50]]))
                for offer in offers:
                    offer.availability = states[offer.external_id]
            except SourceError as error:
                note = "Versandverfügbarkeit nicht bestätigt: " + str(error)
                for offer in offers:
                    offer.availability = "unknown"
                    offer.availability_error = note
                raise AvailabilityError(note, offers, error.retry_after_seconds) from None
        return offers
