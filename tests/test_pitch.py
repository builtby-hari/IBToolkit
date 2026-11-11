import re
from pathlib import Path

import pytest
from openpyxl import load_workbook

from ibtoolkit.__main__ import main
from ibtoolkit.xl_eval import Evaluator

MODELS = ["lbo", "merger", "dcf", "bank", "debtcap"]
TAG = re.compile(r'<(\w+)([^>]*\bdata-cell="([^"]+)"[^>]*)>([^<]*)</\1>')


@pytest.fixture(scope="module", params=MODELS)
def built(request, tmp_path_factory):
    d = tmp_path_factory.mktemp(request.param)
    xlsx, page = d / "m.xlsx", d / "pitch.html"
    assert main([request.param, f"cases/{request.param}_sample.toml", "--out", str(xlsx), "--pitch", str(page)]) == 0
    return request.param, xlsx, page.read_text(encoding="utf-8")


def parse(text):
    neg = text.startswith(("(", "-"))
    pct = "%" in text
    num = re.sub(r"[^0-9.]", "", text)
    dec = len(num.split(".")[1]) if "." in num else 0
    v = float(num) / (100 if pct else 1)
    return (-v if neg else v), 0.5 * 10 ** -dec / (100 if pct else 1) + 1e-9


def test_every_figure_ties_to_the_evaluated_workbook(built):
    _, xlsx, doc = built
    ev = Evaluator(load_workbook(xlsx))
    tags = TAG.findall(doc)
    assert len(tags) > 60
    for _, attrs, ref, shown in tags:
        sheet, cell = ref.split("!")
        want = ev.cell(sheet, cell)
        if "data-text" in attrs:
            assert shown == want
        elif shown in ("Pass", "Fail"):
            assert (want == int(re.search(r'data-pass="(\d)"', attrs)[1])) == (shown == "Pass")
        else:
            got, tol = parse(shown)
            assert abs(got - want) <= tol, (ref, shown, want)


def test_no_untagged_figures(built):
    _, _, doc = built
    for m in re.finditer(r'<\w+ [^>]*class="[^"]*\bnum\b[^"]*"[^>]*>', doc):
        assert "data-cell=" in m.group(0)


def test_headline_matches_python_engine(tmp_path):
    from ibtoolkit import lbo
    out = tmp_path / "p.html"
    main(["lbo", "cases/lbo_sample.toml", "--out", str(tmp_path / "m.xlsx"), "--pitch", str(out)])
    irr = lbo.run(lbo.load_case("cases/lbo_sample.toml"))["returns"]["irr"]
    assert f"{irr:.1%}" in out.read_text()


def test_pitch_page_hygiene(built):
    _, _, doc = built
    low = doc.lower()
    assert not re.search(r"http|src=|href=|@import|url\(|<script|<link|<img", low)
    assert chr(0x2014) not in doc and chr(0x2013) not in doc
    assert "@page" in doc and "size: 11in 8.5in" in doc and "break-after: page" in doc
    assert 4 <= doc.count('<section class="page') <= 8
    assert "<svg" in doc and "Illustrative" in doc
    assert "All Checks OK" in doc and "Checks Status" in doc


def test_text_is_escaped(tmp_path):
    case = (tmp_path / "c.toml")
    case.write_text(Path("cases/lbo_sample.toml").read_text().replace(
        "Illustrative Lower Middle Market Services Business", 'A <b>&\\"Co\\"</b>'))
    out = tmp_path / "p.html"
    assert main(["lbo", str(case), "--out", str(tmp_path / "m.xlsx"), "--pitch", str(out)]) == 0
    doc = out.read_text()
    assert "<b>" not in doc and "A &lt;b&gt;&amp;&quot;Co&quot;&lt;/b&gt;" in doc


def test_football_labels_not_clipped(built):
    _, _, doc = built
    labels = re.findall(r'<text x="([\d.]+)" y="[\d.]+" text-anchor="end">((?:(?!</text>).)*?[A-Za-z]{3}(?:(?!</text>).)*)</text>',
                        doc)
    assert labels
    for x, label in labels:
        text = re.sub(r"<[^>]+>", "", label)
        assert float(x) - len(text) * 6 >= 0, text
