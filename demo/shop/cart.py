from dataclasses import dataclass, field

from .pricing import discount_for


@dataclass
class Item:
    name: str
    price: float
    quantity: int = 1


@dataclass
class Cart:
    items: list = field(default_factory=list)
    coupon: str | None = None

    def add(self, item: Item) -> None:
        for existing in self.items:
            if existing.name == item.name:
                existing.quantity += item.quantity
                return
        self.items.append(item)

    def remove(self, name: str) -> None:
        self.items = [i for i in self.items if i.name != name]
        if not self.items:
            self.coupon = None

    def subtotal(self) -> float:
        return sum(i.price * i.quantity for i in self.items)

    def total(self) -> float:
        subtotal = self.subtotal()
        if self.coupon:
            subtotal *= 1 - discount_for(self.coupon)
        return round(subtotal, 2)
