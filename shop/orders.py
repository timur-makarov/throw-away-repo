from shop import store


def total(order):
    return sum(line["cents"] * line["quantity"] for line in order["lines"])


def summary(order_id):
    order = store.get_order(order_id)
    if order is None:
        return None
    return {"id": order["id"], "total": total(order), "lines": len(order["lines"])}
