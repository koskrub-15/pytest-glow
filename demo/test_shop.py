from shop.cart import Cart, Item
from shop.pricing import shipping


def test_add_merges_same_item():
    cart = Cart()
    cart.add(Item("tea", 4.5))
    cart.add(Item("tea", 4.5, 2))
    assert cart.items[0].quantity == 3


def test_coupon():
    cart = Cart([Item("book", 20.0)], coupon="welcome10")
    assert cart.total() == 18.0


def test_free_shipping():
    assert shipping(60, "FR") == 0.0
