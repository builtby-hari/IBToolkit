"""Review step for a draft case: show every sourced value, run sanity checks, list what is still TODO,
and approve the draft (draft = false) only when it is clean.

Checks: balance sheet ties, period mismatches across fields, stale data, units, odd signs, and whether
the numbers written in [target] still match the sourced values they came from.
"""
import copy
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import draft as draftmod
from .fields import APPROVED, FIELDS, FLAG, SourcedValue

BALANCE_TOL = 0.005       # total assets vs liabilities + equity, relative
STALE_DAYS = 183          # newest filing vs this value's filing
MIN_SIZE = 10_000         # a USD revenue or asset figure below this probably has a units problem
NON_NEGATIVE = ("revenue", "total_assets", "cash", "debt", "capex", "d_and_a", "interest_expense", "goodwill",
                "intangibles", "current_assets", "current_liabilities", "diluted_shares", "shares_outstanding")
POSITIVE = ("revenue", "total_assets", "diluted_shares", "shares_outstanding")
# [target] key -> the field whose value it comes from (for attaching issues).
TARGET_OWNER = {"net_debt": "debt", "diluted_shares": "diluted_shares", "ltm_revenue": "revenue",
                "ltm_ebitda": "operating_income", "ltm_eps": "diluted_eps"}


@dataclass
class Issue:
    field: str
    note: str
    value: SourcedValue = None   # None when the issue is not tied to one sourced value

    def resolved(self):
        return self.value is not None and self.value.status == APPROVED


@dataclass
class Report:
    path: str
    is_draft: bool
    values: list
    issues: list
    todos: list
    manual: list = field(default_factory=list)   # (key, value, has_source) for hand-entered [target] numbers
    info: list = field(default_factory=list)

    @property
    def unresolved(self):
        return [i for i in self.issues if not i.resolved()]


def _load(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Draft file not found: {path}")
    text = path.read_text()
    return text, tomllib.loads(text)


def values_from(raw):
    """SourcedValue list from the [[intake.values]] blocks."""
    return [SourcedValue(**d) for d in raw.get("intake", {}).get("values", [])]


def todo_lines(text):
    """Every TODO comment as one string (its wrapped continuation lines are joined on)."""
    out, lines = [], text.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r"^\s*#\s*TODO\b", ln):
            parts, j = [ln.strip().lstrip("#").strip()], i + 1
            while j < len(lines) and lines[j].startswith("#    "):
                parts.append(lines[j].lstrip("#").strip())
                j += 1
            out.append(" ".join(parts))
    return out


# ---- checks --------------------------------------------------------------------------------------

def _days(a, b):
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _is_cover(v):
    return v.field == "shares_outstanding" and any("cover page" in n for n in v.notes)


def check_values(values):
    """Issues from the values alone (no case file needed)."""
    out = []
    by = {v.field: v for v in values}

    def add(v, note):
        out.append(Issue(v.field, note, v))

    for v in values:
        if v.status == FLAG:
            for n in v.notes or ["flagged on extraction"]:
                add(v, f"flagged on extraction: {n}")
        if v.unit != FIELDS[v.field][0]:
            add(v, f"unit {v.unit} should be {FIELDS[v.field][0]}")
        if v.field in POSITIVE and v.value <= 0:
            add(v, f"odd sign: {v.field} is {v.value:,.0f}, expected positive")
        elif v.field in NON_NEGATIVE and v.value < 0:
            add(v, f"odd sign: {v.field} is negative ({v.value:,.0f})")
        if v.field in ("revenue", "total_assets") and 0 < v.value < MIN_SIZE:
            add(v, f"units: {v.field} is only {v.value:,.0f} USD; was it filed in thousands or millions?")
    ni, eps = by.get("net_income"), by.get("diluted_eps")
    if ni and eps and ni.value * eps.value < 0:
        add(eps, "odd sign: diluted EPS and net income have opposite signs")
    ta, le = by.get("total_assets"), by.get("liabilities_and_equity")
    if ta and le and ta.period_end == le.period_end and ta.value:
        if abs(ta.value - le.value) / abs(ta.value) > BALANCE_TOL:
            add(ta, f"balance sheet does not tie: total assets {ta.value:,.0f} vs liabilities + equity {le.value:,.0f}")
    ca = by.get("current_assets")
    if ca and ta and ca.value > ta.value:
        add(ca, "current assets exceed total assets")
    out += _period_issues(values)
    out += _stale_issues(values)
    return _dedupe(out)


