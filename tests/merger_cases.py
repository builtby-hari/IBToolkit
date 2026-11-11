import copy
from pathlib import Path

from ibtoolkit.merger import load_case

ROOT = Path(__file__).resolve().parent.parent


def sample():
    return load_case(ROOT / "cases" / "merger_sample.toml")


def all_stock():
    """Hand-checkable: no marks, CDI, saves, charges or cash. Acquirer EPS 1.00 at $10,
    target pays $100 in stock, so 10 new shares on 100 existing."""
    c = copy.deepcopy(sample())
    c["acquirer"].update(net_income=[100.0, 100.0], shares=100.0, share_price=10.0,
                         tbv=500.0, tangible_assets=5000.0)
    c["target"].update(net_income=[12.0, 12.0], shares=20.0, share_price=4.0, tbv=40.0,
                       tangible_assets=400.0, noninterest_expense=50.0,
                       core_deposits=0.0, loans=0.0, securities=0.0)
    c["deal"].pop("p_tbv", None)
    c["deal"].update(price_per_share=5.0, stock_pct=1.0, cost_of_cash=0.0, cost_saves_pct=0.0,
                     phase_in=[0.0, 0.0], merger_charges=0.0, cdi_pct=0.0, tax_rate=0.25)
    return c
