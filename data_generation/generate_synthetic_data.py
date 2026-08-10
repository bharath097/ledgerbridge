"""
generate_synthetic_data.py
Generates realistic, Salesforce-style fundraising data and NetSuite-style
GL accounting data for a university foundation, with intentional data
quality issues baked in for the troubleshooting/reconciliation story.

Output: CSVs in ../raw/ mimicking real source-system exports.
"""

import random
import uuid
from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)

OUT = "../raw"

# ---------------------------------------------------------------------------
# FISCAL YEAR HELPERS  (Foundation fiscal year = Jul 1 - Jun 30, like UO)
# ---------------------------------------------------------------------------
FY_START = date(2023, 7, 1)
FY_END = date(2026, 6, 30)


def random_date(start=FY_START, end=FY_END):
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def fiscal_year(d):
    return d.year + 1 if d.month >= 7 else d.year


# ---------------------------------------------------------------------------
# DIMENSIONS
# ---------------------------------------------------------------------------

FUNDS = [
    ("FND-001", "General Scholarship Fund", "Scholarship", "Restricted"),
    ("FND-002", "Athletics Excellence Fund", "Athletics", "Restricted"),
    ("FND-003", "Presidential Endowment", "Endowment", "Restricted"),
    ("FND-004", "Annual Giving Fund", "Annual", "Unrestricted"),
    ("FND-005", "STEM Innovation Fund", "Program", "Restricted"),
    ("FND-006", "Library Modernization Fund", "Capital", "Restricted"),
    ("FND-007", "First-Gen Student Support", "Scholarship", "Restricted"),
    ("FND-008", "Faculty Research Grants", "Program", "Restricted"),
]

CAMPAIGNS = [
    ("CAM-001", "Give Big Day 2024", 250000, date(2024, 5, 1), date(2024, 5, 3)),
    ("CAM-002", "Homecoming Giving 2024", 150000, date(2024, 10, 1), date(2024, 10, 31)),
    ("CAM-003", "Year-End Appeal 2024", 500000, date(2024, 12, 1), date(2024, 12, 31)),
    ("CAM-004", "Give Big Day 2025", 300000, date(2025, 5, 1), date(2025, 5, 3)),
    ("CAM-005", "Year-End Appeal 2025", 550000, date(2025, 12, 1), date(2025, 12, 31)),
    ("CAM-006", "Scholarship Match Challenge", 200000, date(2025, 3, 1), date(2025, 4, 30)),
]

# NetSuite-style chart of accounts
ACCOUNTS = [
    ("1000", "Cash - Operating", "Bank"),
    ("1100", "Cash - Investment Pool", "Bank"),
    ("4000", "Contribution Revenue - Unrestricted", "Income"),
    ("4100", "Contribution Revenue - Restricted", "Income"),
    ("4200", "Pledge Revenue", "Income"),
    ("4300", "Investment Income", "Income"),
    ("5000", "Scholarship Disbursements", "Expense"),
    ("5100", "Grant Expense", "Expense"),
    ("5200", "Administrative Expense", "Expense"),
    ("5300", "Fundraising Expense", "Expense"),
]

SUBSIDIARIES = [
    ("SUB-01", "University Foundation - Main"),
    ("SUB-02", "University Foundation - Real Estate Holdings"),
]

DONOR_SEGMENT_WEIGHTS = {"Individual": 0.75, "Organization": 0.15, "Foundation/Trust": 0.10}


def gen_dims():
    dim_fund = pd.DataFrame(FUNDS, columns=["fund_id", "fund_name", "fund_type", "restriction_type"])
    dim_campaign = pd.DataFrame(
        CAMPAIGNS, columns=["campaign_id", "campaign_name", "goal_amount", "start_date", "end_date"]
    )
    dim_account = pd.DataFrame(ACCOUNTS, columns=["account_number", "account_name", "account_type"])
    dim_subsidiary = pd.DataFrame(SUBSIDIARIES, columns=["subsidiary_id", "subsidiary_name"])

    dim_fund.to_csv(f"{OUT}/dim_fund.csv", index=False)
    dim_campaign.to_csv(f"{OUT}/dim_campaign.csv", index=False)
    dim_account.to_csv(f"{OUT}/netsuite_chart_of_accounts.csv", index=False)
    dim_subsidiary.to_csv(f"{OUT}/netsuite_subsidiaries.csv", index=False)
    return dim_fund, dim_campaign, dim_account, dim_subsidiary


# ---------------------------------------------------------------------------
# SALESFORCE-STYLE: DONORS (Contacts) + GIFTS (Opportunities) + PLEDGES
# ---------------------------------------------------------------------------

