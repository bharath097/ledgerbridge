# Data Dictionary — mart schema

## dim_donor
| Column | Type | Notes |
|---|---|---|
| donor_id | TEXT (PK) | Source: Salesforce Contact Id |
| donor_name | TEXT | Normalized (trimmed, title-cased) in staging; near-duplicates deduped by normalized-name match |
| donor_type | TEXT | Individual / Organization / Foundation-Trust |
| email | TEXT | **Present in raw/stg only** — deliberately excluded from mart per the access policy in `sql/06_security_roles.sql` |
| first_gift_date | DATE | Earliest gift on record |
| state | TEXT | Mailing state, 2-letter |

## dim_fund
| Column | Type | Notes |
|---|---|---|
| fund_id | TEXT (PK) | e.g. FND-001 |
| fund_name | TEXT | |
| fund_type | TEXT | Scholarship / Athletics / Endowment / Annual / Program / Capital |
| restriction_type | TEXT | Restricted / Unrestricted — drives which GL revenue account a gift posts to (4100 vs 4000) |

## dim_campaign
| Column | Type | Notes |
|---|---|---|
| campaign_id | TEXT (PK) | |
| campaign_name | TEXT | |
| goal_amount | NUMERIC | |
| start_date / end_date | DATE | |

## dim_account
| Column | Type | Notes |
|---|---|---|
| account_number | TEXT (PK) | Mirrors a NetSuite chart-of-accounts number |
| account_name | TEXT | |
| account_type | TEXT | Bank / Income / Expense |

## dim_date
| Column | Type | Notes |
|---|---|---|
| date_id | INT (PK) | YYYYMMDD surrogate |
| calendar_date | DATE | |
| fiscal_year | INT | **Foundation fiscal year = Jul 1–Jun 30**, not calendar year |
| fiscal_month | INT | 1 = July … 12 = June |

## fact_gifts
Grain: **one row per gift.**
| Column | Notes |
|---|---|
| gift_id (PK) | |
| donor_id, fund_id, campaign_id, date_id | FKs |
| gift_amount | |
| gift_type | Cash / Pledge Payment / Stock / Matching Gift |

## fact_pledges
Grain: **one row per pledge.**
| Column | Notes |
|---|---|
| pledge_id (PK) | |
| pledged_amount, paid_amount | `has_overpayment_flag` = TRUE when paid > pledged (data integrity violation, surfaced not silently corrected) |

## fact_gl_transactions
Grain: **one row per GL line** (every gift produces a balanced debit/credit pair — see `netsuite_gl_export.csv`).
| Column | Notes |
|---|---|
| transaction_id, line_no (composite PK) | |
| debit_amount, credit_amount | Exactly one is non-zero per row, by double-entry convention |
| source_gift_id | Links back to fact_gifts — the join key the reconciliation view depends on |

## mart.fund_reconciliation (view)
Grain: one row per fund × fiscal_year × fiscal_month.
Compares `SUM(fact_gifts.gift_amount)` to `SUM(fact_gl_transactions.credit_amount)` on Income accounts.
`status` = Reconciled (< $500 variance) / Timing Difference OK (< 8% of gifts_recorded) / Needs Review.

## mart.dq_results
Log table written by `mart.run_data_quality_checks()` on every pipeline run. One row per rule per run — see `sql/04_data_quality_checks.sql` for the six rules currently enforced.
