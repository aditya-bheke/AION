"""In-memory product catalog and orders (stands in for the database)."""
import logging

log = logging.getLogger("orders.catalog")

PRODUCTS = {
    "SKU-1001": {"sku": "SKU-1001", "name": "Mechanical Keyboard", "price": 3499.00},
    "SKU-1002": {"sku": "SKU-1002", "name": "Wireless Mouse", "price": 899.00},
    "SKU-1003": {"sku": "SKU-1003", "name": "27-inch Monitor", "price": 15999.00},
    "SKU-1004": {"sku": "SKU-1004", "name": "USB-C Hub", "price": 1299.00},
    "SKU-1005": {"sku": "SKU-1005", "name": "Laptop Stand", "price": 1499.00},
}

ORDERS = {
    1001: {"id": 1001, "customer": "C-501", "items": [{"sku": "SKU-1001", "qty": 1}, {"sku": "SKU-1002", "qty": 2}]},
    1002: {"id": 1002, "customer": "C-502", "items": [{"sku": "SKU-1003", "qty": 1}]},
    1003: {"id": 1003, "customer": "C-503", "items": [{"sku": "SKU-1004", "qty": 3}, {"sku": "SKU-1005", "qty": 1}]},
    1004: {"id": 1004, "customer": "C-504", "items": [{"sku": "SKU-1002", "qty": 1}]},
    1005: {"id": 1005, "customer": "C-505", "items": [{"sku": "SKU-1001", "qty": 2}, {"sku": "SKU-1003", "qty": 1}]},
    1006: {"id": 1006, "customer": "C-506", "items": [{"sku": "SKU-1005", "qty": 4}]},
    1007: {"id": 1007, "customer": "C-507", "items": [{"sku": "SKU-1004", "qty": 1}, {"sku": "SKU-1002", "qty": 1}]},
    1008: {"id": 1008, "customer": "C-508", "items": [{"sku": "SKU-1003", "qty": 2}]},
    # Draft carts are stored as orders until checkout; they may be empty.
    1010: {"id": 1010, "customer": "C-510", "items": [], "status": "draft"},
}

# Large items are not kept in the hot inventory cache.
_COLD_SKUS = {"SKU-1003", "SKU-1005"}


def list_products():
    return list(PRODUCTS.values())


def get_product(sku):
    if sku in _COLD_SKUS:
        log.warning("Inventory cache miss for %s, loading from catalog store", sku)
    return PRODUCTS.get(sku)


def get_order(order_id):
    return ORDERS.get(order_id)
