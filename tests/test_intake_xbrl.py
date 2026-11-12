"""XBRL extraction, offline. Fixtures are trimmed copies of real SEC companyfacts (Home Depot, Apple)."""
import copy
import json
from pathlib import Path

import pytest

from ibtoolkit.intake import xbrl
from ibtoolkit.intake.fields import FLAG

FIX = Path(__file__).parent / "fixtures"
UA = "IBToolkit research tool admin@example.com"


def load(name):
    return json.loads((FIX / name).read_text())


def as_of(facts, filed_on_or_before):
    """Facts as they stood on a date: drop rows filed later."""
    f = copy.deepcopy(facts)
    for entry in f["facts"]["us-gaap"].values():
        for unit, rows in entry["units"].items():
            entry["units"][unit] = [r for r in rows if r["filed"] <= filed_on_or_before]
    return f


def pick(values, field, ptype):
    hits = [v for v in values if v.field == field and v.period_type == ptype]
    assert hits, f"no {ptype} value for {field}"
    return max(hits, key=lambda v: v.period_end)


def synth(tag, rows, unit="USD"):
    return {"cik": 1, "entityName": "Synthetic", "facts": {"us-gaap": {tag: {"units": {unit: rows}}}}}


def row(end, val, form="10-K", fp="FY", fy=2024, filed="2025-02-01", accn="0000000001-25-000001", start=None):
    r = dict(end=end, val=val, fy=fy, fp=fp, form=form, filed=filed, accn=accn)
    if start:
        r["start"] = start
    return r


# ---- hand tie-out: Home Depot 10-K for the fiscal year ended 2026-02-01 (accn 0001628280-26-019436) --------

def test_tie_out_home_depot_10k():
    """Every number below is on the filed statements: SEC rendered 10-K pages R3 (balance sheet) and
    R5 (earnings) for accn 0001628280-26-019436, in $ millions."""
    vals = xbrl.extract(as_of(load("companyfacts_hd.json"), "2026-03-18"))
    ltm = lambda f: pick(vals, f, "LTM").value / 1e6
    inst = lambda f: pick(vals, f, "instant").value / 1e6
    assert ltm("revenue") == 164_683          # Net sales
    assert ltm("operating_income") == 20_890  # Operating income
    assert ltm("interest_expense") == 2_412   # Interest expense
    assert ltm("income_tax") == 4_446         # Provision for income taxes
    assert ltm("net_income") == 14_156        # Net earnings
    assert pick(vals, "diluted_eps", "LTM").value == 14.23  # Diluted EPS (dollars)
    assert pick(vals, "diluted_shares", "FY").value / 1e6 == 995
    assert inst("cash") == 1_389
    assert inst("current_assets") == 34_391
    assert inst("current_liabilities") == 32_424
    assert inst("total_assets") == 105_095
    assert inst("liabilities_and_equity") == 105_095
    assert inst("goodwill") == 22_344
    assert inst("intangibles") == 10_329
    # Debt = short-term debt 4,464 + current installments 4,967 + long-term debt 46,341
    assert inst("debt") == 4_464 + 4_967 + 46_341
    assert pick(vals, "revenue", "LTM").period_end == "2026-02-01"
    assert all(v.status != FLAG for v in vals)


def test_tie_out_apple_net_income():
    """Apple 10-K FY2026 (accn 0000320193-26-000026) statements: net income 132,175 and 112,010 for FY2025."""
    vals = xbrl.extract(load("companyfacts_aapl.json"))
    v = pick(vals, "net_income", "FY")
    assert v.value == 132_175_000_000 and v.period_end == "2026-09-26"
    assert "10-K FY2026 accn 0000320193-26-000026 tag NetIncomeLoss" in v.source_ref


# ---- LTM and periods ---------------------------------------------------------------------------------

def test_ltm_from_fy_plus_ytd_minus_prior_ytd():
    vals = xbrl.extract(load("companyfacts_hd.json"))
    ltm = pick(vals, "revenue", "LTM")
    assert ltm.period_end == "2026-08-02" and ltm.period_start == "2025-08-03"
    assert ltm.value == 164_683_000_000 + 89_626_000_000 - 85_133_000_000 == 169_176_000_000
    # the citation lists all three pieces
    assert ltm.source_ref.startswith("LTM to 2026-08-02 = 10-K FY2025 accn 0001628280-26-019436 tag "
                                     "RevenueFromContractWithCustomerExcludingAssessedTax")
    assert ltm.source_ref.count(" accn ") == 3 and "YTD to 2026-08-02" in ltm.source_ref and "YTD to 2025-08-03" in ltm.source_ref
    assert pick(vals, "revenue", "FY").value == 164_683_000_000
    assert pick(vals, "revenue", "YTD").value == 89_626_000_000
    assert pick(vals, "revenue", "Q").value == 47_861_000_000


