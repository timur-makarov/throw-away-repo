# Architecture

A small order service with no framework: each handler takes a request dict and returns a dict with a `status`.
The conventions are in `AGENTS.md`.

## Areas

| Area | Paths | Holds |
|---|---|---|
| Handlers | shop/api.py | The requests the service answers: get an order, list orders, customers and products, and their status codes |
| Orders | shop/orders.py | Order totals and summaries: what an order costs, in cents, and how many lines it has |
| Export | shop/export.py | The CSV download of every order with its total |
| Permissions | shop/auth.py | Who may read, write or delete: the roles admin, clerk and viewer |
| Store | shop/store.py, shop/__init__.py | Where orders, customers, products and discount codes are saved and read back |
| Migrations | migrations/** | The stored data's shape, one numbered SQL file per change |
| Tests | tests/** | The automated tests for handlers, orders, permissions and export |
| Docs | docs/** | What each handler accepts and answers, for people calling the service |
