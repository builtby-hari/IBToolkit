"""Shared Excel writer for banker-style workbooks.

Conventions: blue font for hard-coded inputs, black for formulas, green for direct links to
another sheet, purple for direct links on the same sheet, gray italic for static values computed
outside Excel. Every calculated cell is a live formula.
"""
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.workbook.defined_name import DefinedName

USD = '$#,##0_);($#,##0);"-"_)'
PCT = '0.0%_);(0.0%);"-"_)'
MULT = '0.0"x"'
MULT2 = '0.00"x"'
YEAR = '"Year "0'

BLUE = "0000FF"
BLACK = "000000"
GRAY = "595959"
GREEN = "008000"
PURPLE = "800080"
_BASE_FILL = PatternFill("solid", fgColor="BDD7EE")
_LINK = re.compile(r"=(?:(?P<sheet>\w+)!)?\$?[A-Z]{1,3}\$?\d+|=(?P<name>[A-Za-z_]\w*)")
_HEAD_FILL = PatternFill("solid", fgColor="1F3864")
_SEC_FILL = PatternFill("solid", fgColor="D9E1F2")
_TOP = Border(top=Side(style="thin"))
_GOOD = PatternFill("solid", bgColor="C6EFCE", fgColor="C6EFCE")
_BAD = PatternFill("solid", bgColor="FFC7CE", fgColor="FFC7CE")
OK_TEXT = "All Checks OK"