def _period_issues(values):
    core = [v for v in values if not _is_cover(v)]
    if not core:
        return []
    ref = max(v.period_end for v in core)
    return [Issue(v.field, f"period mismatch: ends {v.period_end}, but the latest period in this draft is {ref}", v)
            for v in core if v.period_end != ref]


def _stale_issues(values):
    dated = [v for v in values if v.filed]
    if not dated:
        return []
    newest = max(v.filed for v in dated)
    return [Issue(v.field, f"stale: filed {v.filed}, more than 6 months before the newest filing ({newest})", v)
            for v in dated if _days(newest, v.filed) > STALE_DAYS]


def _dedupe(issues):
    seen, out = set(), []
    for i in issues:
        k = (i.field, i.note)
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out


def _target_issues(values, raw, text):
    """Compare [target] to what the sourced values give; collect hand-entered numbers."""
    target = raw.get("target", {})
    sel = draftmod.select(values)
    derived = draftmod.derive_target(sel)
    issues, manual = [], []
    for key, expected in derived.items():
        if key not in target:
            continue
        issue = _compare(key, target[key], expected, sel.get(TARGET_OWNER[key]))
        if issue:
            issues.append(issue)
    for key, val in target.items():
        if key not in derived:
            manual.append((key, val, _has_source_comment(text, key)))
    for key, val, ok in manual:
        if not ok:
            issues.append(Issue(f"target.{key}", "hand-entered number with no source comment (write the source "
                                "above or beside the line, or label it ASSUMPTION)"))
    return issues, manual


def _compare(key, written, expected, owner):
    if not isinstance(written, (int, float)) or not expected:
        return None
    if abs(written - expected) / abs(expected) <= BALANCE_TOL / 5:
        return None
    ratio = written / expected
    for p in (1e3, 1e6, 1e-3, 1e-6):
        if abs(ratio - p) / p < 0.02:
            return Issue(f"target.{key}", f"units: written {written:g} is about {p:g}x the sourced {expected:,.3f}", owner)
    return Issue(f"target.{key}", f"written {written:g} differs from the sourced {expected:,.3f}; "
                 "note why it was edited", owner)


def _has_source_comment(text, key):
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if re.match(rf"^{re.escape(key)}\s*=", ln):
            if "#" in ln.split("=", 1)[1]:
                return True
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            return j >= 0 and lines[j].lstrip().startswith("#") and not re.match(r"^\s*#\s*TODO\b", lines[j])
    return False


def review(path):
    """Load a draft case and run every check."""
    text, raw = _load(path)
    values = values_from(raw)
    issues = check_values(values)
    t_issues, manual = _target_issues(values, raw, text)
    info = []
    by = {v.field: v for v in values}
    if "liabilities_and_equity" not in by or "total_assets" not in by:
        info.append("balance check skipped: total assets or liabilities + equity not available")
    return Report(str(path), bool(raw.get("meta", {}).get("draft")), values, issues + t_issues,
                  todo_lines(text), manual, info)


# ---- printing ------------------------------------------------------------------------------------

def _show(v):
    unit = v.unit
    if unit == "USD":
        return f"{v.value / 1e6:,.1f}M"
    if unit == "shares":
        return f"{v.value / 1e6:,.3f}M"
    return f"{v.value:,.4f}"


def _short_src(v):
    accns = list(dict.fromkeys(re.findall(r"accn (\S+)", v.source_ref)))
    tags = list(dict.fromkeys(re.findall(r"tag (\w+)", v.source_ref)))
    return f"{v.form or '?'} accn {', '.join(accns)} tag {', '.join(tags)}"


