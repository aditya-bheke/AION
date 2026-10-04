"""Orders service HTTP API."""
import logging
import os
import subprocess

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app import catalog, pricing
from app.logging_setup import configure_logging

configure_logging()
log = logging.getLogger("orders.api")
app = FastAPI(title="Orders Service")


def _current_commit():
    """Git commit of the running code, reported by /health (used to verify deployments)."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=os.path.dirname(os.path.abspath(__file__)),
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


COMMIT = _current_commit()


@app.middleware("http")
async def access_log(request: Request, call_next):
    req = {"method": request.method, "path": request.url.path, "query": request.url.query}
    try:
        response = await call_next(request)
    except Exception:
        req["status"] = 500
        log.exception("Unhandled exception while processing request", extra={"request": req})
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
    req["status"] = response.status_code
    log.info("%s %s -> %s", request.method, request.url.path, response.status_code, extra={"request": req})
    return response


@app.get("/health")
def health():
    return {"status": "ok", "service": "orders-service", "commit": COMMIT}


@app.get("/products")
def list_products():
    return catalog.list_products()


@app.get("/products/{sku}")
def get_product(sku: str):
    product = catalog.get_product(sku)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {sku} not found")
    return product


def _order_or_404(order_id: int):
    order = catalog.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return order


@app.get("/orders/{order_id}")
def get_order(order_id: int):
    return _order_or_404(order_id)


@app.get("/orders/{order_id}/total")
def order_total(order_id: int):
    return pricing.compute_total(_order_or_404(order_id))
