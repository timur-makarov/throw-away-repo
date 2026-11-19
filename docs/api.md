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

## Who may call

Who may call `api.create_customer`, `api.get_customer` and `api.update_customer`: any caller. These handlers make no role check and ignore `request["role"]`.

Role-gated handlers ask `shop/auth.py` and answer a 403 with `error` when the role may not:

| Handler | Request | Role needed |
|---|---|---|
| `api.delete_product` | `{"id": 1}` | `admin` (action `delete`) |
| `api.rename_product` | `{"id": 1, "name"}` | `admin` (action `rename`) |
| `api.delete_customer` | `{"id": 1}` | `admin` (action `delete`) |

## Orders export

`export.orders_csv()` returns every order as CSV with the columns `id`, `customer_id`, `lines` and `total`: `customer_id` is empty when the order has none, `lines` is the number of lines, and `total` is in integer cents. With no orders it still returns the header row.

## Error answers

A handler does not raise on bad input. A failed call returns a 4xx `status` and an `error` text instead of the success fields:

```python
api.get_order({"id": 99999})
# {"status": 404, "error": "no such order"}
```
