import csv
import io

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


def test_no_orders_still_returns_the_header_row():
    store.reset()
    assert export.orders_csv() == "id,customer_id,lines,total\r\n"


def test_customers_csv_has_a_header_and_one_row_per_customer():
    store.reset()
    store.save_customer({"id": 2, "name": "Bob"})
    store.save_customer({"id": 1, "name": "Ann"})
    assert export.customers_csv().splitlines() == ["id,name", "1,Ann", "2,Bob"]


def test_customers_csv_with_no_customers_is_just_the_header():
    store.reset()
    assert export.customers_csv() == "id,name\r\n"


def test_customers_csv_neutralizes_formula_names(monkeypatch):
    monkeypatch.setattr(store, "list_customers", lambda: [{"id": 1, "name": "=HYPERLINK(\"x\")"}, {"id": 2, "name": "@a"}])
    rows = list(csv.reader(io.StringIO(export.customers_csv())))
    assert rows[1][1] == "'=HYPERLINK(\"x\")"
    assert rows[2][1] == "'@a"


def test_header_helper_writes_the_header_row_first():
    out, writer = export._writer(["a", "b"])
    writer.writerow([1, 2])
    assert out.getvalue() == "a,b\r\n1,2\r\n"
