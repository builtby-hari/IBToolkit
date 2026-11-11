# Methodology

All formulas are in USD. Rates are annual unless marked monthly. Every constant in these formulas comes from `config/settings.toml`, not from code.

## 1. Seller's Discretionary Earnings (SDE)

$$
\text{SDE} = \text{Pre-Tax Income} + \text{Interest} + \text{Depreciation} + \text{Amortization} + \text{Owner Salary} + \sum_{i} \text{Personal or One-Time Add-Backs}_i
$$

Each add-back $A_i$ has a label, an amount, a category and a source note. Categories are `personal`, `one_time`, `non_cash` and `owner_comp`.

**Add-back ratio** (flag input):

$$
r_{\text{add}} = \frac{\sum_i A_i}{\max(\text{Pre-Tax Income}, 1)}
$$

## 2. EBITDA (Buyer View)

A buyer who hires a manager must pay that manager. EBITDA here is SDE less a market manager's compensation, including payroll burden.

$$
\text{EBITDA} = \text{SDE} - \text{Manager Salary} \times (1 + \text{Payroll Burden})
$$

Payroll burden defaults to 0.0765 (employer FICA). Manager salary defaults per industry in config.

## 3. Multiples Valuation

For each industry $k$ with SDE multiple range $[m_{\text{lo}}, m_{\text{hi}}]$ (config):

$$
V_{\text{SDE}} = \text{SDE} \times m_k, \quad m_k = \begin{cases} \frac{m_{\text{lo}} + m_{\text{hi}}}{2} & \text{if use\_midpoint} \\ m_{\text{lo}} & \text{otherwise} \end{cases}
$$

The same rule gives $V_{\text{EBITDA}}$ from the EBITDA multiple range.

## 4. Discounted Cash Flow

**Cash flow available to the buyer** in year $t$:

$$
\text{CF}_t = \text{EBITDA}_t - \text{Capex}_t - \tau \times (\text{EBITDA}_t - D\&A_t)
$$

with $\text{Capex}_t = c \times \text{EBITDA}_t$, where $c$ is `maintenance_capex_pct_of_ebitda`, and $\tau$ is `tax_rate`.

EBITDA grows at the base growth rate $g$:

$$
\text{EBITDA}_t = \text{EBITDA}_0 (1+g)^{t-1}
$$

**Discount rate** build-up:

$$
r = r_f + \pi_{\text{size}} + \pi_{\text{ind}}
$$

where $r_f$ is the FRED DGS10 yield (with `--live-rates`) or the typed rate in config, $\pi_{\text{size}}$ is the size and illiquidity premium and $\pi_{\text{ind}}$ is the industry premium.

**Present value** over $N$ forecast years with Gordon growth terminal value:

$$
V_{\text{DCF}} = \sum_{t=1}^{N} \frac{\text{CF}_t}{(1+r)^t} + \frac{\text{CF}_{N+1}}{(r - g_{\infty})(1+r)^N}, \quad \text{CF}_{N+1} = \text{CF}_N (1 + g_{\infty})
$$

The model requires $r > g_{\infty}$. If not, the run stops with an error.

## 5. SBA 7(a) Debt Sizing

**Loan amount** (change of ownership, equity injection at least $e_{\min}$):

$$
L = P - \max(e_{\min} \times P, E_{\text{cash}}), \quad L \le L_{\max} = \$5{,}000{,}000
$$

where $P$ is the purchase price and $E_{\text{cash}}$ is the buyer's cash equity from config. A seller note on full standby (config `seller_standby_note`) counts as equity up to half of the required injection (SOP 50 10 8.1, App. 15); any excess still reduces $L$. Cash plus that credit must cover $e_{\min} P$. Loans with $L \le 0$ or $P \le 0$ are rejected. A loan above $L_{\max}$ is not trimmed to the cap (that would leave the gap unfunded and overstate DSCR): the deal gets an `equity_shortfall` flag that names the extra equity needed.

**Guarantee fee** (paid at closing, not in the loan): 2% of the guaranteed portion up to $150k loans (85% guaranteed), 3% for $150k to $700k, and 3.5% up to $1M of guaranteed portion plus 3.75% above (75% guaranteed). These are SOP maximums.

**Interest rate** (variable, prime plus spread by loan size):

$$
i = \text{DPRIME} + s(L)
$$

