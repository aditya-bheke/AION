"""Coupon codes and seasonal campaigns."""
from datetime import date

# code -> (percent off, maximum discount in rupees, valid until)
COUPONS = {
    "WELCOME10": (10, 500, date(2099, 12, 31)),
    "FESTIVE20": (20, 2000, date(2099, 12, 31)),
    "SUMMER23": (15, 1500, date(2023, 8, 31)),
    "DIWALI25": (25, 3000, date(2099, 11, 30)),
}


def get_coupon(code, today=None):
    """Return the active coupon for `code`, or None if it is unknown or expired."""
    today = today or date.today()
    entry = COUPONS.get(code.upper())
    if entry is None:
        return None
    percent, max_discount, valid_until = entry
    if today > valid_until:
        return None
    return {"code": code.upper(), "percent": percent, "max_discount": max_discount}
