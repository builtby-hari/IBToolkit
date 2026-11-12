"""Read the three financial statements out of a 10-K or 10-Q PDF into SourcedValue.

How it works:
1. Find the income statement, balance sheet and cash flow statement pages by their headings. A
   heading must be a whole line near the top of a page, so the table of contents (headings followed
   by page numbers), MD&A prose and notes are skipped.
2. Read the column headers (years, dates, "Three Months Ended"...) and the scale line
   ("in millions", "in thousands") and pick the latest period column.
3. Map each row label to a canonical field with a synonym table.
4. Anything odd is still returned but flagged with the reason. A value that is not printed on the
   page is never made up.

Needs pdfplumber (see requirements-intake.txt). It is imported lazily so the rest of the toolkit
works without it.
"""
import os
import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta

from .fields import FIELDS, FY, INSTANT, PDF, QTR, YTD, SourcedValue

INCOME, BALANCE, CASHFLOW = "income", "balance", "cashflow"

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]
MONTH_RE = "|".join(m[:3] + r"[a-z]*" for m in MONTHS)

# Words that can appear in a column header or scale line. A line made only of these (and numbers)
# is header text, not a data row.
HEADER_WORDS = set("""fiscal year years ended three six nine twelve months month weeks week quarter
quarters in millions thousands billions except per share shares data dollars amounts unaudited audited
and of to date ytd restated note notes continued""".split()) | set(MONTHS) | {m[:3] for m in MONTHS} | {"sept"}

SCALES = {"millions": 1e6, "thousands": 1e3, "billions": 1e9}


class PdfIntakeError(RuntimeError):
    pass


