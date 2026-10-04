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
    assert result["discount"] == 500.00  # 10% capped at Rs 500
    assert result["coupon"] == "WELCOME10"


def test_campaign_coupon_is_capped():
    result = pricing.compute_total(catalog.get_order(1005), "DIWALI25")
    assert result["discount"] == 3000.00
