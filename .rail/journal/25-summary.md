# Sweep 25

Since 0d36e31e2f0c: 20 tickets merged; 12 commits merged without a review.

## Free part
- doc-lint: clean
- rule no-new-suppressions: 3 lines in the tree
- rule shortcut-names-its-ticket: 3 lines in the tree
- rule records-through-store: 0 lines in the tree
- rule roles-in-auth: 0 lines in the tree
- rule migrations-home: 0 lines in the tree

## Review
I read docs/api.md against shop/api.py, shop/export.py and shop/auth.py. The CSV columns and the error answer match the code. The "Who may call" sentence does not. I did not review the vendored Rail engine under .rail/; it is a third-party update.

- F1 (advisory) docs/api.md:15: The new text says only `api.delete_product` asks `shop/auth.py`, which is false. `api.rename_product` calls `auth.allowed(request, "rename")` and `api.delete_customer` calls `auth.allowed(request, "delete")`. Neither handler, nor `delete_product`, is in the handler table, so a reader cannot learn which handlers are role-gated. The new section also sits between the table and the `export.orders_csv()` paragraph, so the export paragraph now reads as part of 'Who may call'. Check: A doc-lint test that every public handler in shop/api.py is named in docs/api.md, and that each handler calling auth.allowed is listed as gated.

## Parked findings
(none)

## Proposed checks, by kind
- add `true` to the bad-id loop in test_delete_product_missing_is_404_for_a_bad_id_too, and reject bool in the handler. (6/F1)
- a test that saves a customer named "=1+1" and asserts the exported cell does not start with "=". (13/F1)