def _pdfplumber():
    """Import pdfplumber only when a PDF is actually read."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise PdfIntakeError("PDF intake needs pdfplumber. Install it with: "
                             "pip install -r requirements-intake.txt") from exc
    return pdfplumber


def load_pages(pdf_path):
    """Return the text of each page (list of str)."""
    with _pdfplumber().open(pdf_path) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


# ---------------------------------------------------------------- rows

_SUPERSCRIPTS = str.maketrans("", "", "¹²³⁰⁴⁵⁶⁷⁸⁹*†‡")
_NUM = re.compile(r"^(\(\s*\d[\d,]*(\.\d+)?\s*\)|-?\d[\d,]*(\.\d+)?)$")
_DASH = re.compile(r"^[—–\-]+$|^\(\s*[—–\-]+\s*\)$")
_FOOTNOTE = re.compile(r"^\(\d\)$")


@dataclass
class Row:
    label: str
    cells: list              # float, or None for a dash (nil) cell
    page: int                # 1-based pdf page
    section: str = ""        # last heading-only line above, lowercase
    context: str = ""        # label-only lines directly above, joined
    short: bool = False      # fewer values than columns
    raw: str = ""


def _clean_line(line):
    line = line.translate(_SUPERSCRIPTS).replace("$", " ").replace("%", " ")
    line = re.sub(r"\(\s+", "(", line)
    line = re.sub(r"\s+\)", ")", line)
    return re.sub(r"\s+", " ", line).strip()


def _cell(token):
    """Number from a token, None for a dash, 'x' if it is not a cell."""
    if _DASH.match(token):
        return None
    if not _NUM.match(token):
        return "x"
    neg = token.startswith("(") or token.startswith("-")
    value = float(token.strip("()-").replace(",", "").strip())
    return -value if neg else value


def split_row(line, ncols=None):
    """Split a cleaned line into (label, cells, short). Cells are taken from the right.

    With ncols known, only that many cells are taken and anything numeric left in the label is
    kept there; footnote markers like (1) just left of the cells are dropped.
    """
    tokens = line.split(" ")
    cells = []
    while tokens:
        c = _cell(tokens[-1])
        if c == "x" or (ncols is not None and len(cells) >= ncols):
            break
        cells.append(c)
        tokens.pop()
    cells.reverse()
    short = ncols is not None and 0 < len(cells) < ncols
    while tokens and _FOOTNOTE.match(tokens[-1]):
        tokens.pop()
    return " ".join(tokens).strip(" :"), cells, short


def merge_wrapped(lines):
    """Join a label-only line with the next line when the next starts lowercase (a wrapped label)."""
    out = []
    for line in lines:
        if out and line[:1].islower() and not split_row(out[-1])[1]:
            out[-1] = out[-1] + " " + line
        else:
            out.append(line)
    return out


def norm(label):
    """Lowercase label with typographic quotes and footnote noise removed."""
    label = label.lower().replace("’", "'").replace("‘", "'")
    label = re.sub(r"\s*\(\d\)\s*$", "", label)
    return re.sub(r"\s+", " ", label).strip(" :,")


# ---------------------------------------------------------------- finding statements

def _strip_tail(line):
    """Drop trailing parentheticals and unaudited/continued from a heading candidate."""
    line = norm(line)
    for _ in range(3):
        line = re.sub(r"\s*(\([^)]*\)|-\s*unaudited|unaudited|continued)\s*$", "", line).strip(" -—,")
    return line


def heading_kind(line):
    """INCOME, BALANCE, CASHFLOW or None for a page-heading line."""
    low = norm(line)
    stripped = line.strip()
    # prose is not a heading: it ends with a colon or period, or starts mid-sentence in lowercase
    if stripped.endswith((":", ".")) or stripped[:1].islower():
        return None
    if len(low.split()) > 14 or re.search(r"\d\s*$", low) or "parenthetical" in low:
        return None
    tail = _strip_tail(line)
    if re.search(r"(balance sheets?|statements? of (financial (position|condition)|condition))$", tail):
        return BALANCE
    if re.search(r"(statements? of cash flows?|cash flows? statements?)$", tail):
        return CASHFLOW
    if re.search(r"(statements? of [a-z ]*(earnings|operations|income|loss|profit)|income statements?)$", tail):
        if "comprehensive" in tail and not re.search(r"(operations|earnings|income|loss) and comprehensive", tail):
            return None
        return INCOME
    return None


def _top_lines(text, n=12):
    return [ln.strip() for ln in text.splitlines() if ln.strip()][:n]


def _count_rows(text):
    return sum(1 for ln in text.splitlines() if split_row(_clean_line(ln))[1] and split_row(_clean_line(ln))[0])


def find_statement_pages(pages):
    """{kind: [0-based page indexes]}: first real statement of each kind plus its continuation pages."""
    found = {}
    for i, text in enumerate(pages):
        kinds = {heading_kind(ln) for ln in _top_lines(text)} - {None}
        if len(kinds) != 1 or _count_rows(text) < 6:
            continue          # no heading, a table of contents (several headings), or not a data page
        kind = kinds.pop()
        if kind in found:
            continue
        found[kind] = [i]
        j = i + 1
        while j < len(pages) and {heading_kind(ln) for ln in _top_lines(pages[j])} == {kind}:
            found[kind].append(j)
            j += 1
    return found


# ---------------------------------------------------------------- column headers

def detect_scale(lines):
    """(multiplier, found) from lines like 'in millions, except per share data'."""
    text = " ".join(lines).lower()
    m = re.search(r"(?:in|dollars in|amounts in|expressed in)\s+(millions|thousands|billions)", text)
    if m:
        return SCALES[m.group(1)], True
    if re.search(r"\$?\s*000'?s|\(000\)", text):
        return 1e3, True
    return 1.0, False


def _is_header_line(line):
    if not line.strip():
        return False
    words = re.findall(r"[a-z]+", line.lower())
    return all(w in HEADER_WORDS for w in words)


@dataclass
class Column:
    year: int
    end: str = ""         # ISO date, blank if the header did not say
    ptype: str = FY
    months: int = 0       # length of the period when the header says so


def _iso(year, month_word, day):
    try:
        month = next(i for i, m in enumerate(MONTHS, 1) if m.startswith(month_word.lower()[:3]))
        return date(year, month, day).isoformat()
    except (ValueError, StopIteration):
        return ""


_PERIOD_MARKERS = [
    (QTR, 3, r"three months|13 weeks|quarter"),
    (YTD, 6, r"six months|26 weeks"),
    (YTD, 9, r"nine months|39 weeks"),
    (YTD, 0, r"year[- ]to[- ]date"),
    (FY, 12, r"twelve months|52 weeks|53 weeks|years? ended|fiscal"),
]


def parse_columns(header_lines, kind):
    """Columns (one per year token) with period end and type, plus a list of problems."""
    text = " ".join(header_lines)
    low = text.lower()
    years = [int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", text)]
    problems = []
    md = [(m.group(1), int(m.group(2))) for m in re.finditer(rf"\b({MONTH_RE})\.?\s+(\d{{1,2}})\b", text, re.I)]
    cols = [Column(y) for y in years]
    if md:
        pairs = md if len(md) == len(years) else [md[0]] * len(years)
        for c, (mon, day) in zip(cols, pairs):
            c.end = _iso(c.year, mon, day)
    if kind == BALANCE:
        for c in cols:
            c.ptype = INSTANT
        return cols, problems
    # period markers in the order they appear
    found = []
    for ptype, months, pat in _PERIOD_MARKERS:
        for m in re.finditer(pat, low):
            found.append((m.start(), ptype, months))
    found.sort()
    groups = []
    for _, ptype, months in found:
        if not groups or groups[-1][:2] != (ptype, months):
            groups.append((ptype, months))
    if not groups:
        problems.append("column header does not say what period the columns cover; assumed fiscal year")
        groups = [(FY, 12)]
    if len(cols) % len(groups) != 0:
        problems.append("could not match period labels to columns; used the first label for all")
        groups = groups[:1]
    size = len(cols) // len(groups) if cols else 0
    for i, c in enumerate(cols):
        c.ptype, c.months = groups[i // size] if size else groups[0]
    return cols, problems


def _period_start(end, months):
    """First day of the period when the period end is a month end; blank for 52/53-week years."""
    if not end or not months:
        return ""
    d = date.fromisoformat(end)
    if d.day != monthrange(d.year, d.month)[1]:
        return ""
    first = d + timedelta(days=1)
    month = first.month - months
    year = first.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, 1).isoformat()


def latest_columns(cols):
    """Index of the newest column of each period type (columns can run oldest first)."""
    best = {}
    for i, c in enumerate(cols):
        key = (c.year, c.end)
        if c.ptype not in best or key > (cols[best[c.ptype]].year, cols[best[c.ptype]].end):
            best[c.ptype] = i
    return best


# ---------------------------------------------------------------- reading a statement

@dataclass
class Statement:
    kind: str
    pages: list                      # 1-based pdf page numbers
    columns: list = field(default_factory=list)
    scale: float = 1.0
    scale_found: bool = False
    share_scale_raw: bool = False    # header says "except share data": share counts are not scaled
    rows: list = field(default_factory=list)
    problems: list = field(default_factory=list)


def read_statement(pages, kind, idxs):
    """Parse the header and data rows of one statement from its page(s)."""
    st = Statement(kind, [i + 1 for i in idxs])
    header_done = False
    for i in idxs:
        lines = merge_wrapped([ln for ln in (_clean_line(x) for x in pages[i].splitlines()) if ln])
        start = next((k for k, ln in enumerate(lines[:14]) if heading_kind(ln) == kind), 0) + 1
        k = start
        header = []
        while k < len(lines) and _is_header_line(lines[k]):
            header.append(lines[k])
            k += 1
        if not header_done:
            st.columns, probs = parse_columns(header, kind)
            st.problems += probs
            st.scale, st.scale_found = detect_scale(header or lines[:14])
            st.share_scale_raw = bool(re.search(r"except share", " ".join(header).lower()))
            header_done = True
        ncols = len(st.columns) or None
        section, context = "", []
        for ln in lines[k:]:
            if re.match(r"(see|the) accompanying notes", ln.lower()):
                break
            label, cells, short = split_row(ln, ncols)
            if not cells:
                section = norm(label) or section
                context.append(label)
                continue
            st.rows.append(Row(label, cells, i + 1, section, " ".join(context[-3:]), short, ln))
            context = []
    if not st.columns:
        st.problems.append("no column header with years found")
    return st


# ---------------------------------------------------------------- label to field

def _fm(*patterns):
    return [re.compile(p) for p in patterns]


# Per field: the statement(s) it is read from (in order of preference), then clean label patterns
# (best first), then partial patterns that match but get flagged. Patterns are full matches on norm(label).
RULES = {
    "revenue": dict(stmts=[INCOME], clean=_fm(
        r"net sales", r"total net sales", r"total (net )?revenues?(, net)?", r"net revenues?", r"revenues?(, net)?",
        r"sales", r"total net revenues?"), partial=[]),
    "operating_income": dict(stmts=[INCOME], clean=_fm(
        r"operating (income|profit|earnings)( \(loss\))?", r"operating \(loss\) (income|profit)",
        r"(income|profit)( \(loss\))? from operations", r"\(loss\) income from operations"), partial=[]),
    "d_and_a": dict(stmts=[CASHFLOW, INCOME], clean=_fm(
        r"depreciation(,| and| &) amortization( and accretion)?", r"depreciation, depletion and amortization"),
        partial=_fm(r"depreciation,? (and )?amortization.*", r"depreciation")),
    "interest_expense": dict(stmts=[INCOME], clean=_fm(
        r"interest expense( \(income\))?", r"total interest expense", r"interest and debt expense"),
        partial=_fm(r"interest expense,? .*", r"interest expense and .*")),
    "income_tax": dict(stmts=[INCOME], clean=_fm(
        r"(provision|benefit)[a-z ()]*income taxes?", r"\(?benefit\)? [a-z ()]*income taxes?",
        r"income tax(es)? (expense|provision)( \(benefit\))?", r"income tax (benefit|\(benefit\) expense)",
        r"income taxes?"), partial=[]),
    "net_income": dict(stmts=[INCOME], clean=[], partial=[]),      # handled in pick_net_income
    "diluted_eps": dict(stmts=[INCOME], clean=[], partial=[]),     # handled in diluted_kind
    "diluted_shares": dict(stmts=[INCOME], clean=[], partial=[]),
    "capex": dict(stmts=[CASHFLOW], clean=_fm(
        r"capital expenditures?", r"purchases? of property(,| and)?( plant,?)?( and)? equipment",
        r"additions to property(,| and)?( plant,?)?( and)? equipment", r"payments for property(,| and)?( plant,?)?( and)? equipment",
        r"acquisitions? of property(,| and)?( plant,?)?( and)? equipment"),
        partial=_fm(r"(capital expenditures?|purchases? of property|additions to property|payments for property"
                    r"|purchases of premises).*")),
    "operating_cash_flow": dict(stmts=[CASHFLOW], clean=_fm(
        r"(net )?cash( flows?)?( provided by| from| used in| \(used in\)| provided by \(used in\)| \(used in\) provided by"
        r"| from \(used in\)| generated by)[ /,]*(\(used in\)/provided by |provided by/\(used in\) )?(operating activities|operations)"),
        partial=_fm(r"(net )?cash[a-z ()/,]*operating activities[a-z ,]*")),
    "cash": dict(stmts=[BALANCE], clean=_fm(r"cash and cash equivalents", r"cash and equivalents", r"cash & cash equivalents",
                                            r"cash"),
                 partial=_fm(r"cash and cash equivalents,? .*", r"cash and due from banks.*",
                             r"cash, cash equivalents.*")),
    "current_assets": dict(stmts=[BALANCE], clean=_fm(r"total current assets"), partial=[]),
    "current_liabilities": dict(stmts=[BALANCE], clean=_fm(r"total current liabilities"), partial=[]),
    "total_assets": dict(stmts=[BALANCE], clean=_fm(r"total assets"), partial=[]),
    "liabilities_and_equity": dict(stmts=[BALANCE], clean=_fm(
        r"total liabilities(,)? (redeemable [a-z ]+, )?(and|&) (stockholders|shareholders|shareowners)'?s?'? ?(equity|deficit)( \(deficit\))?",
        r"total liabilities and equity"), partial=[]),
    "total_equity": dict(stmts=[BALANCE], clean=_fm(
        r"total (stockholders|shareholders|shareowners|stockholder|shareholder)'?s?'? ?(equity|deficit)( \(deficit\))?",
        r"total (stockholders|shareholders)'? (equity )?\(deficit\)",
        r"total [a-z.,& ]*(stockholders|shareholders)'? equity attributable to [a-z.,& ]*"),
        partial=_fm(r"total equity( \(deficit\))?", r"total (stockholders|shareholders)'? equity and .*")),
    "goodwill": dict(stmts=[BALANCE], clean=_fm(r"goodwill(, net)?"), partial=[]),
    "intangibles": dict(stmts=[BALANCE], clean=_fm(
        r"(other |identifiable |acquired )?intangible assets?(, net( of (accumulated )?amortization)?| other than goodwill)?",
        r"(other )?intangibles?,? net"), partial=[]),
}
RULES["debt"] = dict(stmts=[BALANCE], clean=_fm(r"total debt"), partial=[])  # plus the sum in find_debt
RULES["shares_outstanding"] = dict(stmts=[BALANCE], clean=[], partial=[])


def _rule_match(field_name, label):
    """(priority, is_clean) for a label, or None. Lower priority number is better."""
    rule = RULES[field_name]
    low = norm(label)
    for i, rx in enumerate(rule["clean"]):
        if rx.fullmatch(low):
            return i, True
    for i, rx in enumerate(rule["partial"]):
        if rx.fullmatch(low):
            return len(rule["clean"]) + i, False
    return None


def _diluted_kind(row):
    """'eps', 'shares' or None for a row that is about diluted figures."""
    low = norm(row.label)
    if "diluted" not in low and low not in ("diluted",):
        return None
    if "weighted" in low or (re.search(r"\bshares\b", low) and "per share" not in low):
        return "shares"
    if "per" in low and "share" in low or "eps" in low:
        return "eps"
    if low == "diluted":                       # bare 'Diluted': the heading above says which
        sec = row.section
        if "weighted" in sec or ("share" in sec and "per share" not in sec):
            return "shares"
        if "per share" in sec or "per common share" in sec:
            return "eps"
    return None


def _attributable(low):
    return bool(re.fullmatch(r"net (income|earnings)( \(loss\))? (attributable to|available to) [a-z .,&'()-]+", low)) \
        and not re.search(r"non-?controlling|redeemable|preferred", low)


def _plain_net_income(low):
    return bool(re.fullmatch(r"net (income|earnings|loss)( \(loss\))?|net \(loss\) (income|earnings)", low))


# ---------------------------------------------------------------- building values

def _value(row_cell, scale_kind, st, note_list):
    """Scale a printed cell to raw units."""
    if row_cell is None:
        note_list.append("printed as a dash (nil); value is 0")
        return 0.0
    if scale_kind == "usd":
        return row_cell * st.scale
    if scale_kind == "shares":
        return row_cell * (1.0 if st.share_scale_raw else st.scale)
    return row_cell


def _basics(st):
    """Flags that apply to every value from a statement."""
    notes = list(st.problems)
    if not st.scale_found:
        notes.append("no 'in millions/thousands' scale line found; values taken as whole dollars")
    return notes


class _Builder:
    """Turns the parsed statements into SourcedValue objects."""

    def __init__(self, file_name, statements, form):
        self.file = file_name
        self.st = statements
        self.form = form
        self.out = []
        self.bs_date = self._latest_bs_date()

    def _latest_bs_date(self):
        st = self.st.get(BALANCE)
        if st and st.columns:
            dates = [c.end for c in st.columns if c.end]
            return max(dates) if dates else ""
        return ""

    def _ends(self, st, col, idx):
        """(period end, flags, info notes). Year-only headers borrow the balance sheet date when it fits."""
        if col.end:
            return col.end, [], []
        if self.bs_date and idx == latest_columns(st.columns).get(col.ptype) \
                and int(self.bs_date[:4]) in (col.year, col.year + 1):
            return self.bs_date, [], [f"period end {self.bs_date} taken from the balance sheet date (header gives only the year)"]
        return "", ["period end not on the page (header gives only the year)"], []

    def add(self, name, st, row, col_idx, value, scale_kind, extra=(), flags=(), ref_label=None):
        col = st.columns[col_idx] if st.columns else Column(0, "", INSTANT if st.kind == BALANCE else FY)
        end, end_flags, end_info = self._ends(st, col, col_idx) if st.columns else ("", ["no column header found"], [])
        notes = _basics(st) + end_flags
        cell = row.cells[col_idx] if col_idx < len(row.cells) else None
        sv_value = _value(cell, scale_kind, st, notes) if value is None else value
        ref = f"{self.file} p.{row.page}, line '{ref_label or row.label}'"
        ptype = col.ptype if st.columns else FY
        sv = SourcedValue(
            field=name, value=sv_value, unit=FIELDS[name][0], period_type=ptype, period_end=end,
            source_kind=PDF, source_ref=ref, form=self.form,
            period_start=_period_start(end, col.months) if ptype != INSTANT else "")
        if row.short:
            flags = list(flags) + ["row has fewer values than columns; assumed the first value is the latest period"]
        for n in notes + list(flags):
            sv.flag(n)
        sv.notes.extend(end_info)
        sv.notes.extend(extra)
        self.out.append(sv)
        return sv

    def _col_indexes(self, st, row):
        """Columns to emit for a row: the newest of each period type, limited to what the row has."""
        if not st.columns:
            return [0]
        idxs = sorted(latest_columns(st.columns).values())
        if row.short:
            return [0]
        return [i for i in idxs if i < len(row.cells)] or [0]

    def emit(self, name, st, row, scale_kind, flags=(), extra=(), negate_abs=False, ref_label=None):
        for idx in self._col_indexes(st, row):
            cell = row.cells[idx] if idx < len(row.cells) else None
            ex = list(extra)
            value = None
            if negate_abs and cell is not None:
                value = abs(cell) * (st.scale if scale_kind == "usd" else 1.0)
                if cell < 0:
                    ex.append("printed in parentheses (an outflow or expense); stored as a positive number")
            self.add(name, st, row, idx, value, scale_kind, ex, flags, ref_label)

    # ---- per field helpers
    def run(self):
        for name in FIELDS:
            getattr(self, "_" + name, self._generic)(name)
        self._eps_check()
        return self.out

    def _generic(self, name):
        rule = RULES[name]
        for kind in rule["stmts"]:
            st = self.st.get(kind)
            if not st:
                continue
            cands = []
            for row in st.rows:
                m = _rule_match(name, row.label)
                if m and not re.search(r"included in|non-?cash|accrued|unpaid|supplemental|discontinued", norm(row.label)):
                    cands.append((m[0], m[1], row))
            if not cands:
                continue
            cands.sort(key=lambda c: c[0])
            prio, clean, row = cands[0]
            flags, extra = [], []
            if not clean:
                flags.append(f"label '{row.label}' only partly matches {name}; check the definition")
            ties = [c for c in cands[1:] if c[0] == prio and c[2].cells[:1] != row.cells[:1]]
            if ties:
                flags.append("more than one line matches with different values: "
                             + "; ".join(f"'{c[2].label}' {c[2].cells[0]}" for c in ties))
            if kind != rule["stmts"][0]:
                flags.append(f"not found on the {rule['stmts'][0]} statement; read from the {kind} statement")
            if re.search(r"excluding|excludes|net of", norm(row.label)):
                flags.append(f"label '{row.label}' has qualifiers; may not be the full figure")
            if name == "d_and_a" and "impairment" in norm(row.label):
                flags.append("label includes impairment")
            absval = name in ("capex", "interest_expense")
            self.emit(name, st, row, "usd", flags, extra, negate_abs=absval)
            return

    def _net_income(self, name):
        st = self.st.get(INCOME)
        if not st:
            return
        attrib = [r for r in st.rows if _attributable(norm(r.label))]
        plain = [r for r in st.rows if _plain_net_income(norm(r.label))]
        row = (attrib or plain or [None])[0]
        if row is None:
            return
        flags, extra = [], []
        if not attrib and any(re.search(r"non-?controlling", norm(r.label)) for r in st.rows):
            flags.append("statement shows noncontrolling interests but no 'attributable to' line; consolidated net income used")
        if attrib and plain and plain[0].cells[:1] != attrib[0].cells[:1]:
            extra.append(f"consolidated net income line '{plain[0].label}' is {plain[0].cells[0]:,.0f} as printed; "
                         "the attributable line was used")
        self.emit(name, st, row, "usd", flags, extra)

    def _diluted(self, name, kind):
        st = self.st.get(INCOME)
        if not st:
            return
        rows = [r for r in st.rows if _diluted_kind(r) == kind]
        if not rows:
            return
        flags = []
        if len(rows) > 1 and any(r.cells[:1] != rows[0].cells[:1] for r in rows[1:]):
            flags.append("more than one diluted line with different values; first used")
        if kind == "shares" and st.share_scale_raw:
            flags.append("header says 'except share data': share count taken as printed, not scaled; confirm")
        self.emit(name, st, rows[0], "eps" if kind == "eps" else "shares", flags)

    def _diluted_eps(self, name):
        self._diluted(name, "eps")

    def _diluted_shares(self, name):
        self._diluted(name, "shares")

    def _eps_check(self):
        """Net income / diluted shares should be close to diluted EPS; if not, units may be off."""
        got = {}
        for v in self.out:
            if v.period_type in (FY, QTR, YTD):
                got.setdefault((v.period_type, v.period_end), {})[v.field] = v
        for vals in got.values():
            ni, sh, eps = vals.get("net_income"), vals.get("diluted_shares"), vals.get("diluted_eps")
            if ni and sh and eps and sh.value and eps.value:
                implied = ni.value / sh.value
                if abs(implied - eps.value) > 0.05 * abs(eps.value) + 0.02:
                    sh.flag(f"net income / diluted shares = {implied:.2f} but diluted EPS is {eps.value:.2f}; "
                            "check units or the period of the share count")

    def _debt(self, name):
        st = self.st.get(BALANCE)
        if not st:
            return
        total = next((r for r in st.rows if _rule_match("debt", r.label)), None)
        if total:
            self.emit(name, st, total, "usd")
            return
        parts = []
        for row in st.rows:
            low = norm(row.label)
            if not re.search(r"debt|borrowings|notes payable|commercial paper|senior notes", low):
                continue
            if re.search(r"operating lease|total liabilities|issuance costs|deferred", low):
                continue
            if re.search(r"net of current|excluding current|less current|non-?current", low) \
                    or low.startswith(("long-term", "debt")):
                parts.append(row)
            elif re.search(r"current|short-term|commercial paper", low):
                parts.append(row)
        if not parts:
            return
        idx = latest_columns(st.columns).get(INSTANT, 0) if st.columns else 0
        if any(len(r.cells) <= idx or r.cells[idx] is None for r in parts):
            return
        value = sum(r.cells[idx] for r in parts) * st.scale
        row0 = parts[0]
        label = " + ".join(f"{r.label} {r.cells[idx]:,.0f}" for r in parts)
        flags = [f"computed as the sum of balance sheet lines: {label}; check against the debt footnote"]
        if any("lease" in norm(r.label) for r in parts):
            flags.append("includes finance lease liabilities as labeled")
        if not any(norm(r.label).startswith(("long-term", "debt")) or "net of current" in norm(r.label)
                   or "excluding current" in norm(r.label) for r in parts):
            flags.append("no long-term debt line found")
        self.add(name, st, row0, idx, value, "usd", flags=flags, ref_label="; ".join(r.label for r in parts))

    def _shares_outstanding(self, name):
        st = self.st.get(BALANCE)
        if not st:
            return
        for row in st.rows:
            text = (row.context + " " + row.label).replace("’", "'")
            m = re.search(r"outstanding:?\s*([\d,]+(?:\.\d+)?)\s+shares", text) or \
                re.search(r"([\d,]+(?:\.\d+)?)(?: and [\d,]+(?:\.\d+)?)? shares issued and outstanding", text) or \
                re.search(r"([\d,]+(?:\.\d+)?) shares outstanding", text)
            if m and "common" in text.lower():
                value = float(m.group(1).replace(",", "")) * (1.0 if st.share_scale_raw else st.scale)
                idx = latest_columns(st.columns).get(INSTANT, 0) if st.columns else 0
                flags = ["read from the common stock caption, not a table cell; units assumed to follow the "
                         "statement scale; confirm against the cover page"]
                self.add(name, st, row, idx, value, "shares", flags=flags)
                return


# ---------------------------------------------------------------- public API

def _form_type(pages):
    """10-K or 10-Q if the page text names the form, else blank."""
    joined = " ".join(pages).lower()
    if re.search(r"form 10-?k", joined):
        return "10-K"
    if re.search(r"form 10-?q", joined):
        return "10-Q"
    return ""


def extract_report(pdf_path):
    """Full result: {'values': [SourcedValue], 'pages': {kind: [page numbers]}, 'warnings': [str]}."""
    return report_from_pages(load_pages(pdf_path), os.path.basename(str(pdf_path)))


def report_from_pages(pages, file_name):
    """Same as extract_report but from already extracted page text (used by tests)."""
    found = find_statement_pages(pages)
    warnings = [f"no {k} statement page found" for k in (INCOME, BALANCE, CASHFLOW) if k not in found]
    statements = {k: read_statement(pages, k, idxs) for k, idxs in found.items()}
    form = _form_type(pages)
    if not form:
        types = {c.ptype for s in statements.values() for c in s.columns}
        form = "10-K" if FY in types and not types & {QTR, YTD} else ("10-Q" if types & {QTR, YTD} else "")
    values = _Builder(file_name, statements, form).run()
    missing = sorted(set(FIELDS) - {v.field for v in values})
    if missing:
        warnings.append("fields not found: " + ", ".join(missing))
    return {"values": values, "pages": {k: s.pages for k, s in statements.items()}, "warnings": warnings}


def extract(pdf_path):
    """Read a 10-K or 10-Q PDF and return a list of SourcedValue (source_kind 'pdf')."""
    return extract_report(pdf_path)["values"]


def compare(pdf_values, other_values, tolerance=0.005):
    """Notes for values that differ between two sources (for example PDF vs XBRL) by more than tolerance.

    Values are matched on field, period type, period end and segment. Fields only one side has are
    reported too. Returns a list of plain-text notes; empty means everything that overlaps agrees.
    """
    def key(v):
        return (v.field, v.period_type, v.period_end, v.segment)
    other = {key(v): v for v in other_values}
    notes = []
    for v in pdf_values:
        o = other.get(key(v))
        if o is None:
            continue
        denom = max(abs(v.value), abs(o.value))
        diff = abs(v.value - o.value)
        if denom and diff / denom > tolerance:
            notes.append(f"{v.field} {v.period_type} {v.period_end}: pdf {v.value:,.6g} vs {o.source_kind} {o.value:,.6g} "
                         f"({diff / denom:.2%} apart, limit {tolerance:.2%}); pdf: {v.source_ref}; other: {o.source_ref}")
        elif not denom and diff:
            notes.append(f"{v.field} {v.period_type} {v.period_end}: pdf {v.value} vs {o.source_kind} {o.value}")
    mine = {key(v) for v in pdf_values}
    for k, o in other.items():
        if k not in mine and any(k[0] == m[0] for m in mine):
            notes.append(f"{k[0]} {k[1]} {k[2]}: only in {o.source_kind} ({o.value:,.6g}); pdf has no value for that period")
    return notes
