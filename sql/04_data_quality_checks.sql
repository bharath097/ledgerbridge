-- ============================================================================
-- 04_data_quality_checks.sql
-- Automated validation routines. Every check writes a row to mart.dq_results
-- so the Power BI Data Quality Scorecard page has something live to show.
-- ============================================================================

CREATE TABLE IF NOT EXISTS mart.dq_results (
    check_id     SERIAL PRIMARY KEY,
    run_at       TIMESTAMP DEFAULT now(),
    check_name   TEXT,
    table_name   TEXT,
    severity     TEXT,           -- 'critical' | 'warning'
    row_count_affected INT,
    passed       BOOLEAN
);

CREATE OR REPLACE PROCEDURE mart.run_data_quality_checks()
LANGUAGE plpgsql AS $$
DECLARE
    v_count INT;
BEGIN
    -- Check 1: orphaned fund references in raw gifts (bug #1)
    SELECT COUNT(*) INTO v_count FROM stg.gifts_orphaned;
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('fund_id references valid dim_fund', 'salesforce_opportunities', 'critical',
            v_count, v_count = 0);

    -- Check 2: gifts with no matching GL entry within 30 days (bug #3 - missing batch)
    SELECT COUNT(*) INTO v_count
    FROM mart.fact_gifts g
    LEFT JOIN mart.fact_gl_transactions gl ON g.gift_id = gl.source_gift_id
    WHERE gl.source_gift_id IS NULL;
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('every gift has a matching GL entry', 'fact_gl_transactions', 'critical',
            v_count, v_count = 0);

    -- Check 3: pledges where paid_amount > pledged_amount (bug #5)
    SELECT COUNT(*) INTO v_count FROM mart.fact_pledges WHERE has_overpayment_flag;
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('paid_amount <= pledged_amount', 'fact_pledges', 'warning',
            v_count, v_count = 0);

    -- Check 4: null / negative gift amounts
    SELECT COUNT(*) INTO v_count FROM mart.fact_gifts WHERE gift_amount IS NULL OR gift_amount <= 0;
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('gift_amount is positive and not null', 'fact_gifts', 'critical',
            v_count, v_count = 0);

    -- Check 5: GL debits = GL credits per transaction (basic double-entry integrity)
    SELECT COUNT(*) INTO v_count FROM (
        SELECT transaction_id, SUM(debit_amount) - SUM(credit_amount) AS diff
        FROM mart.fact_gl_transactions
        GROUP BY transaction_id
        HAVING ABS(SUM(debit_amount) - SUM(credit_amount)) > 0.01
    ) unbalanced;
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('GL transactions balance (debit=credit)', 'fact_gl_transactions', 'critical',
            v_count, v_count = 0);

    -- Check 6: fund reconciliation rows flagged "Needs Review"
    SELECT COUNT(*) INTO v_count FROM mart.fund_reconciliation WHERE status = 'Needs Review';
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('fund/month reconciliation within tolerance', 'fund_reconciliation', 'warning',
            v_count, v_count = 0);

    RAISE NOTICE 'Data quality checks complete.';
END;
$$;

-- Run the full pipeline end to end:
--   CALL mart.load_dim_date();
--   CALL mart.load_dims_and_facts();
--   CALL mart.run_data_quality_checks();
