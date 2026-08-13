-- ============================================================================
-- 03_mart_dimensional_model.sql
-- Star schema: fact_gifts, fact_pledges, fact_gl_transactions
-- dim_donor, dim_fund, dim_campaign, dim_account, dim_subsidiary, dim_date
-- Plus stored procedures for donor segmentation and fund reconciliation.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- DIMENSIONS
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mart.dim_date (
    date_id      INT PRIMARY KEY,          -- YYYYMMDD
    calendar_date DATE NOT NULL,
    fiscal_year  INT NOT NULL,             -- FY2024 = Jul 2023 - Jun 2024
    fiscal_month INT NOT NULL,             -- 1 = July
    month_name   TEXT,
    quarter      INT
);

CREATE TABLE IF NOT EXISTS mart.dim_donor (
    donor_id        TEXT PRIMARY KEY,
    donor_name      TEXT,
    donor_type      TEXT,
    email           TEXT,
    first_gift_date DATE,
    state           TEXT
);

CREATE TABLE IF NOT EXISTS mart.dim_fund (
    fund_id          TEXT PRIMARY KEY,
    fund_name        TEXT,
    fund_type        TEXT,
    restriction_type TEXT
);

CREATE TABLE IF NOT EXISTS mart.dim_campaign (
    campaign_id   TEXT PRIMARY KEY,
    campaign_name TEXT,
    goal_amount   NUMERIC,
    start_date    DATE,
    end_date      DATE
);

CREATE TABLE IF NOT EXISTS mart.dim_account (
    account_number TEXT PRIMARY KEY,
    account_name   TEXT,
    account_type   TEXT
);

CREATE TABLE IF NOT EXISTS mart.dim_subsidiary (
    subsidiary_id   TEXT PRIMARY KEY,
    subsidiary_name TEXT
);

-- ---------------------------------------------------------------------------
-- FACTS
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mart.fact_gifts (
    gift_id     TEXT PRIMARY KEY,
    donor_id    TEXT REFERENCES mart.dim_donor(donor_id),
    fund_id     TEXT REFERENCES mart.dim_fund(fund_id),
    campaign_id TEXT REFERENCES mart.dim_campaign(campaign_id),
    date_id     INT REFERENCES mart.dim_date(date_id),
    gift_amount NUMERIC,
    gift_type   TEXT
);

CREATE TABLE IF NOT EXISTS mart.fact_pledges (
    pledge_id       TEXT PRIMARY KEY,
    donor_id        TEXT REFERENCES mart.dim_donor(donor_id),
    fund_id         TEXT REFERENCES mart.dim_fund(fund_id),
    date_id         INT REFERENCES mart.dim_date(date_id),
    pledged_amount  NUMERIC,
    paid_amount     NUMERIC,
    status          TEXT,
    has_overpayment_flag BOOLEAN
);

CREATE TABLE IF NOT EXISTS mart.fact_gl_transactions (
    transaction_id TEXT,
    line_no        INT,
    date_id        INT REFERENCES mart.dim_date(date_id),
    account_number TEXT REFERENCES mart.dim_account(account_number),
    fund_id        TEXT,
    subsidiary_id  TEXT REFERENCES mart.dim_subsidiary(subsidiary_id),
    debit_amount   NUMERIC,
    credit_amount  NUMERIC,
    source_gift_id TEXT,
    PRIMARY KEY (transaction_id, line_no)
);

-- ---------------------------------------------------------------------------
-- LOAD PROCEDURES (populate dims/facts from staging)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE PROCEDURE mart.load_dim_date()
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO mart.dim_date
    SELECT
        TO_CHAR(calendar_date, 'YYYYMMDD')::INT,
        calendar_date,
        CASE WHEN EXTRACT(MONTH FROM calendar_date) >= 7
             THEN EXTRACT(YEAR FROM calendar_date)::INT + 1
             ELSE EXTRACT(YEAR FROM calendar_date)::INT END,
        CASE WHEN EXTRACT(MONTH FROM calendar_date) >= 7
             THEN EXTRACT(MONTH FROM calendar_date)::INT - 6
             ELSE EXTRACT(MONTH FROM calendar_date)::INT + 6 END,
        TO_CHAR(calendar_date, 'Month'),
        EXTRACT(QUARTER FROM calendar_date)::INT
    FROM stg.date_spine
    ON CONFLICT (date_id) DO NOTHING;
END;
$$;

