import pytest
from ecommerce.cart import ShoppingCart
from ecommerce.checkout import CheckoutService


def test_empty_cart_checkout_no_null_pointer():
    """Bug 4: Checking out with an empty cart should safely return subtotal 0.0, not raise IndexError."""
    checkout = CheckoutService(tax_rate=0.1)
    cart = ShoppingCart()  # empty
    
    subtotal = checkout.calculate_subtotal(cart)
    assert subtotal == 0.0, f"Expected subtotal 0.0 for empty cart, got {subtotal}"
    
    receipt = checkout.process_checkout(cart)
    assert receipt["subtotal"] == 0.0
    assert receipt["total"] == 0.0
    assert receipt["item_count"] == 0
