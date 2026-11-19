import unittest

from shop import api, store


def new(name="Ann", email="ann@example.com"):
    return {"name": name, "email": email}


class CreateCustomer(unittest.TestCase):
    def setUp(self):
        store.reset()

    def test_create_customer_takes_id_1_first_then_the_next(self):
        first = api.create_customer(new())
        second = api.create_customer(new("Bob", "bob@example.org"))
        self.assertEqual(first, {"status": 200, "customer": {"id": 1, "name": "Ann", "email": "ann@example.com"}})
        self.assertEqual(second["customer"]["id"], 2)
        self.assertEqual(len(api.list_customers({})["customers"]), 2)

    def test_create_customer_uses_highest_stored_id_plus_one(self):
        store.save_customer({"id": 7, "name": "Z", "email": "z@z.io"})
        self.assertEqual(api.create_customer(new())["customer"]["id"], 8)

    def test_create_customer_trims_the_name(self):
        self.assertEqual(api.create_customer(new("  Ann  "))["customer"]["name"], "Ann")

    def test_create_customer_rejects_bad_names(self):
        for name in ("", "   ", None, 5):
            result = api.create_customer(new(name))
            self.assertEqual(result["status"], 400, name)
            self.assertIn("error", result)
        self.assertEqual(store.list_customers(), [])

    def test_create_customer_rejects_bad_emails(self):
        bad = ["", None, "ann", "ann@", "@x.com", "ann@x", "a b@x.com", "a@@x.com",
               "a@x .com", "a@.com", "a@x.", "a@x..com", 3]
        for email in bad:
            self.assertEqual(api.create_customer(new(email=email))["status"], 400, email)
        self.assertEqual(store.list_customers(), [])

    def test_create_customer_without_fields_is_400_not_a_raise(self):
        self.assertEqual(api.create_customer({})["status"], 400)


class GetCustomer(unittest.TestCase):
    def setUp(self):
        store.reset()

    def test_get_customer_returns_the_stored_one(self):
        store.save_customer({"id": 1, "name": "Ann", "email": "ann@example.com"})
        store.save_customer({"id": 2, "name": "Bob", "email": "bob@example.com"})
        self.assertEqual(api.get_customer({"id": 2}),
                         {"status": 200, "customer": {"id": 2, "name": "Bob", "email": "bob@example.com"}})

    def test_get_customer_missing_is_a_404(self):
        self.assertEqual(api.get_customer({"id": 9})["status"], 404)
        self.assertEqual(api.get_customer({})["status"], 404)


class UpdateCustomer(unittest.TestCase):
    def setUp(self):
        store.reset()
        store.save_customer({"id": 1, "name": "Ann", "email": "ann@example.com"})

    def test_update_customer_replaces_name_and_email_and_keeps_the_id(self):
        result = api.update_customer({"id": 1, "name": " Anna ", "email": "anna@example.net"})
        self.assertEqual(result, {"status": 200, "customer": {"id": 1, "name": "Anna", "email": "anna@example.net"}})
        self.assertEqual(api.get_customer({"id": 1})["customer"]["email"], "anna@example.net")
        self.assertEqual(len(store.list_customers()), 1)

    def test_update_customer_validates_both_fields_and_changes_nothing(self):
        for body in ({"name": "", "email": "a@b.co"}, {"name": "A", "email": "nope"}, {"name": "A"}):
            self.assertEqual(api.update_customer(dict(body, id=1))["status"], 400)
        self.assertEqual(store.list_customers()[0]["name"], "Ann")

    def test_update_customer_missing_is_a_404(self):
        self.assertEqual(api.update_customer({"id": 9, "name": "A", "email": "a@b.co"})["status"], 404)
