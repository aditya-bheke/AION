from app import catalog, pricing


def test_subtotal():
    assert pricing.order_subtotal(catalog.get_order(1001)) == 3499.00 + 2 * 899.00


def test_total_includes_gst():
    result = pricing.compute_total(catalog.get_order(1002))
    assert result["subtotal"] == 15999.00
    assert result["tax"] == round(15999.00 * 0.18, 2)
    assert result["total"] == round(15999.00 * 1.18, 2)


def test_welcome_coupon_discount():
    result = pricing.compute_total(catalog.get_order(1002), "WELCOME10")
    assert result["discount"] == round(15999.00 * 0.10, 2)
    assert result["coupon"] == "WELCOME10"


def test_average_item_price():
    result = pricing.compute_total(catalog.get_order(1001))
    assert result["item_count"] == 3
    assert result["average_item_price"] == round((3499.00 + 2 * 899.00) / 3, 2)
