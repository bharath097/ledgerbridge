"""
test_data_quality.py

Unit tests for the pipeline's core integrity rules -- the JD explicitly
calls out "execute system tests" and "unit test new or modified
applications." These run against the generated raw CSVs and would run in
CI on every push (see .github/workflows/ci.yml).

Run with: pytest tests/ -v
"""

import pandas as pd
import pytest

RAW = "raw"


@pytest.fixture(scope="module")
def gifts():
    return pd.read_csv(f"{RAW}/salesforce_opportunities.csv")


@pytest.fixture(scope="module")
def funds():
    return pd.read_csv(f"{RAW}/dim_fund.csv")


@pytest.fixture(scope="module")
def gl():
    return pd.read_csv(f"{RAW}/netsuite_gl_export.csv")


@pytest.fixture(scope="module")
def pledges():
    return pd.read_csv(f"{RAW}/salesforce_pledges.csv")


def test_gift_amounts_are_positive(gifts):
    assert (gifts["gift_amount"] > 0).all(), "Found zero or negative gift amounts"


def test_gift_ids_are_unique(gifts):
    assert gifts["gift_id"].is_unique, "Duplicate gift_id values found"


def test_known_orphaned_funds_are_detected(gifts, funds):
    """This test intentionally asserts the KNOWN bug exists in the synthetic
    data (12 orphaned records), proving the detection logic works -- in a
    real pipeline this would instead assert the count is zero post-fix."""
    orphaned = gifts[~gifts["fund_id"].isin(funds["fund_id"])]
    assert len(orphaned) == 12, f"Expected 12 known orphaned records, found {len(orphaned)}"


def test_gl_transactions_balance_per_transaction(gl):
    """Every transaction_id's debits should equal its credits (double-entry
    integrity) -- except the intentionally injected rounding-error rows."""
    balance_check = gl.groupby("transaction_id").apply(
        lambda g: abs(g["debit_amount"].sum() - g["credit_amount"].sum())
    )
    unbalanced = balance_check[balance_check > 0.01]
    # We know ~20 rows were intentionally corrupted for the rounding-bug demo
    assert len(unbalanced) <= 20, f"Unexpected number of unbalanced GL transactions: {len(unbalanced)}"


def test_no_null_donor_ids(gifts):
    assert gifts["donor_id"].notna().all()


def test_pledge_overpayments_flagged_correctly(pledges):
    overpaid = pledges[pledges["paid_amount"] > pledges["pledged_amount"]]
    # Known intentional bug rate is ~1% of 800 pledges
    assert 0 < len(overpaid) < 20, "Overpayment count outside expected range for synthetic data"


def test_fund_dimension_has_no_duplicate_ids(funds):
    assert funds["fund_id"].is_unique


def test_gift_dates_within_expected_fiscal_range(gifts):
    gifts["gift_date"] = pd.to_datetime(gifts["gift_date"])
    assert gifts["gift_date"].min() >= pd.Timestamp("2023-07-01")
    assert gifts["gift_date"].max() <= pd.Timestamp("2026-06-30")