Spread $s(L)$ comes from config bands that follow the SOP 50 10 tiers: $50,000 or less, $50,001 to $250,000, $250,001 to $350,000, and over $350,000.

**Monthly payment** (annuity, $n = 12T$ months, monthly rate $j = i/12$):

$$
\text{PMT} = \frac{L \cdot j}{1 - (1+j)^{-n}}
$$

**Annual debt service**: $\text{DS} = 12 \times \text{PMT}$.

**DSCR** (two views):

$$
\text{DSCR}_{\text{EBITDA}} = \frac{\text{EBITDA}}{\text{DS}}, \qquad \text{DSCR}_{\text{owner}} = \frac{\text{SDE} - D_{\text{owner}}}{\text{DS}}
$$

where $D_{\text{owner}}$ is the owner living draw from config. The lender test uses the lower of the two. A DSCR of at least 1.25 passes: SOP 50 10 8.1 App. 15 sets 1.25 for an Initial Acquisition or Owner Buyout (1.15 applies only to a Business Expansion), measured on historical EBITDA with no reliance on projections.

## 6. Scoring Model

Each component returns a points value from 0 to 100. Weights $w_c$ come from config and sum to 100.

$$
S_{\text{raw}} = \sum_c w_c \cdot \frac{x_c}{100}
$$

Components:

| Component | Weight | How the 0 to 100 Value Is Set |
|---|---|---|
| Valuation gap | 25 | 100 when asking is at or below blended value by 10 percent, falling linearly to 0 at 40 percent above |
| DSCR | 20 | 0 at DSCR 1.0, 100 at DSCR 2.5, linear between |
| Revenue trend | 15 | Three-year revenue CAGR mapped from minus 5 percent (0) to plus 5 percent (100). A blank growth figure scores 0 and the report notes "revenue growth not provided: ask the broker" |
| Concentration | 10 | 100 when top customer or contract share is 5 percent or less, 0 at 50 percent or more. A blank share scores 0 and the report notes "customer concentration not provided: ask the broker" |
| Market context | 15 | County NAICS establishment growth and payroll growth, averaged and mapped from minus 3 percent (0) to plus 3 percent (100). Not built yet: when missing, this component is dropped and the other weights are rescaled to the same total |
| Data quality | 10 | Share of required fields present, with stated financials scored above estimated ones |
| Operational risk | 5 | 100 with no lease or license flags, reduced by each operational flag |

**Red-flag penalty**:

$$
P_{\text{flag}} = \min\left(\sum_j p_j, P_{\max}\right), \quad p_j = 5, \quad P_{\max} = 20
$$

**Final score**:

$$
S = \max(0, S_{\text{raw}} - P_{\text{flag}})
$$

Listings are ranked by $S$ descending. Ties go to the lower asking price.

## 7. Worked Example (Made-Up Numbers, For Illustration Only)

These numbers are invented for this document. They are not a real listing.

**Listing:** a fuel station with a convenience store in a suburban Texas county. Category: `gas_station`.

**Reported figures (seller-stated, year 0):**

| Item | Amount |
|---|---|
| Asking price | $1,200,000 |
| Pre-tax income | $270,000 |
| Interest | $0 |
| Depreciation | $55,000 |
| Owner salary | $90,000 |
| One-time legal settlement (add-back) | $15,000 |
| Personal vehicle (add-back) | $10,000 |

**Step 1: SDE**

$$
\text{SDE} = 270{,}000 + 0 + 55{,}000 + 90{,}000 + 15{,}000 + 10{,}000 = 440{,}000
$$

Add-back ratio: $r_{\text{add}} = (55{,}000 + 90{,}000 + 15{,}000 + 10{,}000) / 270{,}000 = 170{,}000 / 270{,}000 = 0.63$. This is above the 0.40 flag threshold.

**Step 2: EBITDA**

Manager salary of $80,000 is treated as already including burden here (burden set to 0 for this example; the code default adds 7.65 percent).

$$
\text{EBITDA} = 440{,}000 - 80{,}000 = 360{,}000
$$

**Step 3: Multiples**

Config ranges: SDE 2.0x to 3.0x (midpoint 2.5x), EBITDA 3.0x to 4.0x (midpoint 3.5x).

$$
V_{\text{SDE}} = 440{,}000 \times 2.5 = 1{,}100{,}000
$$

