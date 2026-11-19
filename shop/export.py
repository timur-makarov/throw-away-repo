import csv
import io

from shop import orders, store


def orders_csv():
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "customer_id", "lines", "total"])
    for order in store.list_orders():
        writer.writerow([order["id"], order.get("customer_id", ""), len(order["lines"]), orders.total(order)])
    return out.getvalue()
