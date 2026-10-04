"""Order pricing: subtotal and GST."""
from app import catalog

GST_RATE = 0.18


def order_subtotal(order):
    total = 0.0
    for item in order["items"]:
        product = catalog.get_product(item["sku"])
        total += product["price"] * item["qty"]
    return round(total, 2)


def compute_total(order):
    subtotal = order_subtotal(order)
    tax = round(subtotal * GST_RATE, 2)
    return {
        "order_id": order["id"],
        "subtotal": subtotal,
        "discount": 0.0,
        "tax": tax,
        "total": round(subtotal + tax, 2),
    }