CREATE OR REPLACE PROCEDURE mart.load_dims_and_facts()
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO mart.dim_donor SELECT * FROM stg.donors
        ON CONFLICT (donor_id) DO UPDATE SET donor_name = EXCLUDED.donor_name;

    INSERT INTO mart.dim_fund SELECT * FROM raw.dim_fund
        ON CONFLICT (fund_id) DO NOTHING;

    INSERT INTO mart.dim_campaign SELECT * FROM raw.dim_campaign
        ON CONFLICT (campaign_id) DO NOTHING;

    INSERT INTO mart.dim_account SELECT * FROM raw.netsuite_chart_of_accounts
        ON CONFLICT (account_number) DO NOTHING;

    INSERT INTO mart.dim_subsidiary SELECT * FROM raw.netsuite_subsidiaries
        ON CONFLICT (subsidiary_id) DO NOTHING;

    INSERT INTO mart.fact_gifts
    SELECT gift_id, donor_id, fund_id, campaign_id,
           TO_CHAR(gift_date, 'YYYYMMDD')::INT, gift_amount, gift_type
    FROM stg.gifts
    ON CONFLICT (gift_id) DO NOTHING;

    INSERT INTO mart.fact_pledges
    SELECT pledge_id, donor_id, fund_id,
           TO_CHAR(pledge_date, 'YYYYMMDD')::INT,
           pledged_amount, paid_amount, status, has_overpayment_flag
    FROM stg.pledges
    ON CONFLICT (pledge_id) DO NOTHING;

    INSERT INTO mart.fact_gl_transactions
    SELECT transaction_id, line_no,
           TO_CHAR(transaction_date, 'YYYYMMDD')::INT,
           account_number, fund_id, subsidiary_id,
           debit_amount, credit_amount, source_gift_id
    FROM stg.gl_transactions
    ON CONFLICT (transaction_id, line_no) DO NOTHING;
END;
$$;

-- ---------------------------------------------------------------------------
-- FUNCTION: donor segmentation (New / Active / Lapsing / Lapsed)
-- Business rule: Active = gave in current FY, Lapsing = gave last FY but
-- not this FY, Lapsed = last gift 2+ FYs ago, New = first gift this FY.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION mart.fn_donor_segment(current_fy INT)
RETURNS TABLE(donor_id TEXT, segment TEXT, last_gift_fy INT, lifetime_giving NUMERIC)
LANGUAGE sql AS $$
    WITH donor_fy AS (
        SELECT f.donor_id,
               d.fiscal_year,
               SUM(f.gift_amount) AS fy_total
        FROM mart.fact_gifts f
        JOIN mart.dim_date d ON f.date_id = d.date_id
        GROUP BY f.donor_id, d.fiscal_year
    ),
    donor_summary AS (
        SELECT donor_id,
               MAX(fiscal_year) AS last_gift_fy,
               MIN(fiscal_year) AS first_gift_fy,
               SUM(fy_total) AS lifetime_giving
        FROM donor_fy
        GROUP BY donor_id
    )
    SELECT
        donor_id,
        CASE
            WHEN first_gift_fy = current_fy THEN 'New'
            WHEN last_gift_fy = current_fy THEN 'Active'
            WHEN last_gift_fy = current_fy - 1 THEN 'Lapsing'
            ELSE 'Lapsed'
        END AS segment,
        last_gift_fy,
        lifetime_giving
    FROM donor_summary;
$$;

-- ---------------------------------------------------------------------------
-- VIEW: fund reconciliation (Salesforce gift revenue vs NetSuite GL revenue)
-- This is the centerpiece deliverable -- distinguishes real variances from
-- normal posting-timing lag (gifts near month-end that post next month).
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW mart.fund_reconciliation AS
WITH gift_side AS (
    SELECT f.fund_id, d.fiscal_year, d.fiscal_month,
           SUM(f.gift_amount) AS gifts_recorded
    FROM mart.fact_gifts f
    JOIN mart.dim_date d ON f.date_id = d.date_id
    GROUP BY f.fund_id, d.fiscal_year, d.fiscal_month
),
gl_side AS (
    SELECT g.fund_id, d.fiscal_year, d.fiscal_month,
           SUM(g.credit_amount) AS gl_posted
    FROM mart.fact_gl_transactions g
    JOIN mart.dim_date d ON g.date_id = d.date_id
    JOIN mart.dim_account a ON g.account_number = a.account_number
    WHERE a.account_type = 'Income'
    GROUP BY g.fund_id, d.fiscal_year, d.fiscal_month
)
SELECT
    COALESCE(gs.fund_id, gl.fund_id)         AS fund_id,
    COALESCE(gs.fiscal_year, gl.fiscal_year) AS fiscal_year,
    COALESCE(gs.fiscal_month, gl.fiscal_month) AS fiscal_month,
    COALESCE(gs.gifts_recorded, 0)           AS gifts_recorded,
    COALESCE(gl.gl_posted, 0)                AS gl_posted,
    COALESCE(gs.gifts_recorded, 0) - COALESCE(gl.gl_posted, 0) AS variance_amount,
    CASE
        WHEN COALESCE(gs.gifts_recorded, 0) = 0 THEN NULL
        ELSE ROUND(100.0 * (COALESCE(gs.gifts_recorded,0) - COALESCE(gl.gl_posted,0))
             / NULLIF(gs.gifts_recorded, 0), 2)
    END AS variance_pct,
    CASE
        WHEN ABS(COALESCE(gs.gifts_recorded, 0) - COALESCE(gl.gl_posted, 0)) < 500 THEN 'Reconciled'
        WHEN ABS(COALESCE(gs.gifts_recorded, 0) - COALESCE(gl.gl_posted, 0))
             < 0.08 * NULLIF(gs.gifts_recorded, 1) THEN 'Timing Difference (OK)'
        ELSE 'Needs Review'
    END AS status
FROM gift_side gs
FULL OUTER JOIN gl_side gl
    ON gs.fund_id = gl.fund_id AND gs.fiscal_year = gl.fiscal_year AND gs.fiscal_month = gl.fiscal_month;
