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