def test_balance_sheet_is_instant_at_latest_period_end():
    vals = xbrl.extract(load("companyfacts_hd.json"))
    cash = pick(vals, "cash", "instant")
    assert cash.value == 2_085_000_000 and cash.period_end == "2026-08-02" and cash.period_start == ""
    assert cash.source_ref == ("10-Q Q2 FY2026 (at 2026-08-02) accn 0001628280-26-058715 "
                               "tag CashAndCashEquivalentsAtCarryingValue")
    debt = pick(vals, "debt", "instant")
    assert debt.value == 43_951_000_000 + 4_697_000_000 + 4_248_000_000
    assert "excludes operating leases" in debt.notes[0]


def test_latest_period_is_fiscal_year_gives_ltm_equal_fy():
    vals = xbrl.extract(load("companyfacts_aapl.json"))
    ltm = pick(vals, "revenue", "LTM")
    assert ltm.value == 478_834_000_000 and "no later 10-Q" in ltm.source_ref
    assert pick(vals, "debt", "instant").value == 68_208_000_000 + 9_906_000_000 + 1_997_000_000


def test_first_quarter_ytd_is_the_quarter():
    rows = [row("2024-12-31", 1000, start="2024-01-01"),
            row("2025-03-31", 300, "10-Q", "Q1", 2025, "2025-05-01", "0000000001-25-000002", "2025-01-01"),
            row("2024-03-31", 250, "10-Q", "Q1", 2025, "2025-05-01", "0000000001-25-000002", "2024-01-01")]
    vals = xbrl.extract(synth("Revenues", rows))
    assert pick(vals, "revenue", "LTM").value == 1000 + 300 - 250
    assert pick(vals, "revenue", "YTD").value == 300 and pick(vals, "revenue", "Q").value == 300


# ---- duplicates, sign, stale, units, forms ----------------------------------------------------------------

def test_restated_period_takes_latest_filed_and_says_so():
    rows = [row("2024-12-31", 1000, start="2024-01-01", filed="2025-02-01", accn="0000000001-25-000001"),
            row("2024-12-31", 990, filed="2026-02-01", fy=2025, accn="0000000001-26-000001", start="2024-01-01")]
    v = pick(xbrl.extract(synth("Revenues", rows)), "revenue", "FY")
    assert v.value == 990 and "accn 0000000001-26-000001" in v.source_ref
    assert any("restated" in n and "1000" in n for n in v.notes)
    assert "FY2024" in v.source_ref  # labelled by the year of the original filing


def test_only_10k_and_10q_rows_are_used():
    rows = [row("2024-12-31", 1000, start="2024-01-01"),
            row("2024-12-31", 5, form="DEF 14A", fp=None, filed="2025-04-01", start="2024-01-01")]
    assert pick(xbrl.extract(synth("Revenues", rows)), "revenue", "FY").value == 1000


def test_capex_is_positive():
    rows = [row("2024-12-31", -400, start="2024-01-01")]
    v = pick(xbrl.extract(synth("PaymentsToAcquirePropertyPlantAndEquipment", rows)), "capex", "FY")
    assert v.value == 400 and any("sign flipped" in n for n in v.notes)


def test_tag_preference_and_most_recent_tag_wins():
    facts = synth("Revenues", [row("2019-12-31", 700, start="2019-01-01", fy=2019)])
    facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"] = {
        "units": {"USD": [row("2024-12-31", 1000, start="2024-01-01")]}}
    v = pick(xbrl.extract(facts), "revenue", "FY")
    assert v.value == 1000 and v.source_ref.endswith("RevenueFromContractWithCustomerExcludingAssessedTax")


def test_old_tags_are_flagged_stale():
    vals = xbrl.extract(load("companyfacts_aapl.json"))
    for f in ("goodwill", "interest_expense"):
        v = [x for x in vals if x.field == f][0]
        assert v.status == FLAG and "different tag" in v.notes[0]
    assert pick(vals, "revenue", "FY").status != FLAG


def test_wrong_unit_tag_is_ignored():
    facts = synth("Revenues", [row("2024-12-31", 1000, start="2024-01-01")], unit="EUR")
    assert xbrl.extract(facts) == []


def test_every_value_has_source_and_valid_field():
    for name in ("companyfacts_hd.json", "companyfacts_aapl.json", "companyfacts_sample.json"):
        for v in xbrl.extract(load(name)):
            assert v.source_ref and v.source_kind == "xbrl" and v.period_end


# ---- ticker to CIK ---------------------------------------------------------------------------------------

class Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_cik_for_ticker_from_fixture():
    t = load("company_tickers_sample.json")
    assert xbrl.cik_for_ticker("hd", t) == "354950"
    assert xbrl.cik_for_ticker("AAPL", t) == "320193"
    assert xbrl.cik_for_ticker("BRK.B", t) == "1067983"
    with pytest.raises(xbrl.XbrlError):
        xbrl.cik_for_ticker("NOPE", t)


def test_load_tickers_sends_user_agent(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    seen = {}

    def opener(req):
        seen["ua"] = req.get_header("User-agent")
        seen["url"] = req.full_url
        return Resp((FIX / "company_tickers_sample.json").read_bytes())

    t = xbrl.load_tickers(opener)
    assert seen["ua"] == UA and seen["url"] == xbrl.TICKERS_URL and len(t) == 4


# ---- audit fixes ---------------------------------------------------------------------------------------

def two_tags(**tags):
    f = {"cik": 1, "entityName": "Synthetic", "facts": {"us-gaap": {}}}
    for tag, rows in tags.items():
        f["facts"]["us-gaap"][tag] = {"units": {"USD": rows}}
    return f


def test_revenue_takes_the_larger_tag_when_both_cover_the_same_year():
    fy = dict(start="2024-01-01")
    facts = two_tags(
        RevenueFromContractWithCustomerExcludingAssessedTax=[row("2024-12-31", 247_244, **fy)],
        Revenues=[row("2024-12-31", 371_444, accn="0000000001-25-000002", **fy)])
    v = pick(xbrl.extract(facts), "revenue", "FY")
    assert v.value == 371_444 and "tag Revenues" in v.source_ref
    assert any("247,244" in n and "larger tag Revenues" in n for n in v.notes)


def test_revenue_tag_order_still_decides_when_values_match_or_years_differ():
    fy = dict(start="2024-01-01")
    same = two_tags(RevenueFromContractWithCustomerExcludingAssessedTax=[row("2024-12-31", 100, **fy)],
                    Revenues=[row("2024-12-31", 100, **fy)])
    v = pick(xbrl.extract(same), "revenue", "FY")
    assert "ExcludingAssessedTax" in v.source_ref and v.notes == []
    newer = two_tags(RevenueFromContractWithCustomerExcludingAssessedTax=[row("2024-12-31", 100, **fy)],
                     Revenues=[row("2023-12-31", 900, start="2023-01-01", fy=2023)])
    assert "ExcludingAssessedTax" in pick(xbrl.extract(newer), "revenue", "FY").source_ref


def test_larger_wins_is_revenue_only():
    fy = dict(start="2024-01-01")
    facts = two_tags(NetIncomeLoss=[row("2024-12-31", 10, **fy)], ProfitLoss=[row("2024-12-31", 12, **fy)])
    assert pick(xbrl.extract(facts), "net_income", "FY").value == 10


def test_ltm_note_is_accurate_when_later_10q_lacks_the_tag():
    facts = two_tags(OperatingIncomeLoss=[row("2024-12-31", 50, start="2024-01-01")],
                     Assets=[row("2025-03-31", 999, form="10-Q", fp="Q1", fy=2025, filed="2025-05-01")])
    ltm = pick(xbrl.extract(facts), "operating_income", "LTM")
    assert "no later 10-Q" not in ltm.source_ref and "2025-03-31" in ltm.source_ref
    assert ltm.status == FLAG and any("later 10-Q" in n for n in ltm.notes)


def test_ltm_note_says_no_later_10q_only_when_true():
    ltm = pick(xbrl.extract(two_tags(OperatingIncomeLoss=[row("2024-12-31", 50, start="2024-01-01")])),
               "operating_income", "LTM")
    assert "no later 10-Q" in ltm.source_ref and ltm.status != FLAG


def test_ytd_without_prior_year_ytd_flags_the_fy_fallback():
    facts = two_tags(OperatingIncomeLoss=[
        row("2024-12-31", 50, start="2024-01-01"),
        row("2025-03-31", 20, start="2025-01-01", form="10-Q", fp="Q1", fy=2025, filed="2025-05-01")])
    vals = xbrl.extract(facts)
    assert not [v for v in vals if v.field == "operating_income" and v.period_type == "LTM"]
    fy = pick(vals, "operating_income", "FY")
    assert fy.status == FLAG and any("no prior-year year to date" in n for n in fy.notes)


def test_debt_with_only_noncurrent_piece_is_flagged():
    only = pick(xbrl.extract(two_tags(LongTermDebtNoncurrent=[row("2024-12-31", 500)])), "debt", "instant")
    assert only.status == FLAG and any("only noncurrent debt" in n for n in only.notes)
    both = two_tags(LongTermDebtNoncurrent=[row("2024-12-31", 500)], DebtCurrent=[row("2024-12-31", 50)])
    full = pick(xbrl.extract(both), "debt", "instant")
    assert full.value == 550 and full.status != FLAG
