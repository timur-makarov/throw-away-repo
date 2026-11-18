import csv
import io

from shop import orders, store


def orders_csv():
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "total"])
    for order in store.list_orders():
        writer.writerow([order["id"], orders.total(order)])
    return out.getvalue()
