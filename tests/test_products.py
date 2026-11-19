from shop import api, store


def _two_products():
    store.reset()
    store.save_product({"id": 1, "name": "Tea", "cents": 300})
    store.save_product({"id": 2, "name": "Cake", "cents": 450})


def test_delete_product_admin_removes_it():
    _two_products()
    assert api.delete_product({"id": 1, "role": "admin"}) == {"status": 200}
    ids = [p["id"] for p in api.list_products({})["products"]]
    assert ids == [2]


def test_delete_product_non_admin_is_403_and_keeps_it():
    for role in ("clerk", "viewer", None):
        _two_products()
        request = {"id": 1} if role is None else {"id": 1, "role": role}
        answer = api.delete_product(request)
        assert answer["status"] == 403 and answer["error"]
        assert len(api.list_products({})["products"]) == 2


def test_delete_product_non_admin_is_403_even_when_missing():
    _two_products()
    assert api.delete_product({"id": 99, "role": "clerk"})["status"] == 403


def test_delete_product_missing_is_404():
    _two_products()
    answer = api.delete_product({"id": 99, "role": "admin"})
    assert answer["status"] == 404 and answer["error"]
    assert len(api.list_products({})["products"]) == 2


def test_delete_product_missing_is_404_for_a_bad_id_too():
    for bad in (None, "1", [1]):
        _two_products()
        assert api.delete_product({"id": bad, "role": "admin"})["status"] == 404
