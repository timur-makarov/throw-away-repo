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
