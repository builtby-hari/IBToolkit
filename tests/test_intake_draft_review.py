"""Draft writer, review step, approve, the dcf draft guard and the intake CLI, all offline."""
import json
import re
import tomllib
from pathlib import Path

import pytest

from ibtoolkit import __main__ as cli_main
from ibtoolkit import dcf
from ibtoolkit.intake import cli as intake_cli
from ibtoolkit.intake import draft, review, xbrl
from ibtoolkit.intake.fields import SourcedValue
from test_intake_xbrl import FIX, UA, Resp, load

ROOT = Path(__file__).resolve().parent.parent
TODAY = "2026-11-11"


def hd_draft():
    return draft.build_draft(xbrl.extract(load("companyfacts_hd.json")), "HOME DEPOT, INC.", "HD", "354950", TODAY)


def aapl_draft():
    return draft.build_draft(xbrl.extract(load("companyfacts_aapl.json")), "Apple Inc.", "AAPL", "320193", TODAY)


def complete(text):
    """Stand in for a human: drop the TODO comments and fill NTM, [dcf] and peers from the sample case."""
    text = re.sub(r"^# TODO.*\n(#    .*\n)*", "", text, flags=re.M)
    sample = (ROOT / "cases" / "dcf_sample.toml").read_text()
    dcf_part = sample[sample.index("[dcf]"):sample.index("[[peers]]")].replace("[dcf]\n", "")
    peers = sample[sample.index("[[peers]]"):]
    ntm = ("ntm_revenue = 175000   # ASSUMPTION (test fixture number, not a forecast)\n"
           "ntm_ebitda = 26000    # ASSUMPTION (test fixture number)\n"
           "ntm_eps = 15.5        # ASSUMPTION (test fixture number)\n")
    text = text.replace("[target]\n", "[target]\n" + ntm, 1).replace("[dcf]\n", "[dcf]\n" + dcf_part, 1)
    return text + "\n" + peers


def write(tmp_path, text, name="draft.toml"):
    p = tmp_path / name
    p.write_text(text)
    return p


# ---- draft writer ----------------------------------------------------------------------------------------

def test_draft_is_valid_toml_marked_draft_with_target_numbers():
    raw = tomllib.loads(hd_draft())
    assert raw["meta"]["draft"] is True and raw["meta"]["illustrative"] is False
    t = raw["target"]
    assert t["ltm_revenue"] == 169176 and t["diluted_shares"] == 996 and t["ltm_eps"] == 14.29
    assert t["ltm_ebitda"] == 21022 + 3633
    assert t["net_debt"] == 52896 - 2085
    assert not any(k.startswith("ntm") for k in t)  # never invented


def test_draft_cites_every_number_and_lists_todos():
    text = hd_draft()
    assert text.count("#   Source:") >= 5 and "accn 0001628280-26-058715" in text
    assert "EBITDA = operating income" in text and "Built from the filing" in text
    todos = review.todo_lines(text)
    assert sum(t.startswith("TODO target.ntm_") for t in todos) == 3
    assert sum(t.startswith("TODO dcf.") for t in todos) == len(draft.DCF_TODO)
    assert any(t.startswith("TODO peers") for t in todos)
    assert "Reference only: LTM" in text  # hints come from filings, labelled as not a forecast


def test_draft_has_no_personal_details():
    text = hd_draft()
    assert "@" not in text and not re.search(r"co-authored|generated (with|by)", text, re.I)


def test_missing_da_leaves_ebitda_as_todo():
    vals = [v for v in xbrl.extract(load("companyfacts_hd.json")) if v.field != "d_and_a"]
    text = draft.build_draft(vals, "X", today=TODAY)
    assert "ltm_ebitda =" not in text and "TODO target.ltm_ebitda" in text


def test_dcf_refuses_a_draft(tmp_path, capsys):
    p = write(tmp_path, hd_draft())
    with pytest.raises(dcf.CaseError, match="DRAFT"):
        dcf.load_case(p)
    assert cli_main.main(["dcf", str(p), "--out", str(tmp_path / "x.xlsx")]) == 1
    assert "DRAFT" in capsys.readouterr().err and not (tmp_path / "x.xlsx").exists()


# ---- review ------------------------------------------------------------------------------------------------

def test_review_clean_hd_draft(tmp_path):
    rep = review.review(write(tmp_path, hd_draft()))
    assert rep.is_draft and rep.unresolved == [] and len(rep.todos) == 3 + len(draft.DCF_TODO) + 1
    out = review.format_report(rep)
    assert "revenue" in out and "169,176.0M" in out and "accn 0001628280-26-019436" in out
    assert "Flags: 0 unresolved" in out and f"TODOs: {len(rep.todos)}" in out


def test_review_flags_stale_tags_in_apple(tmp_path):
    rep = review.review(write(tmp_path, aapl_draft()))
    fields = {i.field for i in rep.unresolved}
    assert fields == {"goodwill", "interest_expense"}
    notes = " ".join(i.note for i in rep.unresolved)
    assert "period mismatch" in notes and "stale: filed" in notes
    assert "flag" in review.format_report(rep)


