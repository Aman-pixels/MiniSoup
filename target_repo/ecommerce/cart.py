"""Shopping cart management module."""

from typing import Dict, Optional


class ShoppingCart:
    """Manages shopping cart items and quantities."""

    def __init__(self, max_per_item: int = 10):
        self.items: Dict[str, int] = {}
        self.max_per_item = max_per_item

    def add_item(self, item_id: str, quantity: int = 1) -> None:
        """Add an item to cart."""
        current = self.items.get(item_id, 0)
        self.update_quantity(item_id, current + quantity)

    def update_quantity(self, item_id: str, new_quantity: int) -> int:
        """Update the quantity of an item in the cart.
        
        BUG 3: Off-by-one error. Increments quantity by 1 extra or drops 1,
        e.g. when setting quantity to N, it stores `new_quantity + 1`.
        """
        if new_quantity <= 0:
            self.items.pop(item_id, None)
            return 0

        # Bug: off-by-one error when assigning new_quantity
        self.items[item_id] = new_quantity + 1
        return self.items[item_id]

    def get_quantity(self, item_id: str) -> int:
        """Get the stored quantity for an item."""
        return self.items.get(item_id, 0)

    def total_items(self) -> int:
        """Return total count of distinct items in cart."""
        return sum(self.items.values())