def gen_donors(n=1200):
    rows = []
    for i in range(n):
        donor_type = np.random.choice(list(DONOR_SEGMENT_WEIGHTS), p=list(DONOR_SEGMENT_WEIGHTS.values()))
        name = fake.company() if donor_type != "Individual" else fake.name()

        # Intentional bug #2: inconsistent name casing/spacing for ~4% of donors
        # (simulates duplicate-looking CRM records from manual entry)
        if random.random() < 0.04:
            name = f"  {name.upper()}  "

        first_gift = random_date(FY_START, FY_END - timedelta(days=60))
        rows.append(
            {
                "donor_id": f"DNR-{i+1:05d}",
                "donor_name": name,
                "donor_type": donor_type,
                "email": fake.email(),
                "first_gift_date": first_gift,
                "state": fake.state_abbr(),
            }
        )
    df = pd.DataFrame(rows)

    # Intentional bug: inject ~15 near-duplicate donor rows (same person, new ID,
    # slightly different name formatting) - classic CRM data quality problem
    dupes = df.sample(15, random_state=1).copy()
    dupes["donor_id"] = [f"DNR-DUP{i:03d}" for i in range(len(dupes))]
    dupes["donor_name"] = dupes["donor_name"].apply(lambda n: n.strip().lower())
    df = pd.concat([df, dupes], ignore_index=True)

    df.to_csv(f"{OUT}/salesforce_contacts.csv", index=False)
    return df


def gen_gifts_and_pledges(dim_donor, dim_fund, dim_campaign, n_gifts=6000):
    gift_rows, pledge_rows = [], []
    gift_types = ["Cash", "Pledge Payment", "Stock", "Matching Gift"]
    gift_type_weights = [0.55, 0.25, 0.10, 0.10]

    donor_ids = dim_donor["donor_id"].tolist()
    fund_ids = dim_fund["fund_id"].tolist()
    campaign_ids = [None] * 3 + dim_campaign["campaign_id"].tolist()  # many gifts have no campaign

    for i in range(n_gifts):
        gdate = random_date()
        amount = round(float(np.random.lognormal(mean=5.2, sigma=1.1)), 2)
        amount = min(amount, 250000)  # cap outliers

        gift_rows.append(
            {
                "gift_id": f"GFT-{i+1:06d}",
                "donor_id": random.choice(donor_ids),
                "fund_id": random.choice(fund_ids),
                "campaign_id": random.choice(campaign_ids),
                "gift_date": gdate,
                "gift_amount": amount,
                "gift_type": np.random.choice(gift_types, p=gift_type_weights),
            }
        )

    gifts_df = pd.DataFrame(gift_rows)

    # Intentional bug #1: orphaned fund reference - a retired/merged fund id
    # that no longer exists in dim_fund
    orphan_idx = gifts_df.sample(12, random_state=2).index
    gifts_df.loc[orphan_idx, "fund_id"] = "FND-999"

    gifts_df.to_csv(f"{OUT}/salesforce_opportunities.csv", index=False)

    # Pledges: multi-installment commitments
    for i in range(800):
        pledged = round(float(np.random.lognormal(mean=6.5, sigma=1.0)), 2)
        pledged = min(pledged, 500000)
        paid = round(pledged * random.uniform(0.2, 1.0), 2)

        # Intentional bug #5: a few pledges where paid > pledged (data integrity violation)
        if random.random() < 0.01:
            paid = pledged * 1.15

        pledge_rows.append(
            {
                "pledge_id": f"PLG-{i+1:05d}",
                "donor_id": random.choice(donor_ids),
                "fund_id": random.choice(fund_ids),
                "pledge_date": random_date(),
                "pledged_amount": pledged,
                "paid_amount": round(paid, 2),
                "status": "Paid in Full" if paid >= pledged else "Active",
            }
        )
    pledges_df = pd.DataFrame(pledge_rows)
    pledges_df.to_csv(f"{OUT}/salesforce_pledges.csv", index=False)
    return gifts_df, pledges_df


# ---------------------------------------------------------------------------
# NETSUITE-STYLE: GL TRANSACTIONS (mirrors a typical saved-search export)
# ---------------------------------------------------------------------------

