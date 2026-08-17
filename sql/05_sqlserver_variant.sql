-- ============================================================================
-- 05_sqlserver_variant.sql
-- T-SQL equivalent of the fund reconciliation view and donor segmentation
-- logic from 03_mart_dimensional_model.sql (Postgres). Demonstrates the
-- multi-database fluency the JD calls out (Oracle / SQL Server / Postgres /
-- Microsoft Fabric) -- same business logic, different SQL dialect.
--
-- Key T-SQL vs Postgres differences applied here:
--   - IDENTITY instead of SERIAL
--   - TRY_CONVERT / FORMAT instead of TO_CHAR
--   - DATEFROMPARTS / EOMONTH instead of generate_series for date spines
--   - MERGE instead of INSERT ... ON CONFLICT
--   - Table-valued function instead of Postgres SETOF function
-- ============================================================================

CREATE SCHEMA mart_ss;  -- 'ss' = SQL Server variant, kept separate from mart.*
GO

CREATE TABLE mart_ss.dim_date (
    date_id      INT PRIMARY KEY,
    calendar_date DATE NOT NULL,
    fiscal_year  INT NOT NULL,
    fiscal_month INT NOT NULL,
    month_name   NVARCHAR(20),
    quarter      INT
);
GO

-- Populate a fiscal-year date spine (Jul-Jun) using a recursive CTE,
-- the standard T-SQL pattern in place of Postgres's generate_series()
;WITH date_spine AS (
    SELECT CAST('2023-07-01' AS DATE) AS d
    UNION ALL
    SELECT DATEADD(DAY, 1, d) FROM date_spine WHERE d < '2026-06-30'
)
INSERT INTO mart_ss.dim_date
SELECT
    CONVERT(INT, FORMAT(d, 'yyyyMMdd')),
    d,
    CASE WHEN MONTH(d) >= 7 THEN YEAR(d) + 1 ELSE YEAR(d) END,
    CASE WHEN MONTH(d) >= 7 THEN MONTH(d) - 6 ELSE MONTH(d) + 6 END,
    DATENAME(MONTH, d),
    DATEPART(QUARTER, d)
FROM date_spine
OPTION (MAXRECURSION 0);
GO

-- Table-valued function: donor segmentation (equivalent to Postgres's
-- mart.fn_donor_segment). T-SQL uses RETURNS TABLE + inline SELECT.
CREATE FUNCTION mart_ss.fn_donor_segment (@current_fy INT)
RETURNS TABLE
AS
RETURN (
    WITH donor_fy AS (
        SELECT f.donor_id, d.fiscal_year, SUM(f.gift_amount) AS fy_total
        FROM mart_ss.fact_gifts f
        JOIN mart_ss.dim_date d ON f.date_id = d.date_id
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
            WHEN first_gift_fy = @current_fy THEN 'New'
            WHEN last_gift_fy = @current_fy THEN 'Active'
            WHEN last_gift_fy = @current_fy - 1 THEN 'Lapsing'
            ELSE 'Lapsed'
        END AS segment,
        last_gift_fy,
        lifetime_giving
    FROM donor_summary
);
GO

-- Stored procedure equivalent of the MERGE-based upsert pattern
-- (Postgres used INSERT...ON CONFLICT; T-SQL idiom is MERGE)
CREATE PROCEDURE mart_ss.usp_load_dim_donor
AS
BEGIN
    SET NOCOUNT ON;
    MERGE mart_ss.dim_donor AS target
    USING stg_ss.donors AS source
    ON target.donor_id = source.donor_id
    WHEN MATCHED THEN
        UPDATE SET donor_name = source.donor_name
    WHEN NOT MATCHED THEN
        INSERT (donor_id, donor_name, donor_type, email, first_gift_date, state)
        VALUES (source.donor_id, source.donor_name, source.donor_type,
                source.email, source.first_gift_date, source.state);
END;
GO

-- Fund reconciliation view -- identical business logic to the Postgres
-- version, written in T-SQL syntax
CREATE VIEW mart_ss.fund_reconciliation AS
WITH gift_side AS (
    SELECT f.fund_id, d.fiscal_year, d.fiscal_month, SUM(f.gift_amount) AS gifts_recorded
    FROM mart_ss.fact_gifts f
    JOIN mart_ss.dim_date d ON f.date_id = d.date_id
    GROUP BY f.fund_id, d.fiscal_year, d.fiscal_month
),
gl_side AS (
    SELECT g.fund_id, d.fiscal_year, d.fiscal_month, SUM(g.credit_amount) AS gl_posted
    FROM mart_ss.fact_gl_transactions g
    JOIN mart_ss.dim_date d ON g.date_id = d.date_id
    JOIN mart_ss.dim_account a ON g.account_number = a.account_number
    WHERE a.account_type = 'Income'
    GROUP BY g.fund_id, d.fiscal_year, d.fiscal_month
)
SELECT
    COALESCE(gs.fund_id, gl.fund_id)           AS fund_id,
    COALESCE(gs.fiscal_year, gl.fiscal_year)   AS fiscal_year,
    COALESCE(gs.fiscal_month, gl.fiscal_month) AS fiscal_month,
    ISNULL(gs.gifts_recorded, 0)               AS gifts_recorded,
    ISNULL(gl.gl_posted, 0)                    AS gl_posted,
    ISNULL(gs.gifts_recorded, 0) - ISNULL(gl.gl_posted, 0) AS variance_amount,
    CASE
        WHEN ABS(ISNULL(gs.gifts_recorded, 0) - ISNULL(gl.gl_posted, 0)) < 500 THEN 'Reconciled'
        WHEN gs.gifts_recorded IS NOT NULL
             AND ABS(ISNULL(gs.gifts_recorded, 0) - ISNULL(gl.gl_posted, 0)) < 0.08 * gs.gifts_recorded
             THEN 'Timing Difference (OK)'
        ELSE 'Needs Review'
    END AS status
FROM gift_side gs
FULL OUTER JOIN gl_side gl
    ON gs.fund_id = gl.fund_id AND gs.fiscal_year = gl.fiscal_year AND gs.fiscal_month = gl.fiscal_month;
GO
