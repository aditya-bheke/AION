from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_products():
    r = client.get("/products")
    assert r.status_code == 200
    assert len(r.json()) == 6


def test_get_order():
    r = client.get("/orders/1001")
    assert r.status_code == 200
    assert r.json()["customer"] == "C-501"


def test_unknown_order_is_404():
    assert client.get("/orders/9999").status_code == 404


def test_unknown_product_is_404():
    assert client.get("/products/SKU-0000").status_code == 404


def test_supplier_product_is_listed():
    r = client.get("/products/SKU-1006")
    assert r.status_code == 200
    assert r.json()["supplier"] == "DockCo"