def mk(field, value, **kw):
    unit = {"diluted_eps": "USD/shares", "diluted_shares": "shares", "shares_outstanding": "shares"}.get(field, "USD")
    base = dict(field=field, value=value, unit=unit, period_type="instant", period_end="2026-06-30",
                source_kind="xbrl", source_ref="test", filed="2026-08-01")
    base.update(kw)
    return SourcedValue(**base)


def notes_for(values):
    return " | ".join(i.note for i in review.check_values(values))


def test_check_balance_sheet_tie():
    assert "does not tie" in notes_for([mk("total_assets", 1e9), mk("liabilities_and_equity", 1.1e9)])
    assert notes_for([mk("total_assets", 1e9), mk("liabilities_and_equity", 1.0001e9)]) == ""


def test_check_period_mismatch_and_stale_filing():
    n = notes_for([mk("total_assets", 1e9), mk("cash", 5e6, period_end="2025-12-31", filed="2025-12-01")])
    assert "period mismatch" in n and "stale: filed 2025-12-01" in n


def test_check_odd_signs_and_units():
    n = notes_for([mk("capex", -5), mk("revenue", 900, period_type="LTM"), mk("diluted_shares", 0),
                   mk("net_income", 10, period_type="LTM"), mk("diluted_eps", -1.0, period_type="LTM")])
    assert "capex is negative" in n and "filed in thousands" in n and "diluted_shares is 0" in n
    assert "opposite signs" in n


def test_check_units_in_written_target(tmp_path):
    text = hd_draft().replace("ltm_revenue = 169176", "ltm_revenue = 169176000")
    rep = review.review(write(tmp_path, text))
    assert any(i.field == "target.ltm_revenue" and "units" in i.note for i in rep.unresolved)


def test_check_edited_target_and_unsourced_manual_value(tmp_path):
    text = hd_draft().replace("ltm_revenue = 169176", "ltm_revenue = 170000")
    text = text.replace("[target]\n", "[target]\nntm_revenue = 180000\n", 1)
    rep = review.review(write(tmp_path, text))
    notes = {i.field: i.note for i in rep.unresolved}
    assert "differs from the sourced" in notes["target.ltm_revenue"]
    assert "no source comment" in notes["target.ntm_revenue"]
    assert "hand-entered (no source comment)" in review.format_report(rep)


def test_review_missing_file():
    with pytest.raises(FileNotFoundError):
        review.review("/nonexistent/draft.toml")


# ---- approve -----------------------------------------------------------------------------------------------

def test_approve_refuses_with_todos(tmp_path):
    p = write(tmp_path, hd_draft())
    ok, msg = review.approve(p)
    assert not ok and "TODO" in msg and tomllib.loads(p.read_text())["meta"]["draft"] is True


def test_approve_completed_draft_then_dcf_runs(tmp_path):
    p = write(tmp_path, complete(hd_draft()))
    assert review.review(p).todos == []
    ok, msg = review.approve(p)
    assert ok, msg
    raw = tomllib.loads(p.read_text())
    assert raw["meta"]["draft"] is False and len(raw["intake"]["values"]) > 10
    case = dcf.load_case(p)
    assert dcf.run(case)["val"]["gordon"]["price"] > 0
    assert review.approve(p)[1].endswith("already approved (draft = false)")


def test_approve_blocks_on_flags_unless_accepted(tmp_path):
    p = write(tmp_path, complete(aapl_draft()))
    ok, msg = review.approve(p)
    assert not ok and "unresolved flag" in msg and tomllib.loads(p.read_text())["meta"]["draft"] is True
    ok, msg = review.approve(p, accept_flags=True, today=TODAY)
    assert ok and "2 flagged item(s) accepted" in msg
    raw = tomllib.loads(p.read_text())
    assert raw["meta"]["draft"] is False
    by = {v["field"]: v for v in raw["intake"]["values"]}
    assert by["goodwill"]["status"] == "approved" and by["interest_expense"]["status"] == "approved"
    assert by["revenue"]["status"] == "ok"
    assert any("accepted by reviewer" in n for n in by["goodwill"]["notes"])
    assert review.review(p).unresolved == []  # accepted flags stay visible but are resolved


def test_approve_blocks_when_case_does_not_validate(tmp_path):
    text = complete(hd_draft()).replace("beta = 1.10", "beta = -1")
    ok, msg = review.approve(write(tmp_path, text))
    assert not ok and "does not validate" in msg


# ---- CLI ---------------------------------------------------------------------------------------------------

def fake_opener(seen):
    def opener(req):
        seen.append((req.full_url, req.get_header("User-agent")))
        if "company_tickers" in req.full_url:
            return Resp((FIX / "company_tickers_sample.json").read_bytes())
        assert req.full_url.endswith("CIK0000354950.json")
        return Resp((FIX / "companyfacts_hd.json").read_bytes())
    return opener


