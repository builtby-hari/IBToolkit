import csv

from ibtoolkit.__main__ import main


def test_csv_export_writes_every_sheet_with_values(tmp_path):
    out = tmp_path / "lbo.xlsx"
    assert main(["lbo", "cases/lbo_sample.toml", "--out", str(out), "--csv", str(tmp_path / "csv")]) == 0
    files = {p.name for p in (tmp_path / "csv").iterdir()}
    assert {"Summary.csv", "Model.csv", "Checks.csv"} <= files
    rows = list(csv.reader((tmp_path / "csv" / "Summary.csv").open()))
    flat = [c for r in rows for c in r]
    assert "All Checks OK" in flat
    assert not any(c.startswith("=") for c in flat)  # formulas evaluated, not copied
