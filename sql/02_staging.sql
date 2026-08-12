-- ============================================================================
-- 02_staging.sql
-- Staging layer: clean, dedupe, standardize. This is where "clean,
-- replicable code" lives before anything hits the dimensional model.
-- ============================================================================

-- Donors: trim/normalize names, dedupe on a normalized-name match
-- (this is the fix for the injected CRM duplicate-donor bug)
CREATE OR REPLACE VIEW stg.donors AS
WITH normalized AS (
    SELECT
        donor_id,
        INITCAP(TRIM(donor_name))              AS donor_name,
        LOWER(TRIM(REGEXP_REPLACE(donor_name, '\s+', ' ', 'g'))) AS donor_name_key,
        donor_type,
        LOWER(TRIM(email))                     AS email,
        first_gift_date,
        state
    FROM raw.salesforce_contacts
),
ranked AS (
    -- Keep the earliest donor_id per normalized name -- treats near-duplicate
    -- CRM records (different casing/spacing) as the same donor
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY donor_name_key ORDER BY donor_id) AS rn
    FROM normalized
)
SELECT donor_id, donor_name, donor_type, email, first_gift_date, state
FROM ranked
WHERE rn = 1;

-- Gifts: filter out rows referencing a fund that doesn't exist (orphaned FK bug)
-- but LOG them rather than silently dropping -- see dq checks (04)
CREATE OR REPLACE VIEW stg.gifts AS
SELECT g.gift_id, g.donor_id, g.fund_id, g.campaign_id, g.gift_date,
       g.gift_amount, g.gift_type
FROM raw.salesforce_opportunities g
WHERE g.fund_id IN (SELECT fund_id FROM raw.dim_fund);

CREATE OR REPLACE VIEW stg.gifts_orphaned AS
SELECT g.* FROM raw.salesforce_opportunities g
WHERE g.fund_id NOT IN (SELECT fund_id FROM raw.dim_fund);

-- Pledges: flag the data integrity violation (paid > pledged) rather than
-- silently correcting it -- accounting needs to see and resolve these
CREATE OR REPLACE VIEW stg.pledges AS
SELECT *,
       (paid_amount > pledged_amount) AS has_overpayment_flag
FROM raw.salesforce_pledges;

-- GL transactions: standardize types, keep as-is otherwise (this is
-- financial data -- staging should not silently "fix" amounts)
CREATE OR REPLACE VIEW stg.gl_transactions AS
SELECT transaction_id, line_no, transaction_date, account_number,
       fund_id, subsidiary_id,
       COALESCE(debit_amount, 0)  AS debit_amount,
       COALESCE(credit_amount, 0) AS credit_amount,
       memo, source_gift_id
FROM raw.netsuite_gl_export;

-- Date dimension driver, built directly in staging (fiscal year = Jul-Jun)
CREATE OR REPLACE VIEW stg.date_spine AS
SELECT d::date AS calendar_date
FROM generate_series('2023-07-01'::date, '2026-06-30'::date, '1 day') d;
