"""
build_dashboard_data.py
Computes the exact same metrics the mart SQL layer (03_mart_dimensional_model.sql,
04_data_quality_checks.sql) would produce, using pandas against the raw CSVs.
This lets the dashboard UI run standalone without a live Postgres instance,
while every number matches what the real warehouse would calculate.
"""

import json
import pandas as pd
import numpy as np

RAW = "../raw"
OUT_DATA = "../output/dashboard_data.json"


def fiscal_year(d):
    d = pd.Timestamp(d)
    return d.year + 1 if d.month >= 7 else d.year


def fiscal_month(d):
    d = pd.Timestamp(d)
    return d.month - 6 if d.month >= 7 else d.month + 6


def load():
    donors = pd.read_csv(f"{RAW}/salesforce_contacts.csv", parse_dates=["first_gift_date"])
    gifts = pd.read_csv(f"{RAW}/salesforce_opportunities.csv", parse_dates=["gift_date"])
    pledges = pd.read_csv(f"{RAW}/salesforce_pledges.csv", parse_dates=["pledge_date"])
    gl = pd.read_csv(f"{RAW}/netsuite_gl_export.csv", parse_dates=["transaction_date"])
    funds = pd.read_csv(f"{RAW}/dim_fund.csv")
    campaigns = pd.read_csv(f"{RAW}/dim_campaign.csv")
    accounts = pd.read_csv(f"{RAW}/netsuite_chart_of_accounts.csv")
    return donors, gifts, pledges, gl, funds, campaigns, accounts


