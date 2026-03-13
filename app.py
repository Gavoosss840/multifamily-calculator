# =============================================================================
#  HUGO'S MULTIFAMILY RENTAL CALCULATOR
#  Run with:  streamlit run app.py
# =============================================================================

import math, json, os
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    import numpy_financial as npf
    HAS_NPF = True
except ImportError:
    HAS_NPF = False

st.set_page_config(page_title="Multifamily Pro | Hugo", page_icon="🏢", layout="wide", initial_sidebar_state="expanded")
os.makedirs("profiles", exist_ok=True)

st.markdown("""
<style>
  [data-testid="metric-container"] { background: #0d1f35; border: 1px solid #1e3352; border-radius: 6px; padding: 10px 14px; }
  [data-testid="stMetricValue"]  { color: #4a9eff !important; font-size: 1.25rem !important; }
  [data-testid="stMetricLabel"]  { color: #6b8aa8 !important; font-size: 0.72rem !important; letter-spacing: 1.5px; text-transform: uppercase; }
  .stTabs [data-baseweb="tab-list"] { background: #0d1f35; border-radius: 8px; padding: 4px; gap: 4px; }
  .stTabs [data-baseweb="tab"]      { background: transparent; color: #6b8aa8; border-radius: 6px; padding: 6px 16px; font-size: 0.8rem; }
  .stTabs [aria-selected="true"]    { background: #1e3352 !important; color: #4a9eff !important; }
  [data-testid="stSidebar"]         { background: #081628; border-right: 1px solid #1e3352; }
  [data-testid="stSidebar"] label   { font-size: 0.75rem; letter-spacing: 1px; text-transform: uppercase; color: #ffffff !important; }
  [data-testid="stSidebar"] p       { color: #ffffff !important; }
  [data-testid="stSidebar"] .stMarkdown { color: #ffffff !important; }
  details { background: #0d1f35 !important; border: 1px solid #1e3352 !important; border-radius: 6px; }
  .stButton > button { background: #1e3352; color: #4a9eff; border: 1px solid #2a4a72; border-radius: 6px; font-size: 0.8rem; }
  .stButton > button:hover { background: #2a4a72; border-color: #4a9eff; }
  .stDownloadButton > button { background: #10b981 !important; color: #000 !important; font-weight: 700; }
  details div { color: #ffffff !important; }
  details summary span { color: #ffffff !important; }
  details[open] summary span { color: #000000 !important; }
  details summary span { color: #ef4444 !important; }
  details[open] summary span { color: #ef4444 !important; }
  details code { color: #ef4444 !important; }  
            
</style>
""", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────
def usd(v):
    if v is None or (isinstance(v, float) and not math.isfinite(v)): return "—"
    return f"${v:,.0f}"
def pct(v, d=2):
    if v is None or (isinstance(v, float) and not math.isfinite(v)): return "—"
    return f"{v:.{d}f}%"
def num(v, d=2):
    if v is None or (isinstance(v, float) and not math.isfinite(v)): return "—"
    return f"{v:.{d}f}"
def ratio_status(v, good, bad, higher_is_better=True):
    if v is None or (isinstance(v, float) and not math.isfinite(v)): return "ℹ️"
    if higher_is_better:
        return "🟢" if v >= good else ("🔴" if v <= bad else "🟡")
    else:
        return "🟢" if v <= good else ("🔴" if v >= bad else "🟡")

PLOT_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e2f0ff", family="monospace"),
    margin=dict(t=50, b=40, l=40, r=20),
    legend=dict(orientation="h", y=-0.15),
    xaxis=dict(showgrid=False, zeroline=False),
    yaxis=dict(showgrid=True, gridcolor="#1e3352", zeroline=False),
)

# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🏢 Property Setup")
    prop_name    = st.text_input("Property Name",   "My Multifamily Deal")
    prop_address = st.text_input("Street Address",  "123 Main St, San Antonio TX")
    prop_zip     = st.text_input("ZIP Code",        "78201")

    st.divider()
    st.markdown("### 💰 Financing Mode")
    fin_radio = st.radio("Mode", ["Cash Only", "Loan (Standard)", "Both — Primary + Secondary"],
                         index=1, label_visibility="collapsed")
    mode_key = "Cash" if "Cash" in fin_radio else ("Both" if "Both" in fin_radio else "Loan")

    st.divider()
    st.markdown("### 🏷️ Acquisition")
    purchase_price   = st.number_input("Purchase Price ($)",            0, 20_000_000, 850_000, 5_000)
    closing_cost_pct = st.slider(      "Closing Costs (%)",             0.0, 6.0, 3.0, 0.1)
    rehab_cost       = st.number_input("Rehab / CapEx at Purchase ($)", 0, 1_000_000, 25_000, 1_000)

    if mode_key in ("Loan", "Both"):
        st.markdown("### 🏦 Primary Loan")
        down_pct      = st.slider("Down Payment (%)", 5, 100, 25, 1)
        interest_rate = st.number_input("Interest Rate (%)", 0.0, 20.0, 6.75, 0.05)
        amort_years   = st.selectbox("Amortization Period", [10, 15, 20, 25, 30], index=4)
    else:
        down_pct, interest_rate, amort_years = 100, 0.0, 30

    second_loan_amount, second_rate, second_amort = 0, 8.0, 20
    if mode_key == "Both":
        st.markdown("### 🏦 Secondary / Seller Financing")
        second_loan_amount = st.number_input("2nd Loan Amount ($)", 0, 1_000_000, 50_000, 1_000)
        second_rate        = st.number_input("2nd Loan Rate (%)",   0.0, 20.0, 8.0, 0.1)
        second_amort       = st.selectbox("2nd Amortization", [5, 10, 15, 20], index=1)

    st.divider()
    st.markdown("### 🤝 Partnership")
    ownership_pct = st.slider("Your Ownership Share (%)", 1, 100, 100, 1,
                              help="Your % of the deal — adjusts your share of CF, profit & returns")
    st.divider()
    st.markdown("### 🏘️ Income")
    units            = st.number_input("Number of Units",               1, 500,    6,     1)
    avg_monthly_rent = st.number_input("Avg Monthly Rent / Unit ($)",   0, 20_000, 1_200, 25)
    vacancy_pct      = st.slider(      "Vacancy Rate (%)",              0.0, 40.0, 6.0, 0.5)
    other_income_mo  = st.number_input("Other Income / Month ($)",      0, 10_000, 200,  50,
                                       help="Parking, laundry, late fees…")

    st.divider()
    st.markdown("### 📊 Operating Expenses (Annual)")
    with st.expander("Itemize Expenses", expanded=True):
        prop_tax  = st.number_input("Property Tax ($)",          0, 200_000, 8_000, 100)
        insurance = st.number_input("Insurance ($)",             0, 100_000, 3_500, 100)
        maint     = st.number_input("Maintenance / Repairs ($)", 0, 100_000, 4_000, 100)
        mgmt      = st.number_input("Property Management ($)",   0, 100_000, 3_600, 100)
        utils     = st.number_input("Utilities — owner-paid ($)",0, 100_000, 1_200, 100)
        capex_res = st.number_input("CapEx Reserve ($)",         0, 100_000, 2_400, 100)
        other_exp = st.number_input("Other Expenses ($)",        0, 100_000,   600, 100)

    expenses = {
        "Property Tax": prop_tax, "Insurance": insurance,
        "Maintenance": maint,     "Management": mgmt,
        "Utilities": utils,       "CapEx Reserve": capex_res, "Other": other_exp,
    }

    st.divider()
    st.markdown("### 📈 Growth & Exit")
    rent_growth       = st.slider("Annual Rent Growth (%)",    0.0, 10.0, 3.0, 0.1)
    expense_growth    = st.slider("Annual Expense Growth (%)", 0.0, 10.0, 2.5, 0.1)
    appreciation_rate = st.slider("Annual Appreciation (%)",   0.0, 10.0, 3.0, 0.1)
    exit_cap_rate     = st.number_input("Exit Cap Rate (%)",   1.0, 20.0, 5.5, 0.1)
    hold_years        = st.slider("Hold Period (years)",       1, 30, 5, 1)

    st.divider()
    st.markdown("### 🔄 Refinance")
    with st.expander("Refi Settings"):
        refi_ltv   = st.slider("Refi LTV (%)", 50, 80, 70, 1)
        refi_rate  = st.number_input("Refi Rate (%)", 0.0, 20.0, 6.5, 0.1)
        refi_amort = st.selectbox("Refi Amortization", [15, 20, 25, 30], index=3)

    st.divider()
    st.markdown("### 🔨 BRRRR")
    show_brrrr = st.checkbox("Enable BRRRR Analysis", value=False)
    if show_brrrr:
        arv              = st.number_input("After Repair Value (ARV) ($)", 0, 20_000_000, int(purchase_price * 1.2), 5_000)
        brrrr_refi_ltv   = st.slider("BRRRR Refi LTV (%)", 50, 80, 75, 1)
        brrrr_refi_rate  = st.number_input("BRRRR Refi Rate (%)", 0.0, 20.0, 6.5, 0.1)
        brrrr_refi_amort = st.selectbox("BRRRR Refi Amort", [15, 20, 25, 30], index=3)
    else:
        arv, brrrr_refi_ltv, brrrr_refi_rate, brrrr_refi_amort = purchase_price, 75, 6.5, 30

