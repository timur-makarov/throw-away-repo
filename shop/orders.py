from decimal import ROUND_FLOOR, Decimal

from shop import store


def _line_cents(line):
    # str() keeps 0.29 as 0.29 instead of its binary float neighbour 0.28999...
    amount = Decimal(str(line["cents"])) * Decimal(str(line["quantity"]))
    return int(amount.to_integral_value(rounding=ROUND_FLOOR))


def total(order):
    return sum(_line_cents(line) for line in order["lines"])


def summary(order_id):
    order = store.get_order(order_id)
    if order is None:
        return None
    return {"id": order["id"], "total": total(order), "lines": len(order["lines"])}
