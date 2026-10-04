"""Client for the (sandbox) external payment gateway."""
import itertools


class PaymentGatewayTimeout(Exception):
    pass


_calls = itertools.count(1)


def charge(order_id, amount):
    n = next(_calls)
    # The sandbox gateway is flaky: roughly one call in seven times out.
    if n % 7 == 0:
        raise PaymentGatewayTimeout(f"gateway did not respond within 3000ms (order {order_id})")
    return {"order_id": order_id, "amount": amount, "status": "captured", "transaction_id": f"TXN-{order_id}-{n}"}