# ══════════════════════════════════════════════════════════════════════════════
#  CALCULATION ENGINE
# ══════════════════════════════════════════════════════════════════════════════
def mortgage_payment(principal, annual_rate_pct, n_months):
    if principal <= 0: return 0.0
    if annual_rate_pct == 0: return principal / n_months
    r = annual_rate_pct / 100 / 12
    return principal * (r * (1 + r) ** n_months) / ((1 + r) ** n_months - 1)

def build_amortization(principal, annual_rate_pct, n_months):
    r   = annual_rate_pct / 100 / 12
    pmt = mortgage_payment(principal, annual_rate_pct, n_months)
    rows, balance = [], principal
    for m in range(1, n_months + 1):
        interest     = balance * r
        principal_pd = pmt - interest
        balance      = max(0.0, balance - principal_pd)
        rows.append({"Month": m, "Year": math.ceil(m / 12),
                     "Payment": pmt, "Principal": principal_pd,
                     "Interest": interest, "Balance": balance})
    return pd.DataFrame(rows)

def compute_irr(cash_flows):
    if HAS_NPF:
        try:
            result = npf.irr(cash_flows)
            return result * 100 if math.isfinite(result) else None
        except Exception:
            pass
    rate = 0.10
    for _ in range(2000):
        npv  = sum(cf / (1 + rate) ** i for i, cf in enumerate(cash_flows))
        dnpv = sum(-i * cf / (1 + rate) ** (i + 1) for i, cf in enumerate(cash_flows))
        if abs(dnpv) < 1e-12: break
        rate -= npv / dnpv
        if rate <= -1: return None
    return rate * 100 if math.isfinite(rate) else None

def run_calculations(p):
    closing_costs = p["purchase_price"] * p["closing_cost_pct"] / 100
    total_acq     = p["purchase_price"] + closing_costs + p["rehab_cost"]
    mode = p["financing_mode"]
    if mode == "Cash":
        down_payment = p["purchase_price"]; loan_amount = 0.0
        monthly_mortgage = 0.0; annual_debt_service = 0.0
    elif mode == "Loan":
        down_payment = p["purchase_price"] * p["down_pct"] / 100
        loan_amount  = p["purchase_price"] - down_payment
        monthly_mortgage    = mortgage_payment(loan_amount, p["interest_rate"], p["amort_years"] * 12)
        annual_debt_service = monthly_mortgage * 12
    else:
        down_payment = p["purchase_price"] * p["down_pct"] / 100
        loan1        = p["purchase_price"] - down_payment - p["second_loan_amount"]
        pmt1         = mortgage_payment(loan1, p["interest_rate"], p["amort_years"] * 12)
        pmt2         = mortgage_payment(p["second_loan_amount"], p["second_rate"], p["second_amort"] * 12)
        loan_amount         = loan1 + p["second_loan_amount"]
        monthly_mortgage    = pmt1 + pmt2
        annual_debt_service = monthly_mortgage * 12
    total_cash_invested = down_payment + closing_costs + p["rehab_cost"]
    gpr          = p["units"] * p["avg_monthly_rent"] * 12
    vacancy_loss = gpr * p["vacancy_pct"] / 100
    egi          = gpr - vacancy_loss + p["other_income_monthly"] * 12
    total_opex   = sum(p["expenses"].values())
    expense_ratio= (total_opex / egi * 100) if egi > 0 else 0.0
    noi          = egi - total_opex
    annual_cf    = noi - annual_debt_service
    monthly_cf   = annual_cf / 12
    cf_per_unit  = monthly_cf / p["units"] if p["units"] > 0 else 0.0
    cap_rate     = (noi / p["purchase_price"] * 100) if p["purchase_price"] > 0 else 0.0
    coc          = (annual_cf / total_cash_invested * 100) if total_cash_invested > 0 else 0.0
    dscr         = (noi / annual_debt_service) if annual_debt_service > 0 else float("inf")
    grm          = (p["purchase_price"] / gpr) if gpr > 0 else 0.0
    price_per_unit = p["purchase_price"] / p["units"] if p["units"] > 0 else 0.0
    rent_to_price  = (gpr / 12 / p["purchase_price"] * 100) if p["purchase_price"] > 0 else 0.0
    ltv          = (loan_amount / p["purchase_price"] * 100) if p["purchase_price"] > 0 else 0.0
    be_occ       = ((total_opex + annual_debt_service) / gpr * 100) if gpr > 0 else 0.0
    amort_df = None
    if loan_amount > 0 and mode != "Cash":
        amort_df = build_amortization(loan_amount, p["interest_rate"], p["amort_years"] * 12)
    projection, cum_cf = [], 0.0
    for y in range(1, p["hold_years"] + 1):
        rm = (1 + p["rent_growth"] / 100) ** (y - 1)
        em = (1 + p["expense_growth"] / 100) ** (y - 1)
        y_gpr  = gpr * rm
        y_egi  = y_gpr * (1 - p["vacancy_pct"] / 100) + p["other_income_monthly"] * 12
        y_opex = total_opex * em
        y_noi  = y_egi - y_opex
        y_cf   = y_noi - annual_debt_service
        cum_cf += y_cf
        y_cap  = (y_noi / p["purchase_price"] * 100) if p["purchase_price"] > 0 else 0.0
        y_val  = p["purchase_price"] * (1 + p["appreciation_rate"] / 100) ** y
        y_paydown = 0.0
        if amort_df is not None:
            y_paydown = float(amort_df[amort_df["Year"] == y]["Principal"].sum())
        projection.append({"Year": y, "GPR": y_gpr, "EGI": y_egi, "OpEx": y_opex,
                           "NOI": y_noi, "Debt Service": annual_debt_service,
                           "Cash Flow": y_cf, "Cap Rate": y_cap,
                           "Cum. Cash Flow": cum_cf, "Principal Paydown": y_paydown,
                           "Property Value": y_val})
    proj_df = pd.DataFrame(projection)
    exit_noi       = float(proj_df.iloc[-1]["NOI"]) if len(proj_df) > 0 else noi
    exit_value     = (exit_noi / (p["exit_cap_rate"] / 100)) if p["exit_cap_rate"] > 0 else 0.0
    total_paydown  = float(proj_df["Principal Paydown"].sum()) if len(proj_df) > 0 else 0.0
    remaining_loan = max(0.0, loan_amount - total_paydown)
    exit_equity    = exit_value - remaining_loan
    total_profit   = cum_cf + (exit_value - p["purchase_price"]) + total_paydown
    equity_multiple= ((total_cash_invested + total_profit) / total_cash_invested) if total_cash_invested > 0 else 0.0
    irr_flows = [-total_cash_invested]
    for row in projection[:-1]: irr_flows.append(row["Cash Flow"])
    if projection: irr_flows.append(projection[-1]["Cash Flow"] + exit_equity)
    irr = compute_irr(irr_flows)
    refi_loan    = p["purchase_price"] * p["refi_ltv"] / 100
    refi_pmt     = mortgage_payment(refi_loan, p["refi_rate"], p["refi_amort"] * 12)
    refi_ann_ds  = refi_pmt * 12
    refi_cf      = noi - refi_ann_ds
    refi_cashout = refi_loan - loan_amount
    new_cash_in  = total_cash_invested - max(0, refi_cashout)
    refi_coc     = (refi_cf / new_cash_in * 100) if new_cash_in > 0 else 0.0
    b_refi_loan  = p["arv"] * p["brrrr_refi_ltv"] / 100
    b_refi_pmt   = mortgage_payment(b_refi_loan, p["brrrr_refi_rate"], p["brrrr_refi_amort"] * 12)
    b_ann_ds     = b_refi_pmt * 12
    all_in_cost  = total_acq
    cash_recouped= b_refi_loan
    cash_left_in = max(0.0, all_in_cost - cash_recouped)
    brrrr_cf     = noi - b_ann_ds
    brrrr_coc    = (brrrr_cf / cash_left_in * 100) if cash_left_in > 0 else float("inf")
    equity_created = p["arv"] - all_in_cost
    return dict(
        closing_costs=closing_costs, total_acq=total_acq, total_cash_invested=total_cash_invested,
        down_payment=down_payment, loan_amount=loan_amount,
        monthly_mortgage=monthly_mortgage, annual_debt_service=annual_debt_service,
        gpr=gpr, vacancy_loss=vacancy_loss, egi=egi,
        total_opex=total_opex, expense_ratio=expense_ratio,
        noi=noi, annual_cf=annual_cf, monthly_cf=monthly_cf, cf_per_unit=cf_per_unit,
        cap_rate=cap_rate, coc=coc, dscr=dscr, grm=grm,
        price_per_unit=price_per_unit, rent_to_price=rent_to_price, ltv=ltv, be_occ=be_occ,
        amort_df=amort_df, proj_df=proj_df,
        exit_value=exit_value, exit_equity=exit_equity, total_paydown=total_paydown,
        remaining_loan=remaining_loan, total_profit=total_profit,
        equity_multiple=equity_multiple, irr=irr, cum_cf=cum_cf,
        refi_loan=refi_loan, refi_pmt=refi_pmt, refi_cashout=refi_cashout,
        refi_cf=refi_cf, refi_coc=refi_coc, refi_ann_ds=refi_ann_ds,
        arv=p["arv"], b_refi_loan=b_refi_loan, b_refi_pmt=b_refi_pmt,
        b_ann_ds=b_ann_ds, all_in_cost=all_in_cost,
        cash_recouped=cash_recouped, cash_left_in=cash_left_in,
        brrrr_cf=brrrr_cf, brrrr_coc=brrrr_coc, equity_created=equity_created,
    )

