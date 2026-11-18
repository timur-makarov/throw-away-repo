from shop import orders, store


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
