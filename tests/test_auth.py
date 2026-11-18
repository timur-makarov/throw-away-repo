from shop import auth


def test_a_viewer_reads_and_does_not_write():
    assert auth.allowed({"role": "viewer"}, "read")
    assert not auth.allowed({"role": "viewer"}, "write")


def test_an_unknown_role_may_do_nothing():
    assert not auth.allowed({"role": "guest"}, "read")
    assert not auth.allowed({}, "read")
