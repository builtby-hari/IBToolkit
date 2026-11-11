"""Regenerate the README figures from the illustrative sample cases.

Run from the repo root:  ./.venv/bin/python scripts/make_figures.py
Needs matplotlib (see requirements-figures.txt). Writes docs/figures/*.png. Every number is
computed by the Python engines; nothing is typed in by hand. All cases are illustrative.
"""
import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ibtoolkit import comps, dcf, lbo  # noqa: E402

OUT = ROOT / "docs" / "figures"
NAVY, TEAL, GREY = "#1f3a5f", "#14b8a6", "#6b7280"
DPI = 150
NOTE_DCF = "Illustrative case cases/dcf_sample.toml (made-up companies, not market data, not a forecast)."
NOTE_LBO = "Illustrative case cases/lbo_sample.toml (made-up business, not market data, not a forecast)."


def _footnote(fig, text):
    fig.text(0.01, 0.015, textwrap.fill(text, 150), fontsize=7.2, color=GREY, va="bottom")


def _save(fig, name):
    fig.savefig(OUT / name, dpi=DPI, facecolor="white")
    plt.close(fig)
    print(f"Wrote {OUT / name}")


def football_field():
    case = dcf.load_case(ROOT / "cases" / "dcf_sample.toml")
    sens = dcf.sensitivities(case)
    cp = comps.run(case)
    # Inner 3 by 3 of the 5 by 5 DCF grids: WACC +/- 1 step (0.5 pt), g +/- 1 step (0.25 pt),
    # exit multiple +/- 1 step (1.0x). Outer rows are the +/- 2 step sensitivity extremes.
    rows = []
    for key, label, kind in [("ev_rev_ltm", "Comps: EV / LTM Revenue", "p"), ("ev_rev_ntm", "Comps: EV / NTM Revenue", "p"),
                             ("ev_ebitda_ltm", "Comps: EV / LTM EBITDA", "p"), ("ev_ebitda_ntm", "Comps: EV / NTM EBITDA", "p"),
                             ("pe_ltm", "Comps: P / LTM EPS", "p"), ("pe_ntm", "Comps: P / NTM EPS", "p")]:
        imp = cp["metrics"][key]["implied"]
        rows.append((label, imp["p25"][2], imp["p75"][2], imp["median"][2]))
    inner_g = [sens["price_wacc_g"][i][j] for i in (1, 2, 3) for j in (1, 2, 3)]
    inner_x = [sens["price_wacc_mult"][i][j] for i in (1, 2, 3) for j in (1, 2, 3)]
    base_g = dcf.run(case)["val"]["gordon"]["price"]
    base_x = dcf.run(case)["val"]["exit"]["price"]
    rows.append(("DCF: Gordon growth", min(inner_g), max(inner_g), base_g))
    rows.append(("DCF: exit multiple", min(inner_x), max(inner_x), base_x))

    fig, ax = plt.subplots(figsize=(9.5, 5.6))
    for i, (label, lo, hi, mid) in enumerate(rows):
        color = TEAL if label.startswith("DCF") else NAVY
        ax.add_patch(Rectangle((lo, i - 0.32), hi - lo, 0.64, color=color, alpha=0.85))
        ax.plot([mid, mid], [i - 0.32, i + 0.32], color="white", lw=2)
        ax.text(lo - 0.4, i, f"${lo:,.2f}", va="center", ha="right", fontsize=8.5)
        ax.text(hi + 0.4, i, f"${hi:,.2f}", va="center", ha="left", fontsize=8.5)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(20, 56)
    ax.set_xlabel("Implied value per share (US$)")
    ax.set_title("Football Field: Implied Share Price, Illustrative Industrial Services Target", fontsize=12, loc="left")
    ax.grid(axis="x", color="#e5e7eb", lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    _footnote(fig, "Bars: comps 25th to 75th percentile of peer multiples applied to the target; DCF bars are the inner "
             "3x3 of each sensitivity grid\n(WACC +/-0.5 pt, terminal growth +/-0.25 pt, exit multiple +/-1.0x). White tick = median or base case. "
             f"{NOTE_DCF}")
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    _save(fig, "football_field.png")


def dcf_heatmap():
    case = dcf.load_case(ROOT / "cases" / "dcf_sample.toml")
    s = dcf.sensitivities(case)
    grid = s["price_wacc_g"]
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(grid, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(5))
    ax.set_xticklabels([f"{g:.2%}" for g in s["g_axis"]])
    ax.set_yticks(range(5))
    ax.set_yticklabels([f"{w:.2%}" for w in s["wacc_axis"]])
    ax.set_xlabel("Terminal growth rate (%)")
    ax.set_ylabel("WACC (%)")
    for i in range(5):
        for j in range(5):
            ax.text(j, i, f"${grid[i][j]:,.2f}", ha="center", va="center", fontsize=9,
                    color="white" if grid[i][j] > 44 else "#111827", fontweight="bold" if (i, j) == (2, 2) else None)
    ax.add_patch(Rectangle((1.5, 1.5), 1, 1, fill=False, ec="#dc2626", lw=2))
    cb = fig.colorbar(im, ax=ax, shrink=0.85)
    cb.set_label("Gordon DCF value per share (US$)")
    ax.set_title("DCF Value per Share: WACC vs Terminal Growth (Gordon Method)", fontsize=12, loc="left")
    w0 = dcf.wacc_parts(case["dcf"])["wacc"]
    _footnote(fig, f"Red box = base case (WACC {w0:.2%}, g {case['dcf']['terminal_growth']:.2%}). Steps: WACC 0.50 pt, g 0.25 pt. Mid-year convention on. "
             f"{NOTE_DCF}")
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    _save(fig, "dcf_sensitivity.png")


def lbo_returns():
    case = lbo.load_case(ROOT / "cases" / "lbo_sample.toml")
    s = lbo.sensitivities(case)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    panels = [
        (axes[0], s["irr_entry_exit"], s["entry_axis"], s["exit_axis"], "Entry multiple (x LTM EBITDA)",
         "Exit multiple (x Year 5 EBITDA)", "Entry vs Exit Multiple"),
        (axes[1], s["irr_leverage_exit"], s["leverage_axis"], s["exit_axis"], "Senior leverage (x LTM EBITDA)",
         "Exit multiple (x Year 5 EBITDA)", "Senior Leverage vs Exit Multiple"),
    ]
    for ax, grid, rowax, colax, ylab, xlab, title in panels:
        im = ax.imshow(grid, cmap="Blues", aspect="auto", vmin=0.05, vmax=0.40)
        ax.set_xticks(range(5))
        ax.set_xticklabels([f"{x:.1f}x" for x in colax])
        ax.set_yticks(range(5))
        ax.set_yticklabels([f"{r:.1f}x" for r in rowax])
        ax.set_xlabel(xlab)
        ax.set_ylabel(ylab)
        for i in range(5):
            for j in range(5):
                ax.text(j, i, f"{grid[i][j]:.1%}", ha="center", va="center", fontsize=9,
                        color="white" if grid[i][j] > 0.25 else "#111827")
        ax.add_patch(Rectangle((1.5, 1.5), 1, 1, fill=False, ec="#dc2626", lw=2))
        fig.colorbar(im, ax=ax, shrink=0.8, label="Sponsor IRR (%)")
    axes[0].set_title("Entry vs Exit Multiple", fontsize=11, loc="left")
    axes[1].set_title("Senior Leverage vs Exit Multiple", fontsize=11, loc="left")
    fig.suptitle("LBO Sponsor IRR Sensitivity, 5-Year Hold, No Interim Distributions", fontsize=12, x=0.01, ha="left")
    base = lbo.run(case)["returns"]["irr"]
    t = case["transaction"]
    _footnote(fig, f"Red box = base case ({t['entry_multiple']:.1f}x entry, {t['exit_multiple']:.1f}x exit, {case['senior']['leverage']:.1f}x senior, {base:.1%} IRR). Step: 0.5x multiple, 0.5x leverage. "
             f"{NOTE_LBO}")
    fig.tight_layout(rect=(0, 0.1, 1, 0.95))
    _save(fig, "lbo_returns_sensitivity.png")


def lbo_paydown():
    case = lbo.load_case(ROOT / "cases" / "lbo_sample.toml")
    y = lbo.run(case)["years"]
    yrs = list(range(6))
    sen = [v / 1000 for v in y["s_end"]]
    mez = [v / 1000 for v in y["m_end"]]
    rev = [v / 1000 for v in y["r_end"]]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.bar(yrs, sen, color=NAVY, label="Senior term loan")
    ax.bar(yrs, mez, bottom=sen, color="#93c5fd", label="Mezzanine (incl. PIK)")
    ax.bar(yrs, rev, bottom=[a + b for a, b in zip(sen, mez)], color=TEAL, label="Revolver")
    ax.set_xticks(yrs)
    ax.set_xticklabels(["Close"] + [f"Year {i}" for i in range(1, 6)])
    ax.set_ylabel("Debt outstanding (US$ millions)")
    ax2 = ax.twinx()
    ax2.plot(yrs, y["lev_tot"], color="#dc2626", marker="o", lw=2, label="Total debt / EBITDA (right)")
    ax2.plot(yrs[1:], y["lev_max"][1:], color="#dc2626", ls="--", lw=1.2, label="Covenant maximum (right)")
    ax2.set_ylabel("Total debt / EBITDA (x)")
    ax2.set_ylim(0, 6.5)
    ax.set_ylim(0, 55)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=8, frameon=False)
    ax.set_title("LBO Debt Paydown and Covenant Headroom (Base Case)", fontsize=12, loc="left")
    for s in ("top",):
        ax.spines[s].set_visible(False)
        ax2.spines[s].set_visible(False)
    _footnote(fig, "Bars: debt at each year end. Lines: total debt / EBITDA and the covenant maximum for the year. "
             f"Sweep takes 50% of excess cash. {NOTE_LBO}")
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    _save(fig, "lbo_debt_paydown.png")


