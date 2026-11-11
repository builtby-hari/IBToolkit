"""Reproduce the README worked example and regenerate the figures in docs/figures/.

Run from the repo root:  python3 scripts/make_figures.py
Needs matplotlib (python3 -m pip install matplotlib). Every number is illustrative: a made-up
deal from data/sample/ and the typed rates in config/settings.example.toml. No network is used.
"""
import copy
import math
import os
import sys

os.environ.setdefault("MPLBACKEND", "Agg")  # file output only, no window
import matplotlib.pyplot as plt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
from biz_screener import (
    config,
    ingest,
    normalize,
    pipeline,
    returns,
    sba,
    scoring,
)

SETTINGS = os.path.join(ROOT, "config", "settings.example.toml")
SAMPLE = os.path.join(ROOT, "data", "sample", "sample_listings.csv")
OUT = os.path.join(ROOT, "docs", "figures")
REF = "SAMPLE-ILLUSTRATIVE-LAUNDRY-PASS"
PRIME, RISK_FREE = 0.0675, 0.042
NOTE = ("Illustrative only: made-up sample deal (data/sample), typed rates "
        "(prime 6.75%, 10-year 4.20%), no market data.")


def load_deal():
    cfg = config.load_settings(SETTINGS)
    deals, _ = ingest.parse_csv(SAMPLE)
    listing, periods, adds = next(d for d in deals if d[0].external_ref == REF)
    return cfg, listing, periods, adds


def worked_example(cfg, listing, periods, adds):
    """Print each step for the README and assert the numbers the README quotes."""
    ind = cfg["industries"][listing.category]
    norm = normalize.normalize_periods(periods, adds, ind["manager_salary_default"])
    last = norm[-1]
    score, val, debt = pipeline.screen_deal(listing, periods, adds, cfg, PRIME, RISK_FREE)
    latest = max(periods, key=lambda p: p.fiscal_year)
    da = latest.depreciation + latest.amortization
    ret = returns.equity_returns(listing.asking_price, last.ebitda, da, debt, cfg)
    manager = ind["manager_salary_default"]
    print(f"Worked example (illustrative, deal {REF}, FY{last.fiscal_year})")
    print(f"  SDE                 ${last.sde:,.0f}")
    print(f"  EBITDA              ${last.ebitda:,.0f}  (SDE less manager ${manager:,} x 1.0765)")
    print(f"  Value by SDE        ${val.sde_value:,.0f}")
    print(f"  Value by EBITDA     ${val.ebitda_value:,.0f}")
    print(f"  Value by DCF        ${val.dcf_value:,.0f}")
    print(f"  Blended value       ${val.blended_value:,.0f}   asking ${listing.asking_price:,.0f}")
    print(f"  SBA loan            ${debt.loan_amount:,.0f} at {debt.rate * 100:.2f}% over 10 years")
    print(f"  Annual debt service ${debt.annual_payment:,.0f}")
    print(f"  DSCR: EBITDA {debt.dscr_ebitda:.2f}x, owner {debt.dscr_owner:.2f}x, "
          f"lender test {debt.dscr_lender:.2f}x (minimum 1.25x)")
    print(f"  Score               {score.total:.1f} (red-flag penalty {score.penalty:.0f})")
    print(f"  Buyer equity        invested ${ret['invested']:,.0f}, MOIC {ret['moic']:.2f}x, "
          f"IRR {ret['irr'] * 100:.1f}% (5-year hold, exit at entry multiple)")
    # Self-check: fails loudly if the model drifts from the numbers the README quotes.
    assert round(last.sde) == 220_000
    assert round(last.ebitda) == 160_792
    assert round(val.blended_value) == 624_632
    assert round(debt.loan_amount) == 350_000
    assert abs(debt.rate - 0.1125) < 1e-9
    assert abs(debt.dscr_lender - 2.22) < 0.005
    assert abs(score.total - 91.9) < 0.05
    assert abs(ret["irr"] - 0.290) < 0.001


