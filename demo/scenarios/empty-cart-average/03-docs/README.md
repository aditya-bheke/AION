# orders-service

Order lookup and pricing API for the storefront.

## Endpoints

| Method | Path                         | Description                                   |
|--------|------------------------------|-----------------------------------------------|
| GET    | `/health`                    | Liveness check, reports the running commit    |
| GET    | `/products`                  | List all products                             |
| GET    | `/products/{sku}`            | Get one product                               |
| GET    | `/orders/{id}`               | Get an order                                  |
| GET    | `/orders/{id}/total?coupon=` | Price an order (GST 18%), optional coupon     |
| POST   | `/orders/{id}/pay`           | Charge the order through the payment gateway  |

## Pricing

Totals include 18% GST, optional coupon discounts, the item count and the average item price.

## Run locally

    python -m uvicorn app.main:app --port 8101

## Tests

    python -m pytest -q