def test_cli_ticker_with_injected_opener(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    out = tmp_path / "cases" / "draft_hd_dcf.toml"
    import argparse
    p = argparse.ArgumentParser()
    intake_cli.add_parser(p.add_subparsers(dest="cmd"))
    a = p.parse_args(["intake", "--ticker", "HD", "--model", "dcf", "--out", str(out)])
    seen = []
    assert intake_cli.run(a, fake_opener(seen)) == 0
    assert [u for u, _ in seen][0].endswith("company_tickers.json") and all(ua == UA for _, ua in seen)
    assert tomllib.loads(out.read_text())["meta"]["draft"] is True
    assert "Wrote" in capsys.readouterr().out
    assert intake_cli.run(a, fake_opener([])) == 1  # will not overwrite without --force
    assert "already exists" in capsys.readouterr().err


def test_cli_facts_offline_review_and_approve(tmp_path, capsys):
    out = tmp_path / "d.toml"
    assert cli_main.main(["intake", "--ticker", "HD", "--facts", str(FIX / "companyfacts_hd.json"), "--out", str(out)]) == 0
    assert "sourced values" in capsys.readouterr().out
    assert cli_main.main(["intake", "--review", str(out)]) == 0
    assert "TODOs:" in capsys.readouterr().out
    assert cli_main.main(["intake", "--review", str(out), "--approve"]) == 1
    assert "Not approved" in capsys.readouterr().out
    out.write_text(complete(out.read_text()))
    assert cli_main.main(["intake", "--review", str(out), "--approve"]) == 0
    assert "Approved" in capsys.readouterr().out
    assert cli_main.main(["dcf", str(out), "--out", str(tmp_path / "m.xlsx")]) == 0


def test_cli_errors(tmp_path, capsys):
    assert cli_main.main(["intake"]) == 1
    assert cli_main.main(["intake", "--approve"]) == 1
    assert cli_main.main(["intake", "--review", str(tmp_path / "nope.toml")]) == 1
    assert "Error" in capsys.readouterr().err


def test_cli_needs_user_agent_for_network(monkeypatch, capsys):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert cli_main.main(["intake", "--ticker", "HD", "--out", "unused.toml"]) == 1
    assert "SEC_USER_AGENT" in capsys.readouterr().err


# ---- audit fixes ---------------------------------------------------------------------------------------

def sv(field, value, end, ptype="LTM", **kw):
    unit = "USD/shares" if field == "diluted_eps" else "USD"
    return SourcedValue(field=field, value=value, unit=unit, period_type=ptype, period_end=end,
                        source_kind="xbrl", source_ref=f"10-K accn 1 tag {field}", **kw)


def test_net_debt_and_ebitda_refuse_mismatched_dates():
    sel = {"debt": sv("debt", 5e9, "2018-12-31", "instant"), "cash": sv("cash", 1e9, "2026-03-31", "instant"),
           "operating_income": sv("operating_income", 2e9, "2013-12-31", "FY"),
           "d_and_a": sv("d_and_a", 1e9, "2026-03-31")}
    t = draft.derive_target(sel)
    assert "net_debt" not in t and "ltm_ebitda" not in t
    text = draft.build_draft(list(sel.values()) + [sv("revenue", 9e9, "2026-03-31")], "X", today=TODAY)
    assert "net_debt =" not in text and "ltm_ebitda =" not in text
    assert "TODO target.net_debt: not written, inputs are from different periods" in text
    assert "TODO target.ltm_ebitda: not written, inputs are from different periods" in text


def test_net_debt_refuses_a_stale_tag_flag_and_allows_matching_dates():
    stale = sv("debt", 5e9, "2026-03-31", "instant")
    stale.flag("tag last reported for period ending 2026-03-31, over a year before 2027-06-30; x")
    sel = {"debt": stale, "cash": sv("cash", 1e9, "2026-03-31", "instant")}
    assert "net_debt" not in draft.derive_target(sel) and "stale tag" in draft.target_gaps(sel)["net_debt"]
    ok = {"debt": sv("debt", 5e9, "2026-03-31", "instant"), "cash": sv("cash", 1e9, "2026-03-31", "instant")}
    assert draft.derive_target(ok)["net_debt"] == 4000


def test_cli_pdf_drafts_the_same_way(tmp_path, capsys):
    pytest.importorskip("pdfplumber")
    pdf_file = FIX / "pdf" / "hd_10k_fy2025_statements.pdf"
    out = tmp_path / "p.toml"
    assert cli_main.main(["intake", "--pdf", str(pdf_file), "--ticker", "HD", "--out", str(out)]) == 0
    assert "sourced values" in capsys.readouterr().out
    text = out.read_text()
    assert tomllib.loads(text)["meta"]["draft"] is True
    assert "hd_10k_fy2025_statements.pdf p." in text and "TODO target.ntm_revenue" in text
    assert cli_main.main(["intake", "--review", str(out)]) == 0
    assert cli_main.main(["intake", "--pdf", str(pdf_file), "--out", str(out)]) == 1  # no overwrite
    assert "already exists" in capsys.readouterr().err


def test_cli_pdf_missing_file_is_a_clean_error(tmp_path, capsys):
    assert cli_main.main(["intake", "--pdf", str(tmp_path / "no.pdf"), "--out", str(tmp_path / "x.toml")]) == 1
    assert "PDF not found" in capsys.readouterr().err
