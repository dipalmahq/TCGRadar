from app.adapters.shopify import ShopifyAdapter
from app.adapters.woocommerce import WooCommerceAdapter
from app.adapters.structured_html import StructuredHtmlAdapter

ADAPTERS = {"shopify": ShopifyAdapter, "woocommerce": WooCommerceAdapter, "structured_html": StructuredHtmlAdapter}
