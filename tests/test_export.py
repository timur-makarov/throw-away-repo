from shop import export, store


def test_the_csv_has_a_header_and_one_row_per_order():
    store.reset()
    store.save_order({"id": 1, "lines": [{"cents": 250, "quantity": 2}]})
    assert export.orders_csv().splitlines() == ["id,customer_id,lines,total", "1,,1,500"]


def test_finance_columns_carry_customer_line_count_and_total_in_cents():
    store.reset()
    store.save_order(
        {
            "id": 1,
            "customer_id": 7,
            "lines": [{"cents": 250, "quantity": 2}, {"cents": 99, "quantity": 1}],
        }
    )
    store.save_order({"id": 2, "lines": [{"cents": 1000, "quantity": 3}]})
    store.save_order({"id": 3, "customer_id": 8, "lines": []})
    assert export.orders_csv().splitlines() == [
        "id,customer_id,lines,total",
        "1,7,2,599",
        "2,,1,3000",
        "3,8,0,0",
    ]


def test_the_csv_total_includes_the_discount_code():
    store.reset()
    store.save_code("TEN", 10)
    store.save_order({"id": 1, "code": "TEN", "lines": [{"cents": 999, "quantity": 1}]})
    assert export.orders_csv().splitlines()[1] == "1,,1,899"
