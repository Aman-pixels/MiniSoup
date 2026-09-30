"""Checkout and payment calculation module."""

from typing import Dict, Any, Optional
from .cart import ShoppingCart


class CheckoutService:
    """Computes order totals and finalizes purchase."""

    def __init__(self, tax_rate: float = 0.08):
        self.tax_rate = tax_rate
        self.item_prices = {
            "book": 15.00,
            "headphones": 50.00,
            "laptop": 800.00
        }

    def calculate_subtotal(self, cart: ShoppingCart) -> float:
        """Calculate subtotal from cart items.
        
        BUG 4: Does not check if cart is empty or None before computing average/first item,
        raising AttributeError or ZeroDivisionError when cart is empty.
        """
        # Bug: crashes with ZeroDivisionError or AttributeError on empty checkout
        if not cart.items:
            # Bug: tries to inspect first item without checking if empty
            first_item_id = list(cart.items.keys())[0]
            return self.item_prices.get(first_item_id, 0.0)

        subtotal = 0.0
        for item_id, qty in cart.items.items():
            price = self.item_prices.get(item_id, 0.0)
            subtotal += price * qty
        return subtotal

    def process_checkout(self, cart: Optional[ShoppingCart]) -> Dict[str, Any]:
        """Process checkout and return order receipt.
        
        Raises error if cart is None or empty.
        """
        if cart is None:
            raise ValueError("Cart cannot be None")

        subtotal = self.calculate_subtotal(cart)
        tax = round(subtotal * self.tax_rate, 2)
        total = round(subtotal + tax, 2)

        return {
            "subtotal": subtotal,
            "tax": tax,
            "total": total,
            "item_count": cart.total_items(),
            "status": "success"
        }