inputs = dict(
    purchase_price=purchase_price, closing_cost_pct=closing_cost_pct, rehab_cost=rehab_cost,
    financing_mode=mode_key, down_pct=down_pct, interest_rate=interest_rate, amort_years=amort_years,
    second_loan_amount=second_loan_amount, second_rate=second_rate, second_amort=second_amort,
    units=units, avg_monthly_rent=avg_monthly_rent, vacancy_pct=vacancy_pct,
    other_income_monthly=other_income_mo, expenses=expenses,
    rent_growth=rent_growth, expense_growth=expense_growth,
    appreciation_rate=appreciation_rate, exit_cap_rate=exit_cap_rate, hold_years=hold_years,
    refi_ltv=refi_ltv, refi_rate=refi_rate, refi_amort=refi_amort,
    arv=arv, brrrr_refi_ltv=brrrr_refi_ltv,
    brrrr_refi_rate=brrrr_refi_rate, brrrr_refi_amort=brrrr_refi_amort,
)
r = run_calculations(inputs)
own = ownership_pct / 100

# ══════════════════════════════════════════════════════════════════════════════
#  HEADER
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("# 🏢 Multifamily Pro — Hugo")
st.caption(f"📍 {prop_address}  ·  ZIP {prop_zip}  ·  {units} units  ·  Mode: **{mode_key}**")

