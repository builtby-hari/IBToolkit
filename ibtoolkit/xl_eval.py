"""Tiny evaluator for the formula subset the toolkit writes.

Supports + - * / ^, string literals, ABS, CONCATENATE, comparisons, MAX, MIN, SUM, AVERAGE, MEDIAN, COUNT, EDATE, PERCENTILE (inclusive), SLOPE, INTERCEPT, RSQ, IF, cell and range references
(optionally with a sheet prefix), and workbook defined names. It lets tests
compute what the workbook formulas imply without Excel installed.
"""
import datetime as dt
import re
import statistics

from openpyxl.utils import column_index_from_string, get_column_letter

EPOCH = dt.date(1899, 12, 30)  # Excel date serial 0
TOKEN = re.compile(
    r'(?P<str>"[^"]*")'
    r"|(?P<ref>(?:(?P<sheet>[A-Za-z_]\w*)!)?\$?(?P<c1>[A-Z]{1,3})\$?(?P<r1>\d+)"
    r"(?::\$?(?P<c2>[A-Z]{1,3})\$?(?P<r2>\d+))?)(?![\w(])"
    r"|(?P<name>[A-Za-z_]\w*\b)(?!\()")


def _flat(args):
    """Flatten arguments to numbers only; text and blanks in ranges are skipped, like Excel."""
    for a in args:
        if isinstance(a, list):
            yield from _flat(a)
        elif isinstance(a, (int, float)):
            yield a


def _edate(serial, months):
    d = EPOCH + dt.timedelta(days=int(serial))
    m = d.year * 12 + d.month - 1 + int(months)
    y, mo = divmod(m, 12)
    nxt = dt.date(y + (mo == 11), (mo + 1) % 12 + 1, 1)
    return (dt.date(y, mo + 1, min(d.day, (nxt - dt.timedelta(days=1)).day)) - EPOCH).days


def _percentile(xs, k):
    """Excel PERCENTILE (inclusive): linear interpolation at rank k * (n - 1)."""
    xs = sorted(xs)
    pos = k * (len(xs) - 1)
    lo = int(pos)
    return xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (pos - lo)


def _split_args(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def _convert_if(s):
    while (i := s.find("IF(")) != -1:
        depth, j = 0, i + 2
        while True:
            depth += s[j] == "("
            depth -= s[j] == ")"
            if depth == 0:
                break
            j += 1
        c, a, b = (_convert_if(x) for x in _split_args(s[i + 3:j]))
        s = f"{s[:i]}(({a}) if ({c}) else ({b})){s[j + 1:]}"
    return s


def _ols(ys, xs):
    """Excel argument order: SLOPE(known_ys, known_xs). Returns slope, intercept, RSQ."""
    ys, xs = list(_flat([ys])), list(_flat([xs]))
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / sxx, my - sxy / sxx * mx, sxy * sxy / (sxx * syy)


class Evaluator:
    def __init__(self, wb):
        self.wb, self.cache = wb, {}
        self.names = {n: d.attr_text for n, d in wb.defined_names.items()}

    def cell(self, sheet, ref):
        key = (sheet, ref)
        if key not in self.cache:
            v = self.wb[sheet][ref].value
            if isinstance(v, dt.datetime):
                v = v.date()
            if isinstance(v, dt.date):
                v = (v - EPOCH).days  # dates are serial numbers, as in Excel
            self.cache[key] = self._eval(sheet, v[1:]) if isinstance(v, str) and v.startswith("=") else v
        return self.cache[key]

    def name(self, n):
        sheet, ref = self.names[n].split("!")
        return self.cell(sheet, ref.replace("$", ""))

    def _range(self, sheet, a, b):
        (ca, ra), (cb, rb) = (re.match(r"([A-Z]+)(\d+)", x).groups() for x in (a, b))
        return [self.cell(sheet, f"{get_column_letter(c)}{r}")
                for r in range(int(ra), int(rb) + 1)
                for c in range(column_index_from_string(ca), column_index_from_string(cb) + 1)]

    def _eval(self, sheet, f):
        def sub(m):
            if m["str"]:
                return m["str"]
            if m["ref"]:
                sh = m["sheet"] or sheet
                if m["c2"]:
                    return f'R("{sh}","{m["c1"]}{m["r1"]}","{m["c2"]}{m["r2"]}")'
                return f'V("{sh}","{m["c1"]}{m["r1"]}")'
            return f'N("{m["name"]}")'

        py = TOKEN.sub(sub, f)
        py = py.replace("^", "**").replace("<>", "!=")
        py = re.sub(r"(?<![<>=!])=(?!=)", "==", py)
        py = _convert_if(py)
        env = {"V": self.cell, "R": self._range, "N": self.name,
               "MAX": lambda *a: max(_flat(a)), "MIN": lambda *a: min(_flat(a)),
               "ABS": abs, "CONCATENATE": lambda *a: "".join(str(x) for x in a),
               "SUM": lambda *a: sum(_flat(a)), "COUNT": lambda *a: sum(1 for _ in _flat(a)),
               "EDATE": _edate,
               "AVERAGE": lambda *a: statistics.fmean(_flat(a)),
               "MEDIAN": lambda *a: statistics.median(_flat(a)),
               "PERCENTILE": lambda rng, k: _percentile(list(_flat([rng])), k),
               "SLOPE": lambda y, x: _ols(y, x)[0], "INTERCEPT": lambda y, x: _ols(y, x)[1],
               "RSQ": lambda y, x: _ols(y, x)[2]}
        return eval(py, {"__builtins__": {}}, env)