def worked_example():
    """Print the README worked example (LBO sample) so the numbers can be checked against the text."""
    case = lbo.load_case(ROOT / "cases" / "lbo_sample.toml")
    r = lbo.run(case)
    su, ret, y = r["su"], r["returns"], r["years"]
    b = ret["bridge"]
    print("Worked example (illustrative LBO, cases/lbo_sample.toml, $ thousands)")
    print(f"  Purchase price {su['purchase_price']:,.0f} | advisory {su['advisory']:,.0f} | financing {su['financing']:,.0f}")
    print(f"  Total uses {su['total_uses']:,.0f} | senior {su['senior']:,.0f} | mezz {su['mezz']:,.0f} | sponsor equity {su['equity']:,.0f}")
    print(f"  Year 5 EBITDA {ret['exit_ebitda']:,.0f} | exit EV {ret['exit_ev']:,.0f} | exit equity {ret['exit_equity']:,.0f}")
    print(f"  MOIC {ret['moic']:.2f}x | IRR {ret['irr']:.1%}")
    print(f"  Bridge: EBITDA growth {b['ebitda_growth']:,.0f} | multiple {b['multiple']:,.0f} | "
          f"deleveraging {b['deleveraging']:,.0f} | fees {b['fees']:,.0f} | sum {sum(b.values()):,.0f}")
    print(f"  Total debt / EBITDA: close {y['lev_tot'][0]:.2f}x, year 1 {y['lev_tot'][1]:.2f}x, year 5 {y['lev_tot'][5]:.2f}x")
    print(f"  Year 1 leverage covenant {y['lev_max'][1]:.2f}x, headroom {y['lev_head'][1]:.1%} | "
          f"coverage {y['cov'][1]:.2f}x vs minimum {y['cov_min'][1]:.2f}x | FCCR {y['fccr'][1]:.2f}x")
    print(f"  Peak revolver draw {ret['peak_revolver']:,.0f} | covenant failures {ret['cov_fails']}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    worked_example()
    football_field()
    dcf_heatmap()
    lbo_returns()
    lbo_paydown()
