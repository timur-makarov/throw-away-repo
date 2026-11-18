from shop import export, store


def test_the_csv_has_a_header_and_one_row_per_order():
    store.reset()
    store.save_order({"id": 1, "lines": [{"cents": 250, "quantity": 2}]})
    assert export.orders_csv().splitlines() == ["id,total", "1,500"]