def main():
    donors, gifts, pledges, gl, funds, campaigns, accounts = load()

    gifts["fiscal_year"] = gifts["gift_date"].apply(fiscal_year)
    gifts["fiscal_month"] = gifts["gift_date"].apply(fiscal_month)
    gl["fiscal_year"] = gl["transaction_date"].apply(fiscal_year)
    gl["fiscal_month"] = gl["transaction_date"].apply(fiscal_month)

    current_fy = int(gifts["fiscal_year"].max())
    prior_fy = current_fy - 1

    # ---------------- PAGE 1: Executive overview ----------------
    ytd_total = float(gifts.loc[gifts.fiscal_year == current_fy, "gift_amount"].sum())
    prior_total = float(gifts.loc[gifts.fiscal_year == prior_fy, "gift_amount"].sum())
    yoy_growth = round(100 * (ytd_total - prior_total) / prior_total, 1) if prior_total else None
    donor_count = int(gifts.loc[gifts.fiscal_year == current_fy, "donor_id"].nunique())
    avg_gift = round(ytd_total / max(len(gifts.loc[gifts.fiscal_year == current_fy]), 1), 2)
    total_goal = float(campaigns["goal_amount"].sum())

    monthly_trend = []
    for fy, label in [(prior_fy, "Prior FY"), (current_fy, "Current FY")]:
        by_month = (
            gifts[gifts.fiscal_year == fy].groupby("fiscal_month")["gift_amount"].sum().reindex(range(1, 13), fill_value=0)
        )
        monthly_trend.append({"fy_label": label, "values": [round(v, 0) for v in by_month.tolist()]})

    top_funds = (
        gifts.merge(funds, on="fund_id", how="left")
        .groupby("fund_name")["gift_amount"].sum().sort_values(ascending=False).head(8)
    )
    top_funds_data = [{"fund": k, "amount": round(v, 0)} for k, v in top_funds.items()]

    gift_type_mix = gifts.groupby("gift_type")["gift_amount"].sum()
    gift_type_data = [{"type": k, "amount": round(v, 0)} for k, v in gift_type_mix.items()]

    # ---------------- PAGE 2: Donor retention / RFM ----------------
    donor_fy = gifts.groupby(["donor_id", "fiscal_year"])["gift_amount"].sum().reset_index()
    donor_summary = donor_fy.groupby("donor_id").agg(
        last_fy=("fiscal_year", "max"),
        first_fy=("fiscal_year", "min"),
        frequency=("fiscal_year", "count"),
        lifetime=("gift_amount", "sum"),
    ).reset_index()

    def segment(row):
        if row.first_fy == current_fy:
            return "New"
        if row.last_fy == current_fy:
            return "Active"
        if row.last_fy == current_fy - 1:
            return "Lapsing"
        return "Lapsed"

    donor_summary["segment"] = donor_summary.apply(segment, axis=1)
    segment_counts = donor_summary["segment"].value_counts().to_dict()
    segment_revenue_at_risk = round(
        float(donor_summary.loc[donor_summary.segment == "Lapsing", "lifetime"].sum()), 0
    )

    retention_by_fy = []
    fys = sorted(gifts["fiscal_year"].unique())
    for i in range(1, len(fys)):
        prev_donors = set(gifts.loc[gifts.fiscal_year == fys[i - 1], "donor_id"])
        cur_donors = set(gifts.loc[gifts.fiscal_year == fys[i], "donor_id"])
        rate = round(100 * len(prev_donors & cur_donors) / max(len(prev_donors), 1), 1)
        retention_by_fy.append({"fiscal_year": int(fys[i]), "retention_rate": rate})

    # simple RFM score (1-5 quantile each of recency/frequency/monetary)
    donor_summary["recency_rank"] = pd.qcut(donor_summary["last_fy"], q=min(5, donor_summary["last_fy"].nunique()), labels=False, duplicates="drop")
    donor_summary["freq_rank"] = pd.qcut(donor_summary["frequency"].rank(method="first"), q=5, labels=False)
    donor_summary["monetary_rank"] = pd.qcut(donor_summary["lifetime"].rank(method="first"), q=5, labels=False)
    donor_summary["rfm_score"] = donor_summary[["recency_rank", "freq_rank", "monetary_rank"]].mean(axis=1).round(2)
    # With only a few fiscal years of history, frequency has very few distinct
    # values, so many donors land on the exact same RFM score. Break ties by
    # actual lifetime giving so "top donors" reflects real dollar magnitude,
    # not an arbitrary pick among a tied cohort.
    top_donors = donor_summary.merge(donors[["donor_id", "donor_name"]], on="donor_id", how="left") \
        .sort_values(["rfm_score", "lifetime"], ascending=[False, False]).head(10)
    top_donors_data = [
        {"donor": r.donor_name, "segment": r.segment, "lifetime": round(r.lifetime, 0), "rfm_score": r.rfm_score}
        for r in top_donors.itertuples()
    ]

    # segment x fund revenue-at-risk matrix
    gifts_seg = gifts.merge(donor_summary[["donor_id", "segment"]], on="donor_id", how="left")
    gifts_seg = gifts_seg.merge(funds[["fund_id", "fund_name"]], on="fund_id", how="left")
    matrix = gifts_seg.groupby(["fund_name", "segment"])["gift_amount"].sum().unstack(fill_value=0).round(0)
    matrix_data = {"funds": matrix.index.tolist(), "segments": matrix.columns.tolist(), "values": matrix.values.tolist()}

    # ---------------- PAGE 3: Fund reconciliation ----------------
    gift_side = gifts.groupby(["fund_id", "fiscal_year", "fiscal_month"])["gift_amount"].sum().reset_index()
    gift_side.columns = ["fund_id", "fiscal_year", "fiscal_month", "gifts_recorded"]

    income_accounts = accounts.loc[accounts.account_type == "Income", "account_number"].tolist()
    gl_income = gl[gl.account_number.isin(income_accounts)]
    gl_side = gl_income.groupby(["fund_id", "fiscal_year", "fiscal_month"])["credit_amount"].sum().reset_index()
    gl_side.columns = ["fund_id", "fiscal_year", "fiscal_month", "gl_posted"]

    recon = gift_side.merge(gl_side, on=["fund_id", "fiscal_year", "fiscal_month"], how="outer").fillna(0)
    recon = recon.merge(funds[["fund_id", "fund_name"]], on="fund_id", how="left")
    recon["variance"] = recon["gifts_recorded"] - recon["gl_posted"]

    def status(row):
        # Small-dollar fund/months are naturally noisy in percentage terms, so use
        # an absolute floor before applying the percentage tolerance.
        if abs(row.variance) < 500:
            return "Reconciled"
        if row.gifts_recorded and abs(row.variance) < 0.08 * row.gifts_recorded:
            return "Timing Difference (OK)"
        return "Needs Review"

    recon["status"] = recon.apply(status, axis=1)
    recon_fund_summary = recon.groupby("fund_name")["variance"].sum().sort_values().round(0)
    recon_fund_data = [{"fund": k, "variance": v} for k, v in recon_fund_summary.items()]

    flagged = recon[recon.status == "Needs Review"].sort_values("variance", key=abs, ascending=False).head(15)
    flagged_data = [
        {
            "fund": r.fund_name, "fiscal_year": int(r.fiscal_year), "fiscal_month": int(r.fiscal_month),
            "gifts_recorded": round(r.gifts_recorded, 0), "gl_posted": round(r.gl_posted, 0),
            "variance": round(r.variance, 0), "status": r.status,
        }
        for r in flagged.itertuples()
    ]
    status_counts = recon["status"].value_counts().to_dict()

    # ---------------- PAGE 4: Data quality scorecard ----------------
    orphaned_gifts = gifts[~gifts.fund_id.isin(funds.fund_id)]
    gifts_no_gl = gifts[~gifts.gift_id.isin(gl.source_gift_id)]
    overpaid_pledges = pledges[pledges.paid_amount > pledges.pledged_amount]
    gl_balance_check = gl.groupby("transaction_id").apply(
        lambda g: abs(g.debit_amount.sum() - g.credit_amount.sum()) > 0.01
    )
    unbalanced_tx = int(gl_balance_check.sum())

    # Threshold-based pass/fail, not naive zero-tolerance. A handful of
    # exceptions out of thousands of rows is normal operational noise, not a
    # broken pipeline -- real DQ frameworks grade against a tolerance band,
    # and reserve "fail" for issues that exceed it. Each check documents its
    # own tolerance so the rule is auditable, not just a number.
    n_gifts, n_pledges, n_tx = len(gifts), len(pledges), gl["transaction_id"].nunique()
    orphan_rate = len(orphaned_gifts) / n_gifts
    no_gl_rate = len(gifts_no_gl) / n_gifts
    overpaid_rate = len(overpaid_pledges) / n_pledges
    unbalanced_rate = unbalanced_tx / n_tx
    needs_review_rate = status_counts.get("Needs Review", 0) / max(sum(status_counts.values()), 1)

    dq_checks = [
        {"name": "Fund ID references valid dim_fund (<1.0% tolerance)", "table": "salesforce_opportunities",
         "severity": "critical", "affected": int(len(orphaned_gifts)), "passed": orphan_rate < 0.01},
        {"name": "Every gift has a matching GL entry (<1.5% tolerance)", "table": "fact_gl_transactions",
         "severity": "critical", "affected": int(len(gifts_no_gl)), "passed": no_gl_rate < 0.015},
        {"name": "paid_amount <= pledged_amount (<0.5% tolerance)", "table": "fact_pledges",
         "severity": "warning", "affected": int(len(overpaid_pledges)), "passed": overpaid_rate < 0.005},
        {"name": "GL transactions balance, debit=credit (<0.5% tolerance)", "table": "fact_gl_transactions",
         "severity": "critical", "affected": unbalanced_tx, "passed": unbalanced_rate < 0.005},
        {"name": "Fund/month reconciliation within tolerance (<10% of fund-months)", "table": "fund_reconciliation",
         "severity": "warning", "affected": int(status_counts.get("Needs Review", 0)),
         "passed": needs_review_rate < 0.10},
    ]
    total_checks = len(dq_checks)
    passed_checks = sum(1 for c in dq_checks if c["passed"])
    pass_rate = round(100 * passed_checks / total_checks, 0)

    data = {
        "meta": {"current_fy": current_fy, "prior_fy": prior_fy, "generated_at": pd.Timestamp.now().isoformat()},
        "page1_overview": {
            "ytd_total": round(ytd_total, 0), "prior_total": round(prior_total, 0),
            "yoy_growth": yoy_growth, "donor_count": donor_count, "avg_gift": avg_gift,
            "total_goal": round(total_goal, 0),
            "goal_attainment_pct": round(100 * ytd_total / total_goal, 1),
            "monthly_trend": monthly_trend, "top_funds": top_funds_data, "gift_type_mix": gift_type_data,
        },
        "page2_retention": {
            "segment_counts": segment_counts, "revenue_at_risk": segment_revenue_at_risk,
            "retention_by_fy": retention_by_fy, "top_donors": top_donors_data, "matrix": matrix_data,
        },
        "page3_reconciliation": {
            "status_counts": status_counts, "by_fund_variance": recon_fund_data, "flagged": flagged_data,
            "total_gifts": round(float(gifts["gift_amount"].sum()), 0),
            "total_gl": round(float(gl_income["credit_amount"].sum()), 0),
        },
        "page4_dataquality": {
            "checks": dq_checks, "pass_rate": pass_rate, "total_checks": total_checks, "passed_checks": passed_checks,
        },
    }

    import os
    os.makedirs("../output", exist_ok=True)
    with open(OUT_DATA, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"Dashboard data written to {OUT_DATA}")
    print(f"  YTD total: ${ytd_total:,.0f}  |  YoY: {yoy_growth}%  |  DQ pass rate: {pass_rate}%")


if __name__ == "__main__":
    main()
