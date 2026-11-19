import time
import warnings


def make_user(name):
    time.sleep(0.15)
    return {"name": name, "role": "user", "active": True}


def test_create_user():
    assert make_user("ada")["name"] == "ada"


def test_user_payload():
    user = make_user("grace")
    assert user == {"name": "grace", "role": "admin", "active": True}


def test_query_users(database):
    assert database.query("select 1")


def test_delete_user(database):
    assert database.execute("delete from users where id = 1")


def test_list_orders(database):
    assert database.query("select * from orders")


def test_legacy_endpoint():
    warnings.warn("legacy endpoint is deprecated, use /v2/users", DeprecationWarning)
    time.sleep(0.1)


def test_upload_big_file():
    time.sleep(2.5)