$$
V_{\text{EBITDA}} = 360{,}000 \times 3.5 = 1{,}260{,}000
$$

Asking multiples: $1{,}200{,}000 / 440{,}000 = 2.73$x SDE and $1{,}200{,}000 / 360{,}000 = 3.33$x EBITDA.

**Step 4: DCF**

Inputs: $g = 3\%$, $\tau = 24\%$, $c = 12\%$, $N = 5$. Discount rate $r = 4.2\% + 14\% + 4\% = 22.2\%$ (illustrative DGS10 at 4.2 percent).

Year 1 cash flow: $\text{CF}_1 = 360{,}000 - 43{,}200 - 0.24 \times (360{,}000 - 55{,}000) = 360{,}000 - 43{,}200 - 73{,}200 = 243{,}600$.

Year 1 is the run-rate EBITDA (no growth applied), later years grow at $g$ with D&A held flat, so $\text{CF}_2 = 250{,}512$ and $\text{CF}_5 = 272{,}517$. Explicit five-year PV at $r = 22.2\%$: about $727{,}121$.

Terminal value at year 5: $\text{CF}_6 = 272{,}517 \times 1.03 \approx 280{,}693$, $\text{TV}_5 = 280{,}693 / (0.222 - 0.03) \approx 1{,}461{,}941$. Discounted at $1.222^5 \approx 2.7249$, its present value is about $536{,}505$.

So $V_{\text{DCF}} \approx 727{,}121 + 536{,}505 = 1{,}263{,}626$.

These figures are rounded for reading. Unit tests must hit the exact values from the harness within $1 once the code is built.

**Step 5: Blended value**

$$
V = 0.50 \times 1{,}100{,}000 + 0.30 \times 1{,}263{,}626 + 0.20 \times 1{,}260{,}000 \approx 1{,}181{,}088
$$

Asking is about 1.6 percent above blended value.

**Step 6: SBA debt**

Equity injection: the buyer puts in $250{,}000 cash. That is above the 10 percent minimum of $120{,}000, so the cash figure governs. Loan $L = 1{,}200{,}000 - 250{,}000 = 950{,}000$.

Assumed prime (example) 6.75 percent, loan over $350k spread 3.00 percent, so $i = 9.75\%$, $j = 0.008125$, $n = 120$.

$$
\text{PMT} = \frac{950{,}000 \times 0.008125}{1 - 1.008125^{-120}} \approx \frac{7{,}718.75}{0.621323} \approx 12{,}423
$$

Annual debt service: $\text{DS} \approx 149{,}075$.

$$
\text{DSCR}_{\text{EBITDA}} = 360{,}000 / 149{,}075 \approx 2.41\text{x}
$$

$$
\text{DSCR}_{\text{owner}} = (440{,}000 - 90{,}000) / 149{,}075 \approx 2.35\text{x}
$$

The lender test uses the lower value, 2.35x, which clears the 1.25x minimum.

**Step 7: Score (illustrative component values)**

| Component | Weight | Component Value (0 to 100) | Weighted Points |
|---|---|---|---|
| Valuation gap | 25 | 77 | 19.25 |
| DSCR | 20 | 90 | 18.0 |
| Revenue trend | 15 | 60 | 9.0 |
| Concentration | 10 | 90 | 9.0 |
| Market context | 15 | 65 | 9.75 |
| Data quality | 10 | 75 | 7.5 |
| Operational risk | 5 | 80 | 4.0 |
| **Raw total** | 100 | | **76.5** |

Valuation gap check: asking is 1.6 percent above blended value, which sits at $(1.6 + 10) / 50 = 0.23$ of the way from the top score to zero, so the component is about 77. DSCR check: $(2.35 - 1.0) / 1.5 \times 100 = 90$.

Red flags on this listing: add-back ratio above 0.40 (flag), one penalty of 5. Final score: $76.5 - 5 = 71.5$.

## 8. Sensitivity Tables

The report shows, at minimum:

- Price vs. SDE multiple (grid of 2.0x to 3.5x against asking price)
- Price vs. discount rate (grid of 18 to 26 percent against terminal growth of 2 to 4 percent)
- Interest rate vs. DSCR (prime plus or minus 150 basis points)

## 9. Units and Rounding

- Money is stored as float in USD during the MVP, rounded only for display. A decimal type is a v1.0 decision.
- Percent values are stored as decimals (0.03 means 3 percent).
