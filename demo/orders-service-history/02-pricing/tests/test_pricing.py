from app import catalog, pricing


def test_subtotal():
    assert pricing.order_subtotal(catalog.get_order(1001)) == 3499.00 + 2 * 899.00


def test_total_includes_gst():
    result = pricing.compute_total(catalog.get_order(1002))
    assert result["subtotal"] == 15999.00
    assert result["tax"] == round(15999.00 * 0.18, 2)
    assert result["total"] == round(15999.00 * 1.18, 2)
