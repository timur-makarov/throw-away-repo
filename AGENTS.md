# Shop

A small order service. No framework: handlers take a dict and return a dict.

## Conventions
- Money is an integer number of cents. Discounts round the total down to the whole cent.
- All reads and writes of stored records go through `shop/store.py`.
- A handler returns `{"status": 200, ...}` or `{"status": 4xx, "error": "..."}`. A handler does not raise on bad input.
- Pages are numbered from 1.
- Tests run with `python3 -m pytest -q`. Lint runs with `ruff check .`.
- Who may do what is decided in `shop/auth.py` and nowhere else.
- A change to stored data's shape comes with a numbered file in `migrations/`.
