COUPONS = {"WELCOME10": 0.10, "VIP25": 0.25}


def discount_for(code: str) -> float:
    code = code.strip().upper()
    if code not in COUPONS:
        raise ValueError(f"unknown coupon {code!r}")
    return COUPONS[code]


def shipping(total: float, country: str) -> float:
    if total >= 50:
        return 0.0
    if country == "DE":
        return 4.90
    if country in ("AT", "CH"):
        return 9.90
    return 14.90