c1,c2,c3,c4,c5,c6,c7 = st.columns(7)
with c1: st.metric("My Monthly CF",    usd(r["monthly_cf"] * own))
with c2: st.metric("My NOI Share",     usd(r["noi"] * own))
with c3: st.metric("Cap Rate",         pct(r["cap_rate"]))
with c4: st.metric("Cash-on-Cash",     pct(r["coc"]))
with c5: st.metric("DSCR",             num(r["dscr"]) if math.isfinite(r["dscr"]) else "∞")
with c6: st.metric("Equity Multiple",  f"{r['equity_multiple']:.2f}x")
with c7: st.metric("My IRR Share",     pct(r["irr"]) if r["irr"] else "—")
st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  TABS
# ══════════════════════════════════════════════════════════════════════════════
tabs = st.tabs([
    "📊 Dashboard",
    "🏦 Financing & Amortization",
    "📈 Projections & IRR",
    "🔄 Refinance",
    "🔨 BRRRR",
    "🌍 Market Data",
    "💾 Save / Load / PDF",
    "📖 Dictionary & Formulas",
])

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 1 — DASHBOARD
# ──────────────────────────────────────────────────────────────────────────────
with tabs[0]:
    st.subheader("P&L Summary")
    col_inc, col_exp, col_net = st.columns(3)
    with col_inc:
        st.markdown("**💵 Income**")
        st.markdown(f"Gross Potential Rent: **{usd(r['gpr'])}**")
        st.markdown(f"Vacancy Loss: `({usd(r['vacancy_loss'])})`")
        st.markdown(f"Other Income (annual): {usd(other_income_mo * 12)}")
        st.markdown(f"**Effective Gross Income: {usd(r['egi'])}**")
    with col_exp:
        st.markdown("**📤 Expenses**")
        for k, v in expenses.items():
            st.markdown(f"{k}: {usd(v)}")
        st.markdown(f"**Total OpEx: {usd(r['total_opex'])}** ({pct(r['expense_ratio'],1)} of EGI)")
    with col_net:
        st.markdown("**📊 Net**")
        st.markdown(f"NOI: **{usd(r['noi'])}**")
        st.markdown(f"Annual Debt Service: `({usd(r['annual_debt_service'])})`")
        st.markdown(f"**Annual Cash Flow: {usd(r['annual_cf'])}**")
        st.markdown(f"Monthly CF: {usd(r['monthly_cf'])}")
        st.markdown(f"CF / Unit / Month: {usd(r['cf_per_unit'])}")
        st.markdown(f"Total Cash Invested: {usd(r['total_cash_invested'])}")
        st.markdown(f"**My Share ({ownership_pct}%): {usd(r['annual_cf'] * own)} / yr  ·  {usd(r['monthly_cf'] * own)} / mo**")

    st.divider()
    st.subheader("Key Ratios")
    RATIOS = [
        ("Cap Rate",         r["cap_rate"],   pct(r["cap_rate"]),         6,    3,    True,  "NOI / Price. Target ≥ 6%."),
        ("Cash-on-Cash",     r["coc"],        pct(r["coc"]),              8,    4,    True,  "Annual CF / Cash Invested. Target ≥ 8%."),
        ("DSCR",             r["dscr"] if math.isfinite(r["dscr"]) else 99,
                             num(r["dscr"]) if math.isfinite(r["dscr"]) else "∞",
                                                                          1.25, 1.0,  True,  "NOI / Debt Service. Lenders need ≥ 1.25."),
        ("GRM",              r["grm"],        num(r["grm"],1),            10,   14,   False, "Price / Gross Rent. Lower = better."),
        ("Expense Ratio",    r["expense_ratio"], pct(r["expense_ratio"]), 50,   65,   False, "OpEx / EGI. Lower = better."),
        ("Rent-to-Price %",  r["rent_to_price"], pct(r["rent_to_price"],3),1.0, 0.7,  True,  "Monthly Rent / Price × 100. 1%+ ideal."),
        ("LTV",              r["ltv"],        pct(r["ltv"]),              75,   85,   False, "Loan / Value."),
        ("Break-Even Occ.",  r["be_occ"],     pct(r["be_occ"]),           75,   85,   False, "Min occupancy to cover all costs."),
        ("Price / Unit",     None,            usd(r["price_per_unit"]),   None, None, True,  "Acquisition cost per door."),
        ("CF / Unit / Mo",   None,            usd(r["cf_per_unit"]),      None, None, True,  "Net cash flow per door per month."),
    ]
    ratio_cols = st.columns(5)
    for i, (label, raw, display, good, bad, hib, tip) in enumerate(RATIOS):
        status = ratio_status(raw, good, bad, hib) if raw is not None else "ℹ️"
        with ratio_cols[i % 5]:
            st.metric(f"{status} {label}", display, help=tip)

    st.divider()
    ch1, ch2 = st.columns(2)
    with ch1:
        st.subheader("Expense Breakdown")
        fig_pie = go.Figure(go.Pie(
            labels=list(expenses.keys()), values=list(expenses.values()), hole=0.52,
            marker_colors=["#4a9eff","#7c3aed","#10b981","#f59e0b","#ef4444","#06b6d4","#8b5cf6"],
            textinfo="label+percent",
        ))
        fig_pie.update_layout(**{**PLOT_LAYOUT, "margin": dict(t=20,b=40,l=20,r=20)}, height=320,
                              uniformtext_minsize=10, uniformtext_mode="hide")
        fig_pie.update_traces(textfont_color="white", textfont_size=12)
        st.plotly_chart(fig_pie, use_container_width=True)
    with ch2:
        st.subheader("Capital Stack")
        fig_stack = go.Figure(go.Bar(
            x=["Debt", "Down Payment", "Closing Costs", "Rehab"],
            y=[r["loan_amount"], r["down_payment"], r["closing_costs"], rehab_cost],
            marker_color=["#ef4444","#4a9eff","#f59e0b","#10b981"],
            text=[usd(v) for v in [r["loan_amount"],r["down_payment"],r["closing_costs"],rehab_cost]],
            textposition="auto",
        ))
        fig_stack.update_layout(**{**PLOT_LAYOUT, "margin": dict(t=20,b=40,l=40,r=20)}, height=320, showlegend=False)
        st.plotly_chart(fig_stack, use_container_width=True)

    st.subheader("Income → NOI Waterfall")
    wf_vals = [r["gpr"], -r["vacancy_loss"], other_income_mo*12, -r["total_opex"], r["noi"]]
    fig_wf = go.Figure(go.Waterfall(
        x=["Gross Rent","Vacancy Loss","Other Income","Operating Expenses","NOI"],
        y=wf_vals, measure=["absolute","relative","relative","relative","total"],
        text=[usd(abs(v)) for v in wf_vals], textposition="outside",
        connector=dict(line=dict(color="#1e3352", width=1.5)),
        decreasing=dict(marker=dict(color="#ef4444")),
        increasing=dict(marker=dict(color="#22c55e")),
        totals=dict(marker=dict(color="#4a9eff")),
    ))
    fig_wf.update_layout(**PLOT_LAYOUT, height=360)
    st.plotly_chart(fig_wf, use_container_width=True)

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 2 — FINANCING & AMORTIZATION
# ──────────────────────────────────────────────────────────────────────────────
with tabs[1]:
    if mode_key == "Cash":
        st.info("💵 All-cash purchase — no mortgage or debt service.")
        c1,c2,c3 = st.columns(3)
        with c1: st.metric("Total Cash Deployed", usd(r["total_cash_invested"]))
        with c2: st.metric("Cap Rate (unlevered)", pct(r["cap_rate"]))
        with c3: st.metric("Cash Yield", pct(r["coc"]))
    else:
        st.subheader("Loan Summary")
        c1,c2,c3,c4,c5 = st.columns(5)
        with c1: st.metric("Loan Amount",        usd(r["loan_amount"]))
        with c2: st.metric("Monthly P&I",         usd(r["monthly_mortgage"]))
        with c3: st.metric("Annual Debt Service", usd(r["annual_debt_service"]))
        with c4: st.metric("LTV",                 pct(r["ltv"]))
        with c5: st.metric("Total Cash Invested", usd(r["total_cash_invested"]))
        st.divider()
        if r["amort_df"] is not None:
            ann = (r["amort_df"].groupby("Year")
                   .agg(Total_Payments=("Payment","sum"), Principal_Paid=("Principal","sum"),
                        Interest_Paid=("Interest","sum"), Remaining_Balance=("Balance","last"))
                   .reset_index())
            ann.columns = ["Year","Total Payments","Principal Paid","Interest Paid","Remaining Balance"]
            disp_ann = ann.head(hold_years + 5).copy()
            for col in ["Total Payments","Principal Paid","Interest Paid","Remaining Balance"]:
                disp_ann[col] = disp_ann[col].apply(usd)
            st.subheader("Amortization Schedule (Annual)")
            st.dataframe(disp_ann, use_container_width=True, hide_index=True)
            ann_raw = (r["amort_df"].groupby("Year")
                       .agg(Principal=("Principal","sum"), Interest=("Interest","sum"), Balance=("Balance","last"))
                       .reset_index())
            cha, chb = st.columns(2)
            with cha:
                fig_pi = go.Figure()
                fig_pi.add_trace(go.Bar(name="Principal", x=ann_raw["Year"], y=ann_raw["Principal"], marker_color="#22c55e"))
                fig_pi.add_trace(go.Bar(name="Interest",  x=ann_raw["Year"], y=ann_raw["Interest"],  marker_color="#ef4444"))
                fig_pi.update_layout(**PLOT_LAYOUT, barmode="stack", title="Principal vs. Interest by Year",
                                     height=360, xaxis_title="Year", yaxis_title="$")
                st.plotly_chart(fig_pi, use_container_width=True)
            with chb:
                fig_bal = go.Figure(go.Scatter(
                    x=ann_raw["Year"], y=ann_raw["Balance"],
                    fill="tozeroy", line_color="#4a9eff", fillcolor="rgba(74,158,255,0.15)", name="Loan Balance",
                ))
                fig_bal.update_layout(**PLOT_LAYOUT, title="Remaining Loan Balance", height=360,
                                      xaxis_title="Year", yaxis_title="$")
                st.plotly_chart(fig_bal, use_container_width=True)
            ann_raw["Equity"] = r["loan_amount"] - ann_raw["Balance"]
            fig_eq = go.Figure(go.Scatter(
                x=ann_raw["Year"], y=ann_raw["Equity"],
                fill="tozeroy", line_color="#10b981", fillcolor="rgba(16,185,129,0.15)", name="Equity via Paydown",
            ))
            fig_eq.update_layout(**PLOT_LAYOUT, title="Cumulative Equity via Principal Paydown",
                                  height=300, xaxis_title="Year", yaxis_title="$")
            st.plotly_chart(fig_eq, use_container_width=True)

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 3 — PROJECTIONS & IRR
# ──────────────────────────────────────────────────────────────────────────────
with tabs[2]:
    st.subheader(f"{hold_years}-Year Forward Projection")
    df = r["proj_df"].copy()
    disp = df[["Year","NOI","Cash Flow","Cum. Cash Flow","Cap Rate","Property Value"]].copy()
    disp["NOI"]            = disp["NOI"].apply(usd)
    disp["Cash Flow"]      = disp["Cash Flow"].apply(usd)
    disp["Cum. Cash Flow"] = disp["Cum. Cash Flow"].apply(usd)
    disp["Cap Rate"]       = disp["Cap Rate"].apply(pct)
    disp["Property Value"] = disp["Property Value"].apply(usd)
    st.dataframe(disp, use_container_width=True, hide_index=True)
    st.divider()
    ch1, ch2 = st.columns(2)
    with ch1:
        fig_cf = go.Figure()
        cf_colors = ["#22c55e" if v >= 0 else "#ef4444" for v in df["Cash Flow"]]
        fig_cf.add_trace(go.Bar(name="Annual CF", x=df["Year"], y=df["Cash Flow"], marker_color=cf_colors))
        fig_cf.add_trace(go.Scatter(name="Cumulative CF", x=df["Year"], y=df["Cum. Cash Flow"],
                                    line=dict(color="#4a9eff", width=2), yaxis="y2"))
        fig_cf.update_layout(**PLOT_LAYOUT, title="Cash Flow Projection", height=380,
                             xaxis_title="Year", yaxis_title="Annual CF ($)",
                             yaxis2=dict(title="Cumulative CF ($)", overlaying="y", side="right", showgrid=False, zeroline=False))
        st.plotly_chart(fig_cf, use_container_width=True)
    with ch2:
        fig_nv = go.Figure()
        fig_nv.add_trace(go.Scatter(name="NOI", x=df["Year"], y=df["NOI"],
                                    line=dict(color="#10b981", width=2.5),
                                    fill="tozeroy", fillcolor="rgba(16,185,129,0.10)"))
        fig_nv.add_trace(go.Scatter(name="Property Value", x=df["Year"], y=df["Property Value"],
                                    line=dict(color="#f59e0b", width=2, dash="dot"), yaxis="y2"))
        fig_nv.update_layout(**PLOT_LAYOUT, title="NOI & Appreciation", height=380,
                             xaxis_title="Year", yaxis_title="NOI ($)",
                             yaxis2=dict(title="Property Value ($)", overlaying="y", side="right", showgrid=False, zeroline=False))
        st.plotly_chart(fig_nv, use_container_width=True)

    st.divider()
    st.subheader("Exit & Total Returns")
    c1,c2,c3,c4,c5 = st.columns(5)
    with c1: st.metric("Exit Value",        usd(r["exit_value"]))
    with c2: st.metric("Total Profit",      usd(r["total_profit"]))
    with c3: st.metric("Equity Multiple",   f"{r['equity_multiple']:.2f}x")
    with c4: st.metric("IRR",               pct(r["irr"]) if r["irr"] else "—")
    with c5: st.metric("Principal Paydown", usd(r["total_paydown"]))

    apprecn = r["exit_value"] - purchase_price
    fig_ret = go.Figure(go.Waterfall(
        x=["Cash Invested","Cumulative CF","Appreciation","Principal Paydown","Net Profit"],
        y=[-r["total_cash_invested"], r["cum_cf"], apprecn, r["total_paydown"], r["total_profit"]],
        measure=["absolute","relative","relative","relative","total"],
        text=[usd(abs(v)) for v in [-r["total_cash_invested"],r["cum_cf"],apprecn,r["total_paydown"],r["total_profit"]]],
        textposition="outside",
        connector=dict(line=dict(color="#1e3352", width=1.5)),
        decreasing=dict(marker=dict(color="#ef4444")),
        increasing=dict(marker=dict(color="#22c55e")),
        totals=dict(marker=dict(color="#4a9eff")),
    ))
    fig_ret.update_layout(**PLOT_LAYOUT, height=400, title="Return Waterfall — Where Does Profit Come From?")
    st.plotly_chart(fig_ret, use_container_width=True)

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 4 — REFINANCE
# ──────────────────────────────────────────────────────────────────────────────
with tabs[3]:
    st.subheader("Cash-Out Refinance Analysis")
    c1,c2,c3,c4 = st.columns(4)
    with c1: st.metric("New Loan Amount",      usd(r["refi_loan"]))
    with c2: st.metric("Cash-Out Proceeds",    usd(r["refi_cashout"]))
    with c3: st.metric("New Monthly Payment",  usd(r["refi_pmt"]))
    with c4: st.metric("New Annual Debt Svc",  usd(r["refi_ann_ds"]))
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Before Refinance")
        st.metric("Annual Cash Flow",    usd(r["annual_cf"]))
        st.metric("Cash-on-Cash",        pct(r["coc"]))
        st.metric("Annual Debt Service", usd(r["annual_debt_service"]))
    with col2:
        st.markdown("#### After Refinance")
        delta_cf = r["refi_cf"] - r["annual_cf"]
        st.metric("Annual Cash Flow",    usd(r["refi_cf"]),
                  delta=f"{'+' if delta_cf>=0 else ''}{usd(delta_cf)}")
        st.metric("Post-Refi CoC",       pct(r["refi_coc"]))
        st.metric("New Annual Debt Svc", usd(r["refi_ann_ds"]))
    st.divider()
    if r["refi_cashout"] >= 0:
        st.success(f"💰 This refi releases **{usd(r['refi_cashout'])}** to redeploy into your next acquisition.")
    else:
        st.warning(f"⚠️ Rate-and-term refi — you bring **{usd(-r['refi_cashout'])}** to closing.")
    fig_comp = go.Figure()
    fig_comp.add_trace(go.Bar(name="Before Refi",
                              x=["Annual CF","Annual Debt Svc"],
                              y=[r["annual_cf"], r["annual_debt_service"]],
                              marker_color="#4a9eff"))
    fig_comp.add_trace(go.Bar(name="After Refi",
                              x=["Annual CF","Annual Debt Svc"],
                              y=[r["refi_cf"], r["refi_ann_ds"]],
                              marker_color="#f59e0b"))
    fig_comp.update_layout(**PLOT_LAYOUT, barmode="group", title="Before vs. After Refinance", height=340)
    st.plotly_chart(fig_comp, use_container_width=True)

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 5 — BRRRR
# ──────────────────────────────────────────────────────────────────────────────
with tabs[4]:
    if not show_brrrr:
        st.info("☑️ Enable BRRRR Analysis in the sidebar to unlock this tab.")
    else:
        st.subheader("🔨 BRRRR Analysis")
        c1,c2,c3,c4 = st.columns(4)
        with c1: st.metric("All-In Cost",     usd(r["all_in_cost"]))
        with c2: st.metric("ARV",             usd(r["arv"]))
        with c3: st.metric("Equity Created",  usd(r["equity_created"]))
        with c4: st.metric("BRRRR Refi Loan", usd(r["b_refi_loan"]))
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Capital Recovery")
            st.metric("Cash Recouped via Refi", usd(r["cash_recouped"]))
            st.metric("Cash Left in Deal",      usd(r["cash_left_in"]))
            if r["cash_left_in"] <= 0:
                st.success("🎯 Full capital recovery — infinite CoC return!")
            else:
                st.metric("Post-BRRRR CoC", pct(r["brrrr_coc"]))
        with col2:
            st.markdown("#### Cash Flow After BRRRR Refi")
            st.metric("NOI",                 usd(r["noi"]))
            st.metric("Annual Debt Service", usd(r["b_ann_ds"]))
            st.metric("Annual Cash Flow",    usd(r["brrrr_cf"]))
            st.metric("Monthly Cash Flow",   usd(r["brrrr_cf"] / 12))
        fig_brrr = go.Figure(go.Funnel(
            y=["Purchase + Rehab + Closing", "After Repair Value (ARV)",
               f"Refi Loan ({brrrr_refi_ltv}% of ARV)", "Cash Left in Deal"],
            x=[r["all_in_cost"], r["arv"], r["b_refi_loan"], max(0, r["cash_left_in"])],
            textinfo="value+percent initial",
            marker_color=["#ef4444","#f59e0b","#4a9eff","#22c55e"],
        ))
        fig_brrr.update_layout(**PLOT_LAYOUT, title="BRRRR Capital Flow Funnel", height=380)
        st.plotly_chart(fig_brrr, use_container_width=True)

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 6 — MARKET DATA
# ──────────────────────────────────────────────────────────────────────────────
with tabs[5]:
    st.subheader("🌍 Market Data & Research Resources")
    st.caption(f"Quick links for market intelligence · ZIP **{prop_zip}**")
    z = prop_zip
    MARKET_DATA = {
        "📊 Cap Rates & Valuations": [
            ("CBRE Cap Rate Survey",         "https://www.cbre.com/insights/reports/cap-rate-survey",          "Quarterly national cap rate data by market & property type"),
            ("Marcus & Millichap Research",  "https://www.marcusmillichap.com/research",                      "Multifamily investment forecasts & per-market reports"),
            ("Trepp CRE Intelligence",       "https://www.trepp.com/trepptalk/category/commercial-real-estate","CMBS, cap rates & CRE trends"),
        ],
        "🏠 Rental Rates by ZIP": [
            ("Rentometer — Your ZIP",        f"https://www.rentometer.com/analysis/new?zip_code={z}&bedrooms=2","Instant rental comp analysis for your ZIP"),
            ("Zillow Rent Research",         "https://www.zillow.com/research/data/",                         "Zillow observed rent index & market trend data"),
            ("HUD Fair Market Rents",        "https://www.huduser.gov/portal/datasets/fmr.html",              "Official HUD FMR — key for Section 8 underwriting"),
            ("ApartmentList Rent Estimates", "https://www.apartmentlist.com/research/category/data-rent-estimates","Monthly rent index by city"),
        ],
        "📈 Economic & Market Data": [
            ("Freddie Mac Multifamily",      "https://mf.freddiemac.com/research/",                          "Multifamily research & origination forecasts"),
            ("NMHC Apartment Data",          "https://www.nmhc.org/research-insight/apartment-market-data/", "National vacancy, absorption, concessions tracking"),
            ("FRED Housing Data",            "https://fred.stlouisfed.org/categories/97",                    "Macro housing, vacancy, CPI rent indexes — free"),
        ],
        "💰 Financing Rates": [
            ("Freddie Mac PMMS Rate Survey", "https://www.freddiemac.com/pmms",                              "Weekly 30yr / 15yr mortgage rate benchmark"),
            ("SBA 504 Loan Program",         "https://www.sba.gov/funding-programs/loans/504-loans",         "SBA 504 — up to $5M at fixed rates for CRE"),
        ],
        "🏙️ San Antonio / Texas Triangle": [
            ("SABOR Market Stats",           "https://www.sabor.com/market-statistics",                      "San Antonio Board of Realtors — MLS stats"),
            ("Texas A&M RE Center",          "https://www.recenter.tamu.edu/data/housing-activity/#!/activity/MSA/San_Antonio-New_Braunfels","Academic Texas housing data — free"),
            ("LoopNet SA Multifamily",       "https://www.loopnet.com/search/apartment-buildings/san-antonio-tx/for-sale/","Active multifamily listings in San Antonio"),
        ],
    }
    for category, links in MARKET_DATA.items():
        st.markdown(f"### {category}")
        cols = st.columns(2)
        for idx, (name, url, desc) in enumerate(links):
            with cols[idx % 2]:
                st.markdown(f"**[{name}]({url})**")
                st.caption(desc)

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 7 — SAVE / LOAD / PDF
# ──────────────────────────────────────────────────────────────────────────────
with tabs[6]:
    st.subheader("💾 Profile Management")
    col_save, col_load = st.columns(2)

    with col_save:
        st.markdown("**Save Current Analysis**")
        safe_name = prop_name.replace(" ", "_").lower()
        save_as = st.text_input("File Name (no extension)", value=safe_name)
        if st.button("💾 Save to Disk", use_container_width=True):
            payload = {k: v for k, v in inputs.items()}
            payload["saved_at"] = datetime.now().isoformat()
            os.makedirs("profiles", exist_ok=True)
            with open(f"profiles/{save_as}.json", "w") as f:
                json.dump(payload, f, indent=2)
            st.success(f"✅ Saved → profiles/{save_as}.json")
        st.download_button(
            label="📥 Download JSON",
            data=json.dumps(inputs, indent=2, default=str).encode(),
            file_name=f"{save_as}.json", mime="application/json",
            use_container_width=True,
        )

    with col_load:
        st.markdown("**Load Saved Profile**")
        profile_files = sorted([f for f in os.listdir("profiles") if f.endswith(".json")]) if os.path.exists("profiles") else []
        if profile_files:
            selected = st.selectbox("Saved Profiles", profile_files)
            if st.button("📂 Preview Profile", use_container_width=True):
                with open(f"profiles/{selected}") as f:
                    st.json(json.load(f), expanded=False)
                st.info("Copy values from the preview into the sidebar to apply.")
        else:
            st.info("No profiles saved yet.")
        uploaded = st.file_uploader("Import JSON Profile", type=["json"])
        if uploaded:
            st.json(json.load(uploaded), expanded=False)
            st.info("Profile imported. Apply values via sidebar.")

    st.divider()
    st.subheader("📄 PDF Investment Report")
    if st.button("🖨️ Generate PDF Report", use_container_width=True, type="primary"):
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.patches as mpatches
            from fpdf import FPDF
            import tempfile, io

            BRAND_RED  = (93, 1, 19)
            BLACK      = (0, 0, 0)
            LIGHT_GRAY = (245, 245, 245)
            WHITE      = (255, 255, 255)
            MID_GRAY   = (120, 120, 120)

            # ── helper: save matplotlib fig to temp PNG ──────────────────
            def fig_to_png(fig):
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                            facecolor="white")
                plt.close(fig)
                buf.seek(0)
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                tmp.write(buf.read())
                tmp.close()
                return tmp.name

            # ── Chart 1 — Expense Donut ──────────────────────────────────
            fig1, ax1 = plt.subplots(figsize=(5, 4), facecolor="white")
            colors1 = ["#5d0113","#8b1a2b","#b22234","#cc3344",
                       "#e05566","#f07788","#f8aab0"]
            wedges, texts, autotexts = ax1.pie(
                list(expenses.values()), labels=list(expenses.keys()),
                autopct="%1.1f%%", colors=colors1, startangle=140,
                wedgeprops=dict(width=0.55),
                textprops=dict(color="black", fontsize=8),
            )
            for at in autotexts: at.set_color("white"); at.set_fontsize(7)
            ax1.set_title("Expense Breakdown", color="#5d0113",
                          fontweight="bold", fontsize=11)
            chart1_path = fig_to_png(fig1)

            # ── Chart 2 — Cash Flow Projection bars ──────────────────────
            df = r["proj_df"]
            fig2, ax2 = plt.subplots(figsize=(7, 3.5), facecolor="white")
            bar_colors = ["#5d0113" if v >= 0 else "#cc0000"
                          for v in df["Cash Flow"]]
            ax2.bar(df["Year"], df["Cash Flow"], color=bar_colors)
            ax2_twin = ax2.twinx()
            ax2_twin.plot(df["Year"], df["Cum. Cash Flow"],
                          color="#333333", linewidth=2, marker="o",
                          markersize=4, label="Cumulative CF")
            ax2.set_title("Cash Flow Projection", color="#5d0113",
                          fontweight="bold", fontsize=11)
            ax2.set_xlabel("Year"); ax2.set_ylabel("Annual CF ($)")
            ax2_twin.set_ylabel("Cumulative CF ($)")
            ax2.tick_params(colors="black"); ax2_twin.tick_params(colors="black")
            fig2.patch.set_facecolor("white")
            chart2_path = fig_to_png(fig2)

            # ── Chart 3 — Capital Stack ───────────────────────────────────
            fig3, ax3 = plt.subplots(figsize=(5, 3.5), facecolor="white")
            labels3 = ["Debt", "Down Payment", "Closing Costs", "Rehab"]
            vals3   = [r["loan_amount"], r["down_payment"],
                       r["closing_costs"], rehab_cost]
            colors3 = ["#5d0113","#8b1a2b","#b22234","#cc3344"]
            bars = ax3.bar(labels3, vals3, color=colors3)
            for bar, val in zip(bars, vals3):
                ax3.text(bar.get_x() + bar.get_width()/2,
                         bar.get_height() + max(vals3)*0.01,
                         usd(val), ha="center", va="bottom",
                         fontsize=7, color="black")
            ax3.set_title("Capital Stack", color="#5d0113",
                          fontweight="bold", fontsize=11)
            ax3.tick_params(colors="black")
            fig3.patch.set_facecolor("white")
            chart3_path = fig_to_png(fig3)

            # ── Chart 4 — NOI & Property Value ───────────────────────────
            fig4, ax4 = plt.subplots(figsize=(7, 3.5), facecolor="white")
            ax4.fill_between(df["Year"], df["NOI"],
                             alpha=0.4, color="#5d0113", label="NOI")
            ax4.plot(df["Year"], df["NOI"], color="#5d0113", linewidth=2)
            ax4b = ax4.twinx()
            ax4b.plot(df["Year"], df["Property Value"],
                      color="#333333", linewidth=2,
                      linestyle="--", label="Property Value")
            ax4.set_title("NOI & Property Value", color="#5d0113",
                          fontweight="bold", fontsize=11)
            ax4.set_xlabel("Year"); ax4.set_ylabel("NOI ($)")
            ax4b.set_ylabel("Property Value ($)")
            ax4.tick_params(colors="black"); ax4b.tick_params(colors="black")
            fig4.patch.set_facecolor("white")
            chart4_path = fig_to_png(fig4)

            # ════════════════════════════════════════════════════════════
            #  BUILD PDF
            # ════════════════════════════════════════════════════════════
            class Report(FPDF):
                def header(self):
                    self.set_fill_color(*WHITE)
                    self.rect(0, 0, 210, 297, "F")

                def section_title(self, txt):
                    self.set_fill_color(*LIGHT_GRAY)
                    self.set_text_color(*BRAND_RED)
                    self.set_font("Helvetica", "B", 11)
                    self.ln(4)
                    self.cell(0, 8, txt, ln=False, fill=True)
                    self.ln(9)
                    self.set_text_color(*BLACK)
                    self.set_font("Helvetica", "", 9)

                def row(self, label, value, shade=False):
                    if shade:
                        self.set_fill_color(*LIGHT_GRAY)
                    else:
                        self.set_fill_color(*WHITE)
                    self.set_font("Helvetica", "", 9)
                    self.set_text_color(*MID_GRAY)
                    self.cell(8)
                    self.cell(90, 5.5, label, fill=shade)
                    self.set_font("Helvetica", "B", 9)
                    self.set_text_color(*BLACK)
                    self.cell(0, 5.5, str(value), ln=True, fill=shade)

                def kpi_box(self, label, value):
                    self.set_fill_color(*LIGHT_GRAY)
                    self.set_draw_color(*BRAND_RED)
                    self.set_line_width(0.4)
                    self.rect(self.get_x(), self.get_y(), 42, 16, "DF")
                    self.set_font("Helvetica", "", 7)
                    self.set_text_color(*MID_GRAY)
                    self.cell(42, 6, label, align="C")
                    self.ln(6)
                    self.set_font("Helvetica", "B", 11)
                    self.set_text_color(*BRAND_RED)
                    x = self.get_x()
                    self.cell(42, 8, value, align="C")
                    self.set_xy(x + 42, self.get_y() - 6)
                    self.set_text_color(*BLACK)

            pdf = Report()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()

            # ── Logo + Title block ────────────────────────────────────────
            logo_path = "Logo.png"
            if os.path.exists(logo_path):
                pdf.image(logo_path, x=10, y=10, w=28)
            pdf.set_xy(42, 12)
            pdf.set_text_color(*BRAND_RED)
            pdf.set_font("Helvetica", "B", 18)
            pdf.cell(0, 8, "MULTIFAMILY INVESTMENT REPORT", ln=True)
            pdf.set_xy(42, 21)
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(*BLACK)
            pdf.cell(0, 6, prop_name, ln=True)
            pdf.set_xy(42, 27)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*MID_GRAY)
            pdf.cell(0, 5, f"{prop_address}  |  ZIP {prop_zip}  |  {units} units  |  Mode: {mode_key}", ln=True)
            pdf.set_xy(42, 32)
            pdf.cell(0, 5, f"Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}", ln=True)

            # Red divider line
            pdf.set_y(40)
            pdf.set_draw_color(*BRAND_RED)
            pdf.set_line_width(0.8)
            pdf.line(10, 40, 200, 40)
            pdf.ln(4)

            # ── KPI Row ───────────────────────────────────────────────────
            pdf.set_x(10)
            kpis_top = [
                ("MONTHLY CF",      usd(r["monthly_cf"])),
                ("NOI / YEAR",      usd(r["noi"])),
                ("CAP RATE",        pct(r["cap_rate"])),
                ("CASH-ON-CASH",    pct(r["coc"])),
                ("DSCR",            num(r["dscr"]) if math.isfinite(r["dscr"]) else "∞"),
                ("EQUITY MULTIPLE", f"{r['equity_multiple']:.2f}x"),
                ("IRR",             pct(r["irr"]) if r["irr"] else "—"),
            ]
            start_x = 10
            for label, value in kpis_top:
                pdf.set_xy(start_x, 46)
                pdf.kpi_box(label, value)
                start_x += 28
            pdf.ln(20)

            # ── P&L Section ───────────────────────────────────────────────
            pdf.section_title("  PROFIT & LOSS SUMMARY")
            shade = False
            for label, val in [
                ("Gross Potential Rent",    usd(r["gpr"])),
                ("Vacancy Loss",            f"({usd(r['vacancy_loss'])})"),
                ("Effective Gross Income",  usd(r["egi"])),
                ("Total Operating Expenses",usd(r["total_opex"])),
                ("Expense Ratio",           pct(r["expense_ratio"])),
                ("Net Operating Income",    usd(r["noi"])),
                ("Annual Debt Service",     f"({usd(r['annual_debt_service'])})"),
                ("Annual Cash Flow",        usd(r["annual_cf"])),
                ("Monthly Cash Flow",       usd(r["monthly_cf"])),
                ("CF per Unit per Month",   usd(r["cf_per_unit"])),
            ]:
                pdf.row(label, val, shade); shade = not shade

            # ── Acquisition & Financing ───────────────────────────────────
            pdf.ln(2)
            pdf.section_title("  ACQUISITION & FINANCING")
            shade = False
            for label, val in [
                ("Purchase Price",      usd(purchase_price)),
                ("Closing Costs",       usd(r["closing_costs"])),
                ("Rehab / CapEx",       usd(rehab_cost)),
                ("Total Acquisition",   usd(r["total_acq"])),
                ("Loan Amount",         usd(r["loan_amount"])),
                ("Down Payment",        usd(r["down_payment"])),
                ("Total Cash Invested", usd(r["total_cash_invested"])),
                ("Monthly Mortgage",    usd(r["monthly_mortgage"])),
                ("LTV",                 pct(r["ltv"])),
            ]:
                pdf.row(label, val, shade); shade = not shade

            # ── Key Ratios ────────────────────────────────────────────────
            pdf.ln(2)
            pdf.section_title("  KEY INVESTMENT RATIOS")
            shade = False
            for label, val in [
                ("Cap Rate",           pct(r["cap_rate"])),
                ("Cash-on-Cash",       pct(r["coc"])),
                ("DSCR",               num(r["dscr"]) if math.isfinite(r["dscr"]) else "∞"),
                ("GRM",                num(r["grm"], 1)),
                ("Rent-to-Price",      pct(r["rent_to_price"], 3)),
                ("Break-Even Occ.",    pct(r["be_occ"])),
                ("Price per Unit",     usd(r["price_per_unit"])),
            ]:
                pdf.row(label, val, shade); shade = not shade

            # ── Charts Page ───────────────────────────────────────────────
            pdf.add_page()
            if os.path.exists(logo_path):
                pdf.image(logo_path, x=10, y=10, w=18)
            pdf.set_xy(32, 13)
            pdf.set_text_color(*BRAND_RED)
            pdf.set_font("Helvetica", "B", 13)
            pdf.cell(0, 7, "CHARTS & VISUAL ANALYSIS", ln=True)
            pdf.set_draw_color(*BRAND_RED)
            pdf.line(10, 23, 200, 23)
            pdf.ln(6)

            pdf.image(chart1_path, x=10,  y=28,  w=88)
            pdf.image(chart3_path, x=108, y=28,  w=88)
            pdf.image(chart2_path, x=10,  y=118, w=88)
            pdf.image(chart4_path, x=108, y=118, w=88)

            # ── Projection Table ──────────────────────────────────────────
            pdf.set_y(210)
            pdf.set_text_color(*BRAND_RED)
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_fill_color(*LIGHT_GRAY)
            pdf.cell(0, 8, "  YEAR-BY-YEAR PROJECTION", ln=True, fill=True)
            pdf.ln(2)
            col_w = [14, 32, 32, 32, 24, 38]
            headers = ["Year","NOI","Cash Flow","Cum. CF","Cap Rate","Prop. Value"]
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*WHITE)
            pdf.set_fill_color(*BRAND_RED)
            pdf.set_x(10)
            for h, w in zip(headers, col_w):
                pdf.cell(w, 6, h, fill=True, align="C")
            pdf.ln()
            shade = False
            for _, row_data in r["proj_df"].iterrows():
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(*BLACK)
                pdf.set_fill_color(*LIGHT_GRAY if shade else WHITE)
                pdf.set_x(10)
                pdf.cell(col_w[0], 5.5, str(int(row_data["Year"])),   fill=shade, align="C")
                pdf.cell(col_w[1], 5.5, usd(row_data["NOI"]),         fill=shade, align="R")
                pdf.cell(col_w[2], 5.5, usd(row_data["Cash Flow"]),   fill=shade, align="R")
                pdf.cell(col_w[3], 5.5, usd(row_data["Cum. Cash Flow"]), fill=shade, align="R")
                pdf.cell(col_w[4], 5.5, pct(row_data["Cap Rate"]),    fill=shade, align="C")
                pdf.cell(col_w[5], 5.5, usd(row_data["Property Value"]), fill=shade, align="R")
                pdf.ln()
                shade = not shade

            # ── Exit Analysis ─────────────────────────────────────────────
            pdf.add_page()
            if os.path.exists(logo_path):
                pdf.image(logo_path, x=10, y=10, w=18)
            pdf.set_xy(32, 13)
            pdf.set_text_color(*BRAND_RED)
            pdf.set_font("Helvetica", "B", 13)
            pdf.cell(0, 7, "EXIT ANALYSIS & TOTAL RETURNS", ln=True)
            pdf.set_draw_color(*BRAND_RED)
            pdf.line(10, 23, 200, 23)
            pdf.ln(6)
            pdf.section_title("  EXIT SUMMARY")
            shade = False
            for label, val in [
                ("Hold Period",         f"{hold_years} years"),
                ("Exit Cap Rate",       pct(exit_cap_rate)),
                ("Projected Exit Value",usd(r["exit_value"])),
                ("Principal Paydown",   usd(r["total_paydown"])),
                ("Cumulative Cash Flow",usd(r["cum_cf"])),
                ("Total Profit",        usd(r["total_profit"])),
                ("Equity Multiple",     f"{r['equity_multiple']:.2f}x"),
                ("IRR",                 pct(r["irr"]) if r["irr"] else "—"),
            ]:
                pdf.row(label, val, shade); shade = not shade

            # ── Footer ────────────────────────────────────────────────────
            pdf.set_y(-15)
            pdf.set_draw_color(*BRAND_RED)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*MID_GRAY)
            pdf.cell(0, 8, "B. Horizon Properties LLC  |  Personal investment analysis  |  Not financial advice.", align="C")

            # ── Output ────────────────────────────────────────────────────
            pdf_output = pdf.output(dest="S")
            pdf_bytes  = pdf_output.encode("latin-1") if isinstance(pdf_output, str) else bytes(pdf_output)

            st.download_button(
                label="⬇️ Download PDF Report",
                data=pdf_bytes,
                file_name=f"{safe_name}_BHorizon_report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
            st.success("✅ PDF ready — click above to download.")

        except ImportError as e:
            st.error(f"Missing library: {e}. Run: pip install fpdf2 matplotlib")
        except Exception as e:
            st.error(f"PDF error: {e}")
# ──────────────────────────────────────────────────────────────────────────────
#  TAB 8 — DICTIONARY & FORMULAS
# ──────────────────────────────────────────────────────────────────────────────
with tabs[7]:
    st.subheader("📖 Real Estate Investment Dictionary & Formula Reference")
    st.caption("Every metric used in this calculator — definition, formula, benchmarks.")

    GLOSSARY = {
        "💰 Income & Revenue": [
            ("Gross Potential Rent (GPR)",
             "Total rent income if every unit is occupied 100% of the time at market rate.",
             "Units × Avg Monthly Rent × 12",
             "—"),
            ("Vacancy Loss",
             "Lost income due to empty units or non-payment. Applied as a % of GPR.",
             "GPR × Vacancy Rate %",
             "5–8% in stable markets, 10–15% in weaker markets"),
            ("Effective Gross Income (EGI)",
             "Actual income collected after accounting for vacancy, plus any other income streams.",
             "GPR − Vacancy Loss + Other Income",
             "—"),
            ("Other Income",
             "Non-rent revenue: laundry, parking, storage, late fees, pet fees.",
             "Sum of all ancillary income per month × 12",
             "Typically $50–$300/unit/year"),
        ],
        "📤 Expenses": [
            ("Operating Expenses (OpEx)",
             "All costs to run the property excluding debt service and income taxes.",
             "Property Tax + Insurance + Maintenance + Mgmt + Utilities + CapEx + Other",
             "35–50% of EGI for well-run properties"),
            ("Expense Ratio",
             "What percentage of income is consumed by operating costs. Lower = more efficient.",
             "Total OpEx / EGI × 100",
             "Target < 50%. Above 65% = warning sign."),
            ("CapEx Reserve",
             "Money set aside for major capital expenditures: roof, HVAC, plumbing, appliances.",
             "Typically $500–$1,500/unit/year depending on age",
             "$800–$1,200/unit/year is standard"),
            ("Property Management Fee",
             "Fee paid to a property manager, typically a % of collected rent.",
             "Usually 8–12% of gross collected rents",
             "8% standard, 10–12% for smaller portfolios"),
        ],
        "📊 Core Performance Metrics": [
            ("Net Operating Income (NOI)",
             "The single most important metric. Profit from operations before debt service.",
             "EGI − Total Operating Expenses",
             "Must be positive. Higher = better. Drives valuation."),
            ("Cash Flow",
             "Money left in your pocket after ALL expenses including mortgage payments.",
             "NOI − Annual Debt Service",
             "Target > $100–$200/unit/month minimum"),
            ("Cash Flow per Unit per Month",
             "Normalizes cash flow across different deal sizes. Key for portfolio comparison.",
             "Annual Cash Flow / Units / 12",
             "Target ≥ $100/door/month"),
        ],
        "📐 Key Investment Ratios": [
            ("Cap Rate (Capitalization Rate)",
             "Return on investment assuming all-cash purchase. Used to value and compare properties.",
             "NOI / Purchase Price × 100",
             "4–5% = expensive market. 6–8% = healthy. 9%+ = high-yield/higher risk."),
            ("Cash-on-Cash Return (CoC)",
             "Actual cash yield on the equity you deployed. The real-world return for leveraged investors.",
             "Annual Cash Flow / Total Cash Invested × 100",
             "Target ≥ 8%. Below 5% = weak deal."),
            ("DSCR — Debt Service Coverage Ratio",
             "How many times NOI covers the mortgage payment. The #1 metric lenders care about.",
             "NOI / Annual Debt Service",
             "Lenders require ≥ 1.25. Below 1.0 = property loses money after debt."),
            ("GRM — Gross Rent Multiplier",
             "Quick and dirty valuation tool. How many years of gross rent = purchase price.",
             "Purchase Price / Gross Annual Rent",
             "Lower = better deal. < 8 = strong. 10–14 = moderate. > 15 = expensive."),
            ("Rent-to-Price Ratio",
             "Monthly rent as a % of purchase price. The '1% rule' comes from this.",
             "Monthly Gross Rent / Purchase Price × 100",
             "1%+ = strong cash flow potential. 0.7–1% = moderate. Below 0.5% = tough."),
            ("Break-Even Occupancy",
             "The minimum occupancy rate needed to cover ALL costs including mortgage.",
             "(Total OpEx + Annual Debt Service) / GPR × 100",
             "Target < 75%. Above 85% = fragile deal with no margin for error."),
            ("Price per Unit",
             "Normalizes acquisition cost. Key for comparing multifamily deals of different sizes.",
             "Purchase Price / Number of Units",
             "Varies by market. San Antonio: $60K–$120K/unit typical."),
        ],
        "🏦 Financing & Leverage": [
            ("LTV — Loan-to-Value",
             "How much of the property is financed vs. owned outright.",
             "Loan Amount / Purchase Price × 100",
             "Lenders typically max at 75–80% for investment properties."),
            ("Down Payment",
             "Equity you bring to closing. Remaining purchase price is financed.",
             "Purchase Price × Down Payment %",
             "Investment properties: typically 20–30% required."),
            ("P&I Payment",
             "Monthly mortgage payment covering principal reduction and interest charges.",
             "Loan × (r(1+r)^n) / ((1+r)^n − 1)   where r = monthly rate, n = total months",
             "—"),
            ("Amortization",
             "The process of paying off a loan through regular payments over time.",
             "Each payment = Interest on remaining balance + Principal reduction",
             "30yr most common. 15–20yr builds equity faster but higher payments."),
            ("Interest-Only Period",
             "Period where payments cover only interest, no principal reduction.",
             "Monthly Payment = Loan × (Annual Rate / 12)",
             "Common in bridge loans. Max cash flow short term but no equity build."),
        ],
        "📈 Returns & Exit": [
            ("IRR — Internal Rate of Return",
             "The annualized return accounting for timing of all cash flows including exit. The most complete return metric.",
             "Solve for r: NPV = Σ CFt/(1+r)^t = 0",
             "Target ≥ 15% for value-add. 10–15% = solid core deal."),
            ("Equity Multiple",
             "Total value returned divided by total invested. Simple but powerful.",
             "(Total Cash Invested + Total Profit) / Total Cash Invested",
             "Target ≥ 2.0x over 5 years. 1.5x = ok. Below 1.0x = lost money."),
            ("Exit Value (Resale)",
             "Projected sale price at end of hold period, based on exit cap rate applied to future NOI.",
             "Exit Year NOI / Exit Cap Rate",
             "Exit cap rate typically 0.25–0.5% higher than entry to be conservative."),
            ("Principal Paydown",
             "Equity built by tenants paying down your mortgage over the hold period.",
             "Sum of Principal portion of each payment over hold years",
             "Often underestimated — adds significantly to total return."),
            ("Total Profit",
             "Complete picture of all money made: operating cash flows + appreciation + debt paydown.",
             "Cumulative Cash Flow + (Exit Value − Purchase Price) + Principal Paydown",
             "—"),
        ],
        "🔄 Refinance & BRRRR": [
            ("Cash-Out Refinance",
             "Replacing existing mortgage with larger one to extract equity as tax-free cash.",
             "New Loan = Property Value × Refi LTV %   |   Cash-Out = New Loan − Old Loan",
             "Most lenders: 70–75% LTV on investment properties."),
            ("BRRRR Strategy",
             "Buy · Rehab · Rent · Refinance · Repeat. Force equity through renovation, refi to recycle capital.",
             "Cash Left In = All-In Cost − Refi Loan Amount",
             "Goal: recover 100% of capital. Cash Left In = $0 → infinite CoC return."),
            ("ARV — After Repair Value",
             "Estimated market value of property after all renovations are complete.",
             "Based on comparable sales (comps) in the area post-renovation",
             "Conservative underwriting: ARV = Purchase Price × 1.15–1.30"),
            ("Equity Created",
             "Value added through renovation above and beyond what you spent.",
             "ARV − All-In Cost (Purchase + Closing + Rehab)",
             "Positive = you created value. Negative = you overpaid or over-renovated."),
        ],
    }

    for category, terms in GLOSSARY.items():
        st.markdown(f"### {category}")
        for name, definition, formula, benchmark in terms:
            with st.expander(f"**{name}**"):
                col1, col2 = st.columns([1, 1])
                with col1:
                    st.markdown("**📌 Definition**")
                    st.markdown(definition)
                    if benchmark != "—":
                        st.markdown("**🎯 Benchmark**")
                        st.info(benchmark)
                with col2:
                    st.markdown("**🧮 Formula**")
                    st.code(formula, language="")
        st.divider()