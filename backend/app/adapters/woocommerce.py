from urllib.parse import parse_qs, urlencode, urlsplit

from app.adapters.base import ScanResult, ShopAdapter, SourceError, SourceOffer


class WooCommerceAdapter(ShopAdapter):
    prefix = "/wp-json/wc/store/v1/products"

    def parse_product(self, product: dict, parent: dict | None = None) -> SourceOffer | None:
        parent = parent or {}
        prices = product.get("prices", {})
        # A parent's minimum variant price must never be presented as a display price.
        if product.get("type") == "variable":
            return None
        value = prices.get("price")
        digits = prices.get("currency_minor_unit", 2)
        price = int(value) * 100 // (10 ** int(digits)) if str(value).isdigit() and digits in (0, 1, 2) else None
        attributes = product.get("attributes", [])
        language = ""
        labels = []
        variant_labels = []
        for attribute in parent.get("attributes", []) + attributes:
            name = str(attribute.get("name", "")).lower()
            values = [str(t.get("name", "")) for t in attribute.get("terms", [])]
            if attribute.get("value"):
                values.append(str(attribute["value"]))
            if name in ("sprache", "language") and len(set(values)) == 1:
                language = values[0]
            if name in ("auswahl", "produkt", "produkttyp", "type") and attribute.get("value"):
                variant_labels.extend(values)
            labels.extend(values)
        title = str(parent.get("name") or product.get("name", ""))
        variation = " ".join(variant_labels) or str(product.get("variation", ""))
        if variation:
            title += " · " + variation
        categories = parent.get("categories", []) + product.get("categories", [])
        labels.extend(str(c.get("name", "")) for c in categories)
        extensions = product.get("extensions", {}).get("woocommerce-germanized", {})
        delivery = str(extensions.get("delivery_time_html", ""))
        preorder = any(token in (title + " " + delivery).lower() for token in ("vorbestell", "preorder", "pre-order"))
        in_stock = product.get("is_in_stock")
        buyable = product.get("is_purchasable")
        status = "unknown"
        if in_stock is False:
            status = "out_of_stock"
        elif in_stock is True and buyable is True:
            status = "preorder" if preorder or product.get("is_on_backorder") else "in_stock"
        url = product.get("permalink") or parent.get("permalink", "")
        if not url:
            return None
        self.client.safe_url(url)
        return SourceOffer(
            external_id=str(product["id"]),
            title=title,
            url=url,
            price_minor=price,
            currency=prices.get("currency_code", "EUR"),
            availability=status,
            description=str(product.get("description") or product.get("short_description") or parent.get("description") or parent.get("short_description", "")),
            labels=" ".join(labels),
            variant_label=variation,
            language_hint=language,
            gtin=product.get("global_unique_id") or None,
        )

    def expand_product(self, product: dict, result: ScanResult) -> list[SourceOffer]:
        if product.get("type") != "variable":
            offer = self.parse_product(product)
            return [offer] if offer else []
        result.scanned_count += len(product.get("variations", []))
        items = []
        for variation in product.get("variations", [])[:12]:
            try:
                detail = self.client.json(f"{self.prefix}/{int(variation['id'])}")
                detail = {**detail, "attributes": variation.get("attributes", []) + detail.get("attributes", [])}
                offer = self.parse_product(detail, parent=product)
                if offer:
                    items.append(offer)
            except SourceError:
                result.warnings.append(f"Variant {variation['id']} could not be resolved; ambiguous parent price skipped")
        return items

    def discover(self) -> ScanResult:
        size = max(1, min(int(self.config.get("page_size", 10)), 100))
        pages = max(1, min(int(self.config.get("max_pages", 1)), 10))
        result = ScanResult()
        seen = set()
        for query in self.config.get("searches", [""])[:6]:
            for page in range(1, pages + 1):
                params = urlencode({"per_page": size, "page": page, "search": query, "orderby": "date", "order": "desc"})
                data = self.client.json(f"{self.prefix}?{params}")
                if not isinstance(data, list):
                    raise SourceError("Unexpected WooCommerce catalog schema")
                for product in data:
                    if product.get("id") in seen:
                        continue
                    seen.add(product.get("id"))
                    result.scanned_count += 1
                    result.offers.extend(self.expand_product(product, result))
                if len(data) < size:
                    break
                if page == pages:
                    result.coverage_limited = True
        return result

    def fetch_url(self, url: str) -> list[SourceOffer]:
        parsed = urlsplit(self.client.safe_url(url))
        slug = parsed.path.rstrip("/").split("/")[-1]
        data = self.client.json(f"{self.prefix}?{urlencode({'slug': slug, 'per_page': 1})}")
        if not isinstance(data, list) or not data:
            raise SourceError("Product not found in WooCommerce Store API")
        result = ScanResult()
        offers = self.expand_product(data[0], result)
        if result.warnings and not offers:
            raise SourceError(result.warnings[0])
        selected = parse_qs(parsed.query).get("variation_id", [None])[0]
        wanted = {key: value for key, value in parse_qs(parsed.query).items() if key.startswith("attribute_")}
        return [o for o in offers if (selected is None or o.external_id == selected) and all(parse_qs(urlsplit(o.url).query).get(key) == value for key, value in wanted.items())]
