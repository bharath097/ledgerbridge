-- ============================================================================
-- 01_schema_and_raw.sql
-- Creates the three-layer warehouse (raw / stg / mart) in Postgres.
-- raw = untouched source copies. stg = cleaned/typed. mart = star schema.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS mart;

-- ---------------------------------------------------------------------------
-- RAW LAYER: 1:1 copies of source exports, loaded via COPY / Python loader.
-- Every raw table gets a load timestamp for lineage/debugging.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raw.salesforce_contacts (
    donor_id        TEXT,
    donor_name      TEXT,
    donor_type      TEXT,
    email           TEXT,
    first_gift_date DATE,
    state           TEXT,
    _loaded_at      TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.salesforce_opportunities (
    gift_id      TEXT,
    donor_id     TEXT,
    fund_id      TEXT,
    campaign_id  TEXT,
    gift_date    DATE,
    gift_amount  NUMERIC,
    gift_type    TEXT,
    _loaded_at   TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.salesforce_pledges (
    pledge_id       TEXT,
    donor_id        TEXT,
    fund_id         TEXT,
    pledge_date     DATE,
    pledged_amount  NUMERIC,
    paid_amount     NUMERIC,
    status          TEXT,
    _loaded_at      TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.netsuite_gl_export (
    transaction_id   TEXT,
    line_no          INT,
    transaction_date DATE,
    account_number   TEXT,
    fund_id          TEXT,
    subsidiary_id    TEXT,
    debit_amount     NUMERIC,
    credit_amount    NUMERIC,
    memo             TEXT,
    source_gift_id   TEXT,
    _loaded_at       TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.netsuite_chart_of_accounts (
    account_number TEXT,
    account_name   TEXT,
    account_type   TEXT,
    _loaded_at     TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.netsuite_subsidiaries (
    subsidiary_id   TEXT,
    subsidiary_name TEXT,
    _loaded_at      TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.dim_fund (
    fund_id          TEXT,
    fund_name        TEXT,
    fund_type        TEXT,
    restriction_type TEXT,
    _loaded_at       TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.dim_campaign (
    campaign_id   TEXT,
    campaign_name TEXT,
    goal_amount   NUMERIC,
    start_date    DATE,
    end_date      DATE,
    _loaded_at    TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.donor_manual_adjustments (
    adjustment_id     TEXT,
    donor_name        TEXT,
    fund_id           TEXT,
    adjustment_amount NUMERIC,
    reason            TEXT,
    _loaded_at        TIMESTAMP DEFAULT now()
);

-- Load pattern (run from psql or a Python loader):
--   \copy raw.salesforce_contacts(donor_id,donor_name,donor_type,email,first_gift_date,state)
--     FROM 'raw/salesforce_contacts.csv' WITH (FORMAT csv, HEADER true);
--   (repeat per file)
