import re

from shop import orders, store

_EMAIL = re.compile(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+")


def get_order(request):
    found = orders.summary(request.get("id"))
    if found is None:
        return {"status": 404, "error": "no such order"}
    return {"status": 200, "order": found}


def list_orders(request):
    return {"status": 200, "orders": store.list_orders()}


def list_customers(request):
    return {"status": 200, "customers": store.list_customers()}


def list_products(request):
    return {"status": 200, "products": store.list_products()}


def _customer_fields(request):
    """Return (name, email, None) for valid input, or (None, None, error)."""
    name, email = request.get("name"), request.get("email")
    if not isinstance(name, str) or not name.strip():
        return None, None, "name must not be empty"
    if not isinstance(email, str) or not _EMAIL.fullmatch(email):
        return None, None, "email must look like local@domain.tld"
    return name.strip(), email, None


def _find_customer(customer_id):
    # SHORTCUT(2): store has no get_customer, so this scans the list. Add
    # store.get_customer when the store may change (slice 2).
    for customer in store.list_customers():
        if customer["id"] == customer_id:
            return customer
    return None


def create_customer(request):
    name, email, error = _customer_fields(request)
    if error:
        return {"status": 400, "error": error}
    ids = [c["id"] for c in store.list_customers()]
    customer = {"id": max(ids, default=0) + 1, "name": name, "email": email}
    store.save_customer(customer)
    return {"status": 200, "customer": customer}


def get_customer(request):
    found = _find_customer(request.get("id"))
    if found is None:
        return {"status": 404, "error": "no such customer"}
    return {"status": 200, "customer": found}


def update_customer(request):
    found = _find_customer(request.get("id"))
    if found is None:
        return {"status": 404, "error": "no such customer"}
    name, email, error = _customer_fields(request)
    if error:
        return {"status": 400, "error": error}
    customer = {"id": found["id"], "name": name, "email": email}
    store.save_customer(customer)
    return {"status": 200, "customer": customer}
