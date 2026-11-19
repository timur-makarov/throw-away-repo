# Handlers

Each handler takes a request dict and returns a dict with a `status`.

| Handler | Request | Answer |
|---|---|---|
| `api.get_order` | `{"id": 1}` | `{"status": 200, "order": {"id", "total", "lines"}}` or a 404 |
| `api.list_orders` | `{}` | `{"status": 200, "orders": [...]}` |
| `api.list_customers` | `{}` | `{"status": 200, "customers": [...]}` |
| `api.list_products` | `{}` | `{"status": 200, "products": [...]}` |
| `api.create_customer` | `{"name", "email"}` | `{"status": 200, "customer": {"id", "name", "email"}}`; the id is the highest stored id plus 1 (1 when none); a 400 with `error` when `name` is empty after trimming or `email` is not `local@domain.tld` |
| `api.get_customer` | `{"id": 1}` | `{"status": 200, "customer": {"id", "name", "email"}}` or a 404 |
| `api.update_customer` | `{"id": 1, "name", "email"}` | `{"status": 200, "customer": {...}}` with `name` and `email` replaced together and the id kept; a 400 with `error` when either is invalid (nothing changes), or a 404 |

`export.orders_csv()` returns every order as CSV with the columns `id` and `total`.

## Error answers

A handler does not raise on bad input. A failed call returns a 4xx `status` and an `error` text instead of the success fields:

```python
api.get_order({"id": 99999})
# {"status": 404, "error": "no such order"}
```
