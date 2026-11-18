# Handlers

Each handler takes a request dict and returns a dict with a `status`.

| Handler | Request | Answer |
|---|---|---|
| `api.get_order` | `{"id": 1}` | `{"status": 200, "order": {"id", "total", "lines"}}` or a 404 |
| `api.list_orders` | `{}` | `{"status": 200, "orders": [...]}` |
| `api.list_customers` | `{}` | `{"status": 200, "customers": [...]}` |
| `api.list_products` | `{}` | `{"status": 200, "products": [...]}` |

`export.orders_csv()` returns every order as CSV with the columns `id` and `total`.
