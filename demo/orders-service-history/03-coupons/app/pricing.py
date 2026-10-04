"""Order pricing: subtotal, coupon discount and GST."""
from app import catalog, coupons

GST_RATE = 0.18


def order_subtotal(order):
    total = 0.0
    for item in order["items"]:
        product = catalog.get_product(item["sku"])
        total += product["price"] * item["qty"]
    return round(total, 2)


def apply_discount(subtotal, coupon):
    return round(subtotal * coupon["percent"] / 100, 2)


def compute_total(order, coupon_code=None):
    subtotal = order_subtotal(order)
    discount = 0.0
    if coupon_code:
        coupon = coupons.get_coupon(coupon_code)
        discount = apply_discount(subtotal, coupon)
    taxable = subtotal - discount
    tax = round(taxable * GST_RATE, 2)
    return {
        "order_id": order["id"],
        "coupon": coupon_code.upper() if coupon_code else None,
        "subtotal": subtotal,
        "discount": discount,
        "tax": tax,
        "total": round(taxable + tax, 2),
    }