def gen_gl_transactions(gifts_df, dim_fund, dim_subsidiary):
    """
    For every gift, generate a matching pair of GL lines (debit Cash /
    credit Contribution Revenue), the way a real cash receipts batch would
    post in NetSuite. Then inject realistic posting problems.
    """
    rows = []
    tx_id = 1

    for _, g in gifts_df.iterrows():
        # Most gifts post within 0-5 days (normal timing lag) -- NOT an error
        post_delay = random.choices([0, 1, 2, 3, 5, 20], weights=[40, 25, 15, 10, 7, 3])[0]
        post_date = g["gift_date"] + timedelta(days=int(post_delay))

        fund_lookup = dim_fund.set_index("fund_id")
        restriction = fund_lookup["restriction_type"].get(g["fund_id"], "Restricted")  # orphaned funds default Restricted
        revenue_account = "4100" if restriction == "Restricted" else "4000"
        subsidiary = random.choices(["SUB-01", "SUB-02"], weights=[92, 8])[0]

        # Debit: Cash
        rows.append(
            {
                "transaction_id": f"JE-{tx_id:06d}",
                "line_no": 1,
                "transaction_date": post_date,
                "account_number": "1000",
                "fund_id": g["fund_id"],
                "subsidiary_id": subsidiary,
                "debit_amount": g["gift_amount"],
                "credit_amount": 0.0,
                "memo": f"Gift receipt {g['gift_id']}",
                "source_gift_id": g["gift_id"],
            }
        )
        # Credit: Revenue
        rows.append(
            {
                "transaction_id": f"JE-{tx_id:06d}",
                "line_no": 2,
                "transaction_date": post_date,
                "account_number": revenue_account,
                "fund_id": g["fund_id"],
                "subsidiary_id": subsidiary,
                "debit_amount": 0.0,
                "credit_amount": g["gift_amount"],
                "memo": f"Gift receipt {g['gift_id']}",
                "source_gift_id": g["gift_id"],
            }
        )
        tx_id += 1

    gl_df = pd.DataFrame(rows)

    # Intentional bug #3: simulate an entire batch (one week) that failed to load
    # -- pick a week and drop its GL rows, leaving gifts with NO matching GL entry
    missing_week_gifts = gifts_df[
        (gifts_df["gift_date"] >= date(2025, 3, 10)) & (gifts_df["gift_date"] <= date(2025, 3, 16))
    ]["gift_id"].tolist()
    gl_df = gl_df[~gl_df["source_gift_id"].isin(missing_week_gifts)]

    # Intentional bug #4: rounding/currency mismatch on ~20 transactions
    round_err_idx = gl_df.sample(20, random_state=3).index
    gl_df.loc[round_err_idx, "credit_amount"] = (gl_df.loc[round_err_idx, "credit_amount"] * 100).round() / 100 + 0.01

    # Intentional bug: a handful of GL entries tagged to the WRONG fund
    # (simulates a manual journal entry coding error)
    wrong_fund_idx = gl_df[gl_df["line_no"] == 2].sample(15, random_state=4).index
    all_funds = dim_fund["fund_id"].tolist()
    gl_df.loc[wrong_fund_idx, "fund_id"] = gl_df.loc[wrong_fund_idx, "fund_id"].apply(
        lambda f: random.choice([x for x in all_funds if x != f])
    )

    gl_df.to_csv(f"{OUT}/netsuite_gl_export.csv", index=False)
    return gl_df


# ---------------------------------------------------------------------------
# MANUAL "ALTERYX SOURCE" FILE - a messy spreadsheet accounting hand-maintains
# ---------------------------------------------------------------------------

def gen_manual_adjustments(dim_fund, n=60):
    rows = []
    fund_ids = dim_fund["fund_id"].tolist() + ["FND-OLD-12"]  # one bad legacy id
    for i in range(n):
        amt = round(random.uniform(-5000, 5000), 2)
        if random.random() < 0.08:
            amt = None  # missing amount -> invalid record for the workflow's filter step
        rows.append(
            {
                "adjustment_id": f"ADJ-{i+1:04d}",
                "donor_name": f"  {fake.name().upper()}  " if random.random() < 0.3 else fake.name(),
                "fund_id": random.choice(fund_ids),
                "adjustment_amount": amt,
                "reason": random.choice(["Pledge write-off", "Reclass", "Refund", "Correction"]),
            }
        )
    df = pd.DataFrame(rows)
    df.to_csv(f"{OUT}/donor_manual_adjustments.csv", index=False)
    return df


if __name__ == "__main__":
    import os

    os.makedirs(OUT, exist_ok=True)
    dim_fund, dim_campaign, dim_account, dim_subsidiary = gen_dims()
    dim_donor = gen_donors()
    gifts_df, pledges_df = gen_gifts_and_pledges(dim_donor, dim_fund, dim_campaign)
    gl_df = gen_gl_transactions(gifts_df, dim_fund, dim_subsidiary)
    gen_manual_adjustments(dim_fund)

    print("Synthetic data generated:")
    print(f"  Donors:            {len(dim_donor)}")
    print(f"  Gifts:             {len(gifts_df)}")
    print(f"  Pledges:           {len(pledges_df)}")
    print(f"  GL transactions:   {len(gl_df)}")
    print(f"  Funds/Campaigns:   {len(dim_fund)} / {len(dim_campaign)}")
