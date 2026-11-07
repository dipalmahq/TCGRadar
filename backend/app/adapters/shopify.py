from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, quote, urlsplit

from app.adapters.base import ScanResult, ShopAdapter, SourceError, SourceOffer


def decimal_minor(value) -> int | None:
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            return None
        return int((number * 100).quantize(Decimal("1")))
    except (InvalidOperation, TypeError, ValueError):
        return None


class ShopifyAdapter(ShopAdapter):
    def parse_product(self, product: dict, minor_units=False) -> list[SourceOffer]:
        title = str(product.get("title", "")).strip()
        handle = str(product.get("handle", ""))
        if not title or not handle:
            return []
        tags = product.get("tags", [])
        labels = " ".join(tags) if isinstance(tags, list) else str(tags)
        labels += " " + str(product.get("product_type", ""))
        preorder = any(token in (title + " " + labels).lower() for token in ("vorbestell", "preorder", "pre-order", "pre order"))
        offers = []
        for variant in product.get("variants", []):
            label = str(variant.get("title", ""))
            label = "" if label == "Default Title" else label
            available = variant.get("available")
            status = ("preorder" if preorder else "in_stock") if available is True else "out_of_stock" if available is False else "unknown"
            offers.append(SourceOffer(
                external_id=str(variant["id"]),
                title=f"{title} · {label}" if label else title,
                url=f"{self.client.base_url}/products/{quote(handle, safe='-')}?variant={variant['id']}",
                price_minor=int(variant["price"]) if minor_units and str(variant.get("price", "")).isdigit() else decimal_minor(variant.get("price")) if not minor_units else None,
                currency=self.config.get("currency", "EUR"),
                availability=status,
                description=str(product.get("body_html") or product.get("description", "")),
                labels=labels,
                variant_label=label,
                gtin=variant.get("barcode"),
                product_type_hint=str(product.get("product_type", "")),
            ))
        return offers

    def discover(self) -> ScanResult:
        size = max(1, min(int(self.config.get("page_size", 50)), 250))
        pages = max(1, min(int(self.config.get("max_pages", 3)), 10))
        collections = self.config.get("collections", [None])
        result = ScanResult()
        seen = set()
        for collection in collections[:6]:
            prefix = f"/collections/{quote(collection, safe='-')}" if collection else ""
            for page in range(1, pages + 1):
                data = self.client.json(f"{prefix}/products.json?limit={size}&page={page}")
                if not isinstance(data, dict) or not isinstance(data.get("products"), list):
                    raise SourceError("Unexpected Shopify catalog schema")
                products = data["products"]
                for product in products:
                    result.scanned_count += 1
                    for offer in self.parse_product(product):
                        if offer.external_id not in seen:
                            seen.add(offer.external_id)
                            result.offers.append(offer)
                if len(products) < size:
                    break
                if page == pages:
                    result.coverage_limited = True
        return result

    def fetch_url(self, url: str) -> list[SourceOffer]:
        parsed = urlsplit(self.client.safe_url(url))
        parts = parsed.path.rstrip("/").split("/")
        if len(parts) < 3 or parts[-2] != "products":
            raise SourceError("Expected a Shopify /products/<handle> URL")
        data = self.client.json(parsed.path.rstrip("/") + ".js")
        if not isinstance(data, dict) or not isinstance(data.get("variants"), list):
            raise SourceError("Unexpected Shopify product schema")
        offers = self.parse_product(data, minor_units=True)
        selected = parse_qs(parsed.query).get("variant", [None])[0]
        return [o for o in offers if selected is None or o.external_id == selected]
