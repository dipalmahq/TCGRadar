from urllib.parse import parse_qs, urlencode, urlsplit
from copy import deepcopy
import hashlib

from app.adapters.base import ScanResult, ShopAdapter, SourceError, SourceOffer


class WooCommerceAdapter(ShopAdapter):
    prefix = "/wp-json/wc/store/v1/products"

    def catalog_filters(self):
        # Separate taxonomy queries form a union: category AND tag would lose
        # older products whose merchant supplied only one of these taxonomies.
        filters = []
        for field, parameter in (("category_ids", "category"), ("tag_ids", "tag")):
            if field not in self.config:
                continue
            values = self.config[field]
            if not isinstance(values, list) or not values or any(type(v) is not int or v <= 0 for v in values):
                raise SourceError(f"Invalid WooCommerce {field}; expected positive taxonomy IDs")
            filters.append({parameter: ",".join(str(v) for v in dict.fromkeys(values)), parameter + "_operator": "in"})
        return filters or [{}]

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
        labels.extend(str(t.get("name", "")) for t in parent.get("tags", []) + product.get("tags", []))
        extensions = product.get("extensions", {}).get("woocommerce-germanized", {})
        delivery = str(extensions.get("delivery_time_html", ""))
        from app.adapters.availability import preorder_evidence
        preorder = preorder_evidence(title + " " + delivery, str(product.get("description") or parent.get("description", "")))
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
        for variation in product.get("variations", []):
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
        if self.config.get("full_catalog"):
            return self.discover_batch()
        size = max(1, min(int(self.config.get("page_size", 10)), 100))
        pages = max(1, min(int(self.config.get("max_pages", 1)), 10))
        result = ScanResult()
        seen = set()
        for query, filters in [(q, f) for q in self.config.get("searches", [""])[:6] for f in self.catalog_filters()]:
            for page in range(1, pages + 1):
                params = urlencode({**filters, "per_page": size, "page": page, "search": query, "orderby": "date", "order": "desc"})
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

    def discover_batch(self, cursor=None):
        if not self.config.get("full_catalog"):
            return self.discover()
        state = deepcopy(cursor or {"page": 1})
        result = ScanResult()
        size = max(1, min(int(self.config.get("page_size", 50)), 100))
        try:
            filters = self.catalog_filters()
            filter_index = state.get("filter_index", 0)
            if type(filter_index) is not int or not 0 <= filter_index < len(filters):
                raise SourceError("Invalid WooCommerce taxonomy cursor")
            multiple_filters = len(filters) > 1
            seen = set(state.get("seen_ids", []))
            order = self.config.get('catalog_order', 'asc')
            if order not in ('asc', 'desc'):
                raise SourceError('Invalid WooCommerce catalog order')
            if "pending" not in state:
                params = urlencode({**filters[filter_index], "per_page": size, "page": state["page"], "orderby": "id", "order": order})
                response = self.client.get(f"{self.prefix}?{params}")
                try:
                    items = response.json()
                except ValueError:
                    raise SourceError("Source returned invalid JSON") from None
                if not isinstance(items, list):
                    raise SourceError("Unexpected WooCommerce catalog schema")
                signature = hashlib.sha256(str([p.get("id") for p in items]).encode()).hexdigest()
                if items and signature == state.get("signature"):
                    raise SourceError("Catalog pagination repeated the previous page; full scan not completed")
                total = response.headers.get("X-WP-TotalPages", "")
                state.update(pending=[{"product": p, "variant": 0} for p in items], signature=signature,
                             last_page=state["page"] >= int(total) if total.isdigit() else len(items) < size)
                result.pages_scanned = 1
            while state["pending"]:
                entry = state["pending"][0]
                product = entry["product"]
                if not entry.get("counted"):
                    product_id = str(product["id"])
                    if multiple_filters and product_id in seen:
                        state["pending"].pop(0)
                        continue
                    if multiple_filters:
                        seen.add(product_id)
                        state.setdefault("seen_ids", []).append(product_id)
                    result.scanned_count += 1
                    entry["counted"] = True
                if product.get("type") != "variable":
                    offer = self.parse_product(product)
                    if offer:
                        result.offers.append(offer)
                    state["pending"].pop(0)
                    continue
                variations = product.get("variations", [])
                while entry["variant"] < len(variations):
                    if self.client.requests >= 24:
                        result.complete, result.next_cursor = False, state
                        return result
                    variation = variations[entry["variant"]]
                    try:
                        detail = self.client.json(f"{self.prefix}/{int(variation['id'])}")
                        detail = {**detail, "attributes": variation.get("attributes", []) + detail.get("attributes", [])}
                        offer = self.parse_product(detail, parent=product)
                        if offer:
                            result.offers.append(offer)
                    except SourceError as error:
                        if "HTTP 404" not in str(error):
                            raise
                        result.warnings.append(f"Variant {variation['id']} no longer published; parent price skipped")
                        result.coverage_limited = True
                    result.scanned_count += 1
                    entry["variant"] += 1
                state["pending"].pop(0)
            result.complete = state["last_page"]
            if result.complete and filter_index + 1 < len(filters):
                result.complete = False
                result.next_cursor = {"page": 1, "filter_index": filter_index + 1, "seen_ids": state.get("seen_ids", [])}
            elif not result.complete:
                result.next_cursor = {"page": state["page"] + 1, "signature": state["signature"]}
                if multiple_filters:
                    result.next_cursor.update(filter_index=filter_index, seen_ids=state.get("seen_ids", []))
            return result
        except SourceError as error:
            return self.batch_error(result, state, error)

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