class Book:
    def __init__(self):
        self.wb = Workbook()
        self.wb.remove(self.wb.active)

    def sheet(self, name, title, subtitle="", widths=None):
        ws = self.wb.create_sheet(name)
        ws["A1"] = title
        ws["A1"].font = Font(bold=True, size=14, color="1F3864")
        if subtitle:
            ws["A2"] = subtitle
            ws["A2"].font = Font(italic=True, color=GRAY)
        ws.sheet_view.showGridLines = False
        for col, w in (widths or {"A": 42}).items():
            ws.column_dimensions[col].width = w
        return ws

    def header(self, ws, row, labels, fmt=None):
        """Header row. Numeric labels are year indexes, shown with the YEAR format."""
        for i, lab in enumerate(labels, start=1):
            c = ws.cell(row=row, column=i, value=lab)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = _HEAD_FILL
            c.alignment = Alignment(horizontal="left" if i == 1 else "right")
            if isinstance(lab, (int, float)):
                c.number_format = fmt or YEAR

    def section(self, ws, row, label, ncols):
        for i in range(1, ncols + 1):
            ws.cell(row=row, column=i).fill = _SEC_FILL
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)

    def label(self, ws, ref, text, bold=False, indent=0):
        ws[ref] = text
        ws[ref].font = Font(bold=bold)
        ws[ref].alignment = Alignment(indent=indent)

    def inp(self, ws, ref, value, fmt, name=None):
        """Hard-coded input: blue font."""
        if isinstance(value, str) and value.startswith("="):
            raise ValueError(f"Input {ref} must not be a formula")
        return self._put(ws, ref, value, fmt, BLUE, name)

    def calc(self, ws, ref, formula, fmt, name=None, bold=False, total=False):
        """Calculated cell: must be a live formula, black font."""
        if not (isinstance(formula, str) and formula.startswith("=")):
            raise ValueError(f"Calculated cell {ref} must be a formula, got {formula!r}")
        c = self._put(ws, ref, formula, fmt, BLACK, name, bold)
        if total:
            c.border = _TOP
        return c

    def static(self, ws, ref, value, fmt):
        """Value computed outside Excel (for example Python sensitivities): gray italic."""
        c = self._put(ws, ref, value, fmt, GRAY)
        c.font = Font(color=GRAY, italic=True)
        return c

    def _put(self, ws, ref, value, fmt, color, name=None, bold=False):
        c = ws[ref]
        c.value = value
        c.number_format = fmt
        c.font = Font(color=color, bold=bold)
        c.alignment = Alignment(horizontal="right")
        if name:
            self.name(ws, ref, name)
        return c

    def axis(self, ws, refs, centre, step, fmt, hi=None):
        """Live five-point sensitivity axis: refs[2] is the base case, each cell out adds or takes one
        step from its neighbour. Floors at 0; caps at hi when given."""
        self.calc(ws, refs[2], f"={centre}", fmt)
        for i in (1, 0):
            self.calc(ws, refs[i], f"=MAX(0,{refs[i + 1]}-{step})", fmt)
        for i in (3, 4):
            up = f"{refs[i - 1]}+{step}"
            self.calc(ws, refs[i], f"=MIN({hi},{up})" if hi is not None else f"={up}", fmt)

    def base(self, ws, ref):
        """Mark a sensitivity grid's base-case centre cell: medium-blue fill, bold."""
        c = ws[ref]
        c.fill = _BASE_FILL
        c.font = Font(color=c.font.color, bold=True, italic=c.font.i)

    def color_key(self, ws, r, static=False):
        """Color key block starting at row r. Returns the first free row after it."""
        self.header(ws, r, ["Color Key", "", ""])
        keys = [("Blue: hard-coded input", Font(color=BLUE)), ("Black: formula", Font()),
                ("Green: link to another sheet", Font(color=GREEN)),
                ("Purple: link on the same sheet", Font(color=PURPLE))]
        if static:
            keys.append(("Gray italic: static value from the Python engine", Font(color=GRAY, italic=True)))
        for i, (text, font) in enumerate(keys, start=1):
            ws[f"A{r + i}"] = text
            ws[f"A{r + i}"].font = font
        return r + len(keys) + 2

    def _color_links(self):
        """Recolor formulas that are a bare link (=A1, =Sheet!A1 or =Name): green when the target is on
        another sheet, purple when it is on the same sheet. Calculations stay black."""
        homes = {n: d.attr_text.split("!")[0] for n, d in self.wb.defined_names.items()}
        for ws in self.wb:
            for row in ws.iter_rows():
                for c in row:
                    if not (isinstance(c.value, str) and c.font.color is not None
                            and str(c.font.color.rgb).endswith(BLACK)):
                        continue
                    m = _LINK.fullmatch(c.value)
                    if not m or (m["name"] and m["name"] not in homes):
                        continue
                    home = homes[m["name"]] if m["name"] else (m["sheet"] or ws.title)
                    c.font = Font(color=PURPLE if home == ws.title else GREEN, bold=c.font.b)

    def checks_sheet(self, checks):
        """Add the Checks sheet. checks is a list of (label, violation): violation is a formula
        body, without the equals sign, that is TRUE when the check fails. Each flag is 0 when OK
        and 1 when it fails. Compare numbers against the named tolerance Check_Tol, which this adds to
        the Inputs sheet (so build Inputs first)."""
        ws = self.sheet("Checks", "Model Integrity Checks",
                        "Each flag is a live formula: 0 when the check passes, 1 when it fails.",
                        {"A": 72, "B": 16})
        self.header(ws, 4, ["Check", "Flag (0 = OK)"])
        for i, (label, bad) in enumerate(checks):
            self.label(ws, f"A{5 + i}", label, indent=1)
            self.calc(ws, f"B{5 + i}", f"=IF({bad},1,0)", "0")
        last = 4 + len(checks)
        self.label(ws, f"A{last + 1}", "Total Errors", bold=True)
        self.calc(ws, f"B{last + 1}", f"=SUM(B5:B{last})", "0", name="Checks_Total", bold=True, total=True)
        inp = self.wb["Inputs"]  # the tolerance is an input, so it lives on Inputs
        r = inp.max_row + 2
        self.label(inp, f"A{r}", "Check Tolerance (Absolute, Same Units as the Model)")
        self.inp(inp, f"B{r}", 0.000001, "0.000000", name="Check_Tol")
        rng = f"B5:B{last + 1}"
        ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["0"], fill=_BAD))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=["0"], fill=_GOOD))
        ws.freeze_panes = "B5"
        return ws

    def master_check(self, ws, ref="B5"):
        """Summary cell: OK text or the error count, green or red by conditional formatting."""
        self.label(ws, f"A{ref[1:]}", "Model Checks", bold=True)
        self.calc(ws, ref, f'=IF(Checks_Total=0,"{OK_TEXT}",CONCATENATE(Checks_Total," Check Errors"))',
                  "@", bold=True)
        ws.conditional_formatting.add(ref, FormulaRule(formula=[f'${ref[0]}${ref[1:]}="{OK_TEXT}"'], fill=_GOOD))
        ws.conditional_formatting.add(ref, FormulaRule(formula=[f'${ref[0]}${ref[1:]}<>"{OK_TEXT}"'], fill=_BAD))

    def name(self, ws, ref, name):
        col = "".join(ch for ch in ref if ch.isalpha())
        row = "".join(ch for ch in ref if ch.isdigit())
        self.wb.defined_names[name] = DefinedName(name, attr_text=f"{ws.title}!${col}${row}")

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._color_links()
        self.wb.save(path)
        return path
