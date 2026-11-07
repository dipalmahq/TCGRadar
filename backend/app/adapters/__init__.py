from app.adapters.shopify import ShopifyAdapter
from app.adapters.woocommerce import WooCommerceAdapter

ADAPTERS = {"shopify": ShopifyAdapter, "woocommerce": WooCommerceAdapter}
