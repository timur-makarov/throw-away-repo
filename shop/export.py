import csv
import io

from shop import orders, store


def _safe(value):
    text = str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def _writer(header):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    return out, writer


def orders_csv():
    out, writer = _writer(["id", "customer_id", "lines", "total"])
    for order in store.list_orders():
        writer.writerow([order["id"], order.get("customer_id", ""), len(order["lines"]), orders.total(order)])
    return out.getvalue()


def customers_csv():
    out, writer = _writer(["id", "name"])
    for customer in store.list_customers():
        writer.writerow([customer["id"], _safe(customer["name"])])
    return out.getvalue()


def products_csv():
    out, writer = _writer(["id", "name", "cents"])
    for product in store.list_products():
        writer.writerow([product["id"], _safe(product["name"]), product["cents"]])
    return out.getvalue()
