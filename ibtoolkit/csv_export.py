"""Write every sheet of a built workbook to CSV, with formulas evaluated to values.

For readers without a spreadsheet app. Charts and formatting are not carried over.
"""
import csv
from pathlib import Path

from openpyxl import load_workbook

from .xl_eval import Evaluator


def export(xlsx, out_dir):
    """One CSV per sheet in out_dir. Returns the paths written."""
    wb = load_workbook(xlsx)
    ev = Evaluator(wb)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for ws in wb.worksheets:
        path = out / f"{ws.title}.csv"
        with path.open("w", newline="") as fh:
            w = csv.writer(fh)
            for row in ws.iter_rows():
                vals = ["" if c.value is None else ev.cell(ws.title, c.coordinate) for c in row]
                w.writerow([round(v, 6) if isinstance(v, float) else v for v in vals])
        paths.append(path)
    return paths
