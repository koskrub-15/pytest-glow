def render(cart) -> str:
    lines = [f"{i.quantity} x {i.name:<20} {i.price * i.quantity:>8.2f}" for i in cart.items]
    lines.append("-" * 33)
    lines.append(f"{'total':<25} {cart.total():>8.2f}")
    return "\n".join(lines)