def format_report(rep):
    """The review table as text."""
    flags = {}
    for i in rep.issues:
        if i.value is not None:
            flags.setdefault(id(i.value), []).append(i.note)
    rows = [("field", "value", "period", "status", "source")]
    notes = []
    for v in rep.values:
        status = "flag" if flags.get(id(v)) and v.status == "ok" else v.status
        rows.append((v.field, _show(v), f"{v.period_type} {v.period_end}", status, _short_src(v)))
        notes.append(flags.get(id(v), []))
    for key, val, ok in rep.manual:
        rows.append((f"target.{key}", f"{val:g}" if isinstance(val, (int, float)) else str(val), "-", "manual",
                     "hand-entered" + ("" if ok else " (no source comment)")))
        notes.append([])
    widths = [min(max(len(r[i]) for r in rows), 64) for i in range(5)]
    out = [f"Review of {rep.path} (draft = {'true' if rep.is_draft else 'false'})", ""]
    for n, r in enumerate(rows):
        out.append("  ".join(c[:widths[i]].ljust(widths[i]) for i, c in enumerate(r)).rstrip())
        if n == 0:
            out.append("  ".join("-" * w for w in widths))
        else:
            out += [f"      ! {note}" for note in notes[n - 1]]
    loose = [i for i in rep.issues if i.value is None]
    for i in loose:
        out.append(f"  ! {i.field}: {i.note}")
    out += [""] + [f"Note: {n}" for n in rep.info]
    out.append(f"Flags: {len(rep.unresolved)} unresolved of {len(rep.issues)}")
    out.append(f"TODOs: {len(rep.todos)}")
    out += [f"  - {t}" for t in rep.todos]
    return "\n".join(out)


# ---- approve -------------------------------------------------------------------------------------

def approve(path, accept_flags=False, today=None):
    """Set draft = false when there are no TODOs and no unresolved flags (or the flags are accepted).
    Returns (ok, message)."""
    from .. import dcf  # late import: dcf is not needed to review
    rep = review(path)
    text, raw = _load(path)
    if not rep.is_draft:
        return True, f"{path} is already approved (draft = false)"
    if rep.todos:
        return False, f"Not approved: {len(rep.todos)} TODO item(s) remain. Fill each in with a sourced value."
    if rep.unresolved and not accept_flags:
        return False, (f"Not approved: {len(rep.unresolved)} unresolved flag(s). Fix them, or accept them with "
                       "--accept-flags after reading the review.")
    probe = copy.deepcopy(raw)
    probe.get("meta", {}).pop("draft", None)
    try:
        dcf.validate(probe)
    except dcf.CaseError as e:
        return False, f"Not approved: the case does not validate yet ({e})"
    today = today or date.today().isoformat()
    new = _rewrite(text, {i.value.field for i in rep.unresolved if i.value is not None}, today)
    Path(path).write_text(new)
    n = len({i.field for i in rep.unresolved})
    extra = f" ({n} flagged item(s) accepted)" if n else ""
    return True, f"Approved {path}: draft = false{extra}"


def _rewrite(text, accept_fields, today):
    """Flip draft to false and mark accepted values as approved, editing only the lines we wrote."""
    out, in_values, cur = [], False, None
    for ln in text.splitlines():
        if re.match(r"^draft\s*=\s*true\b", ln):
            ln = "draft = false"
        elif ln.strip() == "[[intake.values]]":
            in_values, cur = True, None
        elif ln.startswith("[") and in_values:
            in_values = False
        elif in_values:
            m = re.match(r'^field = "(\w+)"', ln)
            if m:
                cur = m.group(1)
            elif cur in accept_fields and ln.startswith("status = "):
                ln = 'status = "approved"'
            elif cur in accept_fields and ln.startswith("notes = ["):
                add = f'"accepted by reviewer with --accept-flags on {today}"'
                ln = ln[:-1] + add + "]" if ln == "notes = []" else ln[:-1] + ", " + add + "]"
        out.append(ln)
    return "\n".join(out) + "\n"
