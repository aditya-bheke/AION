"""Coupon codes."""

COUPONS = {
    "WELCOME10": 10,
    "FESTIVE20": 20,
}


def get_coupon(code):
    """Return the coupon for `code`. Unknown codes give no discount."""
    percent = COUPONS.get(code.upper(), 0)
    return {"code": code.upper(), "percent": percent}
