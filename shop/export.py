import csv
import io

from shop import orders, store


def _safe(value):
    text = str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def orders_csv():
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "customer_id", "lines", "total"])
    for order in store.list_orders():
        writer.writerow([order["id"], order.get("customer_id", ""), len(order["lines"]), orders.total(order)])
    return out.getvalue()


def customers_csv():
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "name"])
    for customer in store.list_customers():
        writer.writerow([customer["id"], _safe(customer["name"])])
    return out.getvalue()
