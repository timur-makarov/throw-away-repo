"""The only module that touches stored records."""
_ORDERS, _CUSTOMERS, _PRODUCTS, _CODES = {}, {}, {}, {}


def reset():
    for table in (_ORDERS, _CUSTOMERS, _PRODUCTS, _CODES):
        table.clear()


def save_order(order):
    _ORDERS[order["id"]] = dict(order)


def get_order(order_id):
    found = _ORDERS.get(order_id)
    return dict(found) if found else None


def list_orders():
    return [dict(o) for _, o in sorted(_ORDERS.items())]


def save_customer(customer):
    _CUSTOMERS[customer["id"]] = dict(customer)


def list_customers():
    return [dict(c) for _, c in sorted(_CUSTOMERS.items())]


def save_product(product):
    _PRODUCTS[product["id"]] = dict(product)


def list_products():
    return [dict(p) for _, p in sorted(_PRODUCTS.items())]


def rename_product(product_id, name):
    """Set a stored product's name. Return False when there is no such product."""
    found = _PRODUCTS.get(product_id)
    if found is None:
        return False
    found["name"] = name
    return True


def delete_product(product_id):
    return _PRODUCTS.pop(product_id, None) is not None


def save_code(code, percent):
    _CODES[code] = percent


def get_code(code):
    return _CODES.get(code)
