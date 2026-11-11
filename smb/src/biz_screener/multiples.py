"""Value a business from SDE and EBITDA using industry multiple ranges."""
from typing import Tuple


def pick_multiple(low: float, high: float, use_midpoint: bool) -> float:
    if low > high:
        raise ValueError("multiple low is above high")
    return (low + high) / 2 if use_midpoint else low


def _value(earnings: float, industry: dict, prefix: str, use_midpoint: bool) -> float:
    return earnings * pick_multiple(industry[prefix + "_multiple_low"],
                                    industry[prefix + "_multiple_high"], use_midpoint)


def value_from_sde(sde: float, industry: dict, use_midpoint: bool = True) -> float:
    return _value(sde, industry, "sde", use_midpoint)


def value_from_ebitda(ebitda: float, industry: dict, use_midpoint: bool = True) -> float:
    return _value(ebitda, industry, "ebitda", use_midpoint)


def asking_multiples(asking_price: float, sde: float, ebitda: float) -> Tuple[float, float]:
    """(price/SDE, price/EBITDA); infinity when earnings are not positive."""
    inf = float("inf")
    return (asking_price / sde if sde > 0 else inf,
            asking_price / ebitda if ebitda > 0 else inf)
