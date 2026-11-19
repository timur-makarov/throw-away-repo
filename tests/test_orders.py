import unittest

from shop import api, store


def order(n, cents=500):
    return {"id": n, "lines": [{"cents": cents, "quantity": 2}]}


class Orders(unittest.TestCase):
    def setUp(self):
        store.reset()

    def test_a_summary_has_the_total(self):
        store.save_order(order(1))
        self.assertEqual(api.get_order({"id": 1})["order"]["total"], 1000)

    def test_a_missing_order_is_a_404(self):
        self.assertEqual(api.get_order({"id": 9})["status"], 404)

    def test_a_fractional_quantity_gives_an_integer_total(self):
        store.save_order({"id": 1, "lines": [{"cents": 1000, "quantity": 0.25}]})
        found = api.get_order({"id": 1})["order"]["total"]
        self.assertEqual(found, 250)
        self.assertIs(type(found), int)

    def test_each_line_rounds_down_before_the_lines_are_added(self):
        # 0.29 * 100 is 28.999... in binary floats; exact decimals give 29.
        # 0.5 * 3 = 1.5 -> 1 and 0.5 * 3 = 1.5 -> 1, so 29 + 1 + 1 = 31, not floor(31.999) or 32.
        store.save_order({"id": 1, "lines": [
            {"cents": 100, "quantity": 0.29},
            {"cents": 3, "quantity": 0.5},
            {"cents": 3, "quantity": 0.5},
        ]})
        self.assertEqual(api.get_order({"id": 1})["order"]["total"], 31)

    def test_integer_quantities_keep_their_totals(self):
        store.save_order({"id": 1, "lines": [{"cents": 250, "quantity": 2}, {"cents": 99, "quantity": 3}]})
        self.assertEqual(api.get_order({"id": 1})["order"]["total"], 797)

    def test_a_discount_code_reduces_total_rounded_down(self):
        store.save_code("TEN", 10)
        store.save_code("HALFPLUS", 12.5)
        store.save_order({"id": 1, "code": "TEN", "lines": [{"cents": 999, "quantity": 1}]})
        store.save_order({"id": 2, "code": "HALFPLUS", "lines": [{"cents": 999, "quantity": 1}]})
        # 999 * 0.9 = 899.1 -> 899; 999 * 0.875 = 874.125 -> 874
        self.assertEqual(api.get_order({"id": 1})["order"]["total"], 899)
        self.assertEqual(api.get_order({"id": 2})["order"]["total"], 874)
        self.assertIs(type(api.get_order({"id": 2})["order"]["total"]), int)

    def test_a_discount_code_reduces_total_after_lines_are_summed(self):
        store.save_code("HALF", 50)
        # Per line: 3 * 0.5 -> 1 twice = 2. On the sum: 6 * 0.5 = 3.
        store.save_order({"id": 1, "code": "HALF", "lines": [{"cents": 3, "quantity": 1}, {"cents": 3, "quantity": 1}]})
        self.assertEqual(api.get_order({"id": 1})["order"]["total"], 3)

    def test_an_unknown_code_changes_nothing(self):
        store.save_order({"id": 1, "code": "NOPE", "lines": [{"cents": 999, "quantity": 1}]})
        store.save_order({"id": 2, "lines": [{"cents": 999, "quantity": 1}]})
        self.assertEqual(api.get_order({"id": 1})["order"]["total"], 999)
        self.assertEqual(api.get_order({"id": 2})["order"]["total"], 999)

    def test_status_defaults_to_open(self):
        store.save_order(order(1))
        self.assertEqual(api.get_order({"id": 1})["order"]["status"], "open")

    def test_summary_shows_status_as_stored(self):
        for n, status in enumerate(("open", "paid", "cancelled"), start=1):
            store.save_order({**order(n), "status": status})
            found = api.get_order({"id": n})["order"]
            self.assertEqual(found, {"id": n, "total": 1000, "lines": 1, "status": status})
