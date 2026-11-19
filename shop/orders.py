from decimal import ROUND_FLOOR, Decimal

from shop import store


def _line_cents(line):
    # str() keeps 0.29 as 0.29 instead of its binary float neighbour 0.28999...
    amount = Decimal(str(line["cents"])) * Decimal(str(line["quantity"]))
    return int(amount.to_integral_value(rounding=ROUND_FLOOR))


def total(order):
    cents = sum(_line_cents(line) for line in order["lines"])
    percent = store.get_code(order["code"]) if "code" in order else None
    if percent is None:
        return cents
    discounted = Decimal(cents) * (100 - Decimal(str(percent))) / 100
    return int(discounted.to_integral_value(rounding=ROUND_FLOOR))


def summary(order_id):
    order = store.get_order(order_id)
    if order is None:
        return None
    return {
        "id": order["id"],
        "total": total(order),
        "lines": len(order["lines"]),
        "status": order.get("status", "open"),
    }
