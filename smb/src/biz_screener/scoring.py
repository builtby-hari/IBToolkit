"""Weighted score, red-flag penalty and ranking."""
from typing import Dict, List, Optional

from .models import Score

def _scale(x: float, lo: float, hi: float) -> float:
    """Linear map lo->0, hi->100, clamped. hi may be below lo for inverse scales."""
    return max(0.0, min(100.0, (x - lo) / (hi - lo) * 100))


def valuation_gap_score(asking: float, blended: float) -> float:
    """100 at asking 10 percent under blended value, 0 at 40 percent over."""
    if blended <= 0:
        return 0.0
    return _scale((asking - blended) / blended, 0.40, -0.10)


def dscr_score(dscr: float) -> float:
    return _scale(dscr, 1.0, 2.5)


def trend_score(cagr: Optional[float]) -> float:
    """A blank growth figure scores 0: unknown is never filled with a guess."""
    return 0.0 if cagr is None else _scale(cagr, -0.05, 0.05)


def concentration_score(top_share: Optional[float]) -> float:
    """A blank top customer share scores 0, same rule."""
    return 0.0 if top_share is None else _scale(top_share, 0.50, 0.05)


def market_score(growth: Optional[float]) -> Optional[float]:
    """None when market data is not built: the component is dropped, not scored neutral."""
    return None if growth is None else _scale(growth, -0.03, 0.03)


def total_score(components: Dict[str, float], weights: Dict[str, float],
                penalty: float) -> float:
    # A component that is absent is dropped and the rest rescaled to the same weight total.
    used = {k: w for k, w in weights.items() if k in components or k != "market_context"}
    scale = sum(weights.values()) / sum(used.values())
    raw = sum(w * scale * components.get(k, 0.0) / 100 for k, w in used.items())
    return max(0.0, raw - penalty)


def rank_listings(scores: List[Score]) -> List[Score]:
    """Highest total first; ties go to the lower asking price."""
    ordered = sorted(scores, key=lambda s: (-s.total, s.asking_price))
    for i, s in enumerate(ordered, 1):
        s.rank = i
    return ordered