def irr_grid(cfg, listing, periods, adds):
    """Equity IRR (%) by asking price (rows) and revenue growth (columns)."""
    ind = cfg["industries"][listing.category]
    norm = normalize.normalize_periods(periods, adds, ind["manager_salary_default"])[-1]
    latest = max(periods, key=lambda p: p.fiscal_year)
    da = latest.depreciation + latest.amortization
    prices = list(range(450_000, 750_001, 50_000))
    growths = [0.00, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    grid = []
    for price in prices:
        row = []
        for g in growths:
            c = copy.deepcopy(cfg)
            c["dcf"]["revenue_growth_base"] = g
            try:
                debt = sba.debt_summary(price, norm.ebitda, norm.sde, PRIME, c["sba"], c["buyer"])
                ret = returns.equity_returns(price, norm.ebitda, da, debt, c)
                row.append(float("nan") if ret["irr"] is None else ret["irr"] * 100)
            except ValueError:  # equity shortfall: no financing structure at this price
                row.append(float("nan"))
        grid.append(row)
    return prices, growths, grid


def plot_irr_heatmap(prices, growths, grid, path):
    fig, ax = plt.subplots(figsize=(8, 5.4))
    im = ax.imshow(grid, cmap="RdYlGn", vmin=0, vmax=40, aspect="auto", origin="lower")
    ax.set_xticks(range(len(growths)), [f"{g * 100:.0f}%" for g in growths])
    ax.set_yticks(range(len(prices)), [f"${p // 1000}k" for p in prices])
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            label = "n/a" if math.isnan(v) else f"{v:.0f}%"
            ax.text(j, i, label, ha="center", va="center", fontsize=9, color="black")
    ax.set_xlabel("Annual revenue and EBITDA growth, years 2 to 5 (%)")
    ax.set_ylabel("Asking price (USD thousands)")
    ax.set_title("Buyer equity IRR by asking price and growth (5-year hold)", fontweight="bold")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Equity IRR (%)")
    fig.text(0.01, 0.012, NOTE + "\nExit at entry EBITDA multiple. n/a = equity shortfall (no financing at that price).",
             fontsize=7.5, style="italic")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def dscr_vs_price(cfg):
    """Lender DSCR across asking prices, with the SBA spread steps visible."""
    rows = []
    for price in range(300_000, 900_001, 5_000):
        d = sba.debt_summary(price, 160_792, 220_000, PRIME, cfg["sba"], cfg["buyer"])
        rows.append((price, d.dscr_lender))
    return rows


def plot_dscr(rows, path):
    prices = [r[0] / 1000 for r in rows]
    dscr = [r[1] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(prices, dscr, color="#1f5fa8", lw=2, label="Lender DSCR (lower of two views)")
    ax.axhline(1.25, color="#a11", ls="--", lw=1.2, label="SBA minimum 1.25x")
    for price in (500, 600):
        ax.axvline(price, color="#888", lw=0.6, alpha=0.6)
    ax.axvline(600, color="grey", ls=":", lw=1.2)
    ax.text(603, 3.3, "Asking $600k", color="grey", fontsize=9)
    ax.annotate("loan passes $250k:\nspread 6.0% to 4.5%", xy=(500, 2.93), xytext=(520, 3.4),
                fontsize=8.5, arrowprops={"arrowstyle": "->", "color": "#555"})
    ax.annotate("loan passes $350k:\nspread 4.5% to 3.0%", xy=(600, 2.22), xytext=(640, 2.6),
                fontsize=8.5, arrowprops={"arrowstyle": "->", "color": "#555"})
    ax.set_xlabel("Purchase price (USD thousands)")
    ax.set_ylabel("Lender DSCR (times)")
    ax.set_title("DSCR vs purchase price: DSCR steps up at each SBA spread tier",
                 fontweight="bold")
    ax.set_ylim(1.0, 3.6)
    ax.legend(loc="lower left", fontsize=8.5)
    ax.grid(alpha=0.3)
    fig.text(0.01, 0.012, NOTE + "\nBuyer cash $250k; SDE $220k; EBITDA $160,792; loan = price less cash.",
             fontsize=7.5, style="italic")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_valuation_gap(points, path):
    """Score curve for the valuation gap, with the sample deals on it."""
    xs = [x / 100 for x in range(-20, 81)]
    ys = [scoring.valuation_gap_score(1 + x, 1) for x in xs]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot([x * 100 for x in xs], ys, color="#555", lw=2, label="Score mapping (0 to 100)")
    for ref, gap, score in points:
        ax.scatter(gap * 100, score, s=60, color="#1f5fa8", zorder=3)
        ax.annotate(ref.replace("SAMPLE-", ""), (gap * 100, score), xytext=(6, 6),
                    textcoords="offset points", fontsize=8.5)
    ax.axvline(-10, color="#2a7a2a", ls=":", lw=1.2)
    ax.axvline(40, color="#a11", ls=":", lw=1.2)
    ax.text(-9.5, 8, "100 points at asking 10% below blended", fontsize=8, color="#2a7a2a")
    ax.text(42, 12, "0 points at 40% above", fontsize=8, color="#a11")
    ax.set_xlabel("Asking price vs blended value (%, negative = below value)")
    ax.set_ylabel("Valuation gap component (0 to 100)")
    ax.set_title("Valuation gap score: how the asking price is scored", fontweight="bold")
    ax.set_ylim(0, 105)
    ax.legend(loc="upper right", fontsize=8.5)
    ax.grid(alpha=0.3)
    fig.text(0.01, 0.012, NOTE + "\nPoints are the four sample deals in data/sample.",
             fontsize=7.5, style="italic")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def sample_gap_points(cfg):
    deals, _ = ingest.parse_csv(SAMPLE)
    points = []
    for listing, periods, adds in deals:
        sc, val, _ = pipeline.screen_deal(listing, periods, adds, cfg, PRIME, RISK_FREE)
        gap = (listing.asking_price - val.blended_value) / val.blended_value
        points.append((listing.external_ref, gap, sc.components["valuation_gap"]))
    return points


def main():
    os.makedirs(OUT, exist_ok=True)
    cfg, listing, periods, adds = load_deal()
    worked_example(cfg, listing, periods, adds)

    prices, growths, grid = irr_grid(cfg, listing, periods, adds)
    p1 = os.path.join(OUT, "irr_sensitivity.png")
    plot_irr_heatmap(prices, growths, grid, p1)

    p2 = os.path.join(OUT, "dscr_vs_price.png")
    plot_dscr(dscr_vs_price(cfg), p2)

    p3 = os.path.join(OUT, "valuation_gap.png")
    plot_valuation_gap(sample_gap_points(cfg), p3)

    for p in (p1, p2, p3):
        print("wrote", os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
