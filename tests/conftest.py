import copy
import shutil
from pathlib import Path

import pytest

from ibtoolkit.lbo import load_case

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sample():
    return load_case(ROOT / "cases" / "lbo_sample.toml")


@pytest.fixture
def no_debt(sample):
    """Hand-checkable case: no debt, no fees, flat EBITDA of 100, all cash kept."""
    c = copy.deepcopy(sample)
    c["transaction"].update(ltm_revenue=1000.0, ltm_ebitda=100.0, entry_multiple=8.0,
                            exit_multiple=8.0, advisory_fee_pct=0.0, financing_fee_pct=0.0)
    c["operating"].update(revenue_growth=[0.0] * 5, ebitda_margin=[0.1] * 5, da_pct_revenue=0.0,
                          capex_pct_revenue=0.0, nwc_pct_revenue_change=0.0, tax_rate=0.0)
    c["senior"]["leverage"] = 0.0
    c["mezz"] = {"leverage": 0.0, "cash_rate": 0.0, "pik_rate": 0.0}
    c["revolver"] = {"commitment": 0.0, "rate": 0.0, "undrawn_fee": 0.0, "min_cash": 0.0}
    return c


@pytest.fixture
def outdir():
    d = ROOT / "output" / "tests"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d)
