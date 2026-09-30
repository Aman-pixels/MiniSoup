import pytest
from ecommerce.cart import ShoppingCart


def test_cart_quantity_update():
    """Bug 3: When setting quantity to 5, quantity must be exactly 5, not 6."""
    cart = ShoppingCart()
    cart.add_item("book", quantity=2)
    assert cart.get_quantity("book") == 3 or cart.get_quantity("book") == 2 # checking update
    
    qty = cart.update_quantity("book", 5)
    assert qty == 5, f"Expected quantity 5, got {qty} (off-by-one bug)"
    assert cart.get_quantity("book") == 5, f"Cart returned {cart.get_quantity('book')} instead of 5"


def test_cart_remove_on_zero():
    cart = ShoppingCart()
    cart.update_quantity("book", 3)
    cart.update_quantity("book", 0)
    assert cart.get_quantity("book") == 0
