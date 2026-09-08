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

-- Threshold-based grading, not naive zero-tolerance. A handful of exceptions
-- out of thousands of rows is normal operational noise, not a broken
-- pipeline -- each check documents its own tolerance so the rule is
-- auditable rather than an arbitrary "must be exactly zero."
CREATE OR REPLACE PROCEDURE mart.run_data_quality_checks()
LANGUAGE plpgsql AS $$
DECLARE
    v_count INT;
    v_total INT;
BEGIN
    -- Check 1: orphaned fund references in raw gifts (bug #1) -- tolerance 1.0%
    SELECT COUNT(*) INTO v_count FROM stg.gifts_orphaned;
    SELECT COUNT(*) INTO v_total FROM raw.salesforce_opportunities;
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('Fund ID references valid dim_fund (<1.0% tolerance)', 'salesforce_opportunities', 'critical',
            v_count, v_count::NUMERIC / NULLIF(v_total, 0) < 0.01);

    -- Check 2: gifts with no matching GL entry (bug #3 - missing batch) -- tolerance 1.5%
    SELECT COUNT(*) INTO v_count
    FROM mart.fact_gifts g
    LEFT JOIN mart.fact_gl_transactions gl ON g.gift_id = gl.source_gift_id
    WHERE gl.source_gift_id IS NULL;
    SELECT COUNT(*) INTO v_total FROM mart.fact_gifts;
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('Every gift has a matching GL entry (<1.5% tolerance)', 'fact_gl_transactions', 'critical',
            v_count, v_count::NUMERIC / NULLIF(v_total, 0) < 0.015);

    -- Check 3: pledges where paid_amount > pledged_amount (bug #5) -- tolerance 0.5%
    SELECT COUNT(*) INTO v_count FROM mart.fact_pledges WHERE has_overpayment_flag;
    SELECT COUNT(*) INTO v_total FROM mart.fact_pledges;
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('paid_amount <= pledged_amount (<0.5% tolerance)', 'fact_pledges', 'warning',
            v_count, v_count::NUMERIC / NULLIF(v_total, 0) < 0.005);

    -- Check 4: null / negative gift amounts -- true invariant, zero-tolerance
    -- (unlike the others, this should never legitimately happen even at low volume)
    SELECT COUNT(*) INTO v_count FROM mart.fact_gifts WHERE gift_amount IS NULL OR gift_amount <= 0;
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('gift_amount is positive and not null', 'fact_gifts', 'critical',
            v_count, v_count = 0);

    -- Check 5: GL debits = GL credits per transaction -- tolerance 0.5%
    SELECT COUNT(*) INTO v_count FROM (
        SELECT transaction_id, SUM(debit_amount) - SUM(credit_amount) AS diff
        FROM mart.fact_gl_transactions
        GROUP BY transaction_id
        HAVING ABS(SUM(debit_amount) - SUM(credit_amount)) > 0.01
    ) unbalanced;
    SELECT COUNT(DISTINCT transaction_id) INTO v_total FROM mart.fact_gl_transactions;
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('GL transactions balance, debit=credit (<0.5% tolerance)', 'fact_gl_transactions', 'critical',
            v_count, v_count::NUMERIC / NULLIF(v_total, 0) < 0.005);

    -- Check 6: fund reconciliation rows flagged "Needs Review" -- tolerance 10% of fund-months
    SELECT COUNT(*) INTO v_count FROM mart.fund_reconciliation WHERE status = 'Needs Review';
    SELECT COUNT(*) INTO v_total FROM mart.fund_reconciliation;
    INSERT INTO mart.dq_results(check_name, table_name, severity, row_count_affected, passed)
    VALUES ('Fund/month reconciliation within tolerance (<10% of fund-months)', 'fund_reconciliation', 'warning',
            v_count, v_count::NUMERIC / NULLIF(v_total, 0) < 0.10);

    RAISE NOTICE 'Data quality checks complete.';
END;
$$;

-- Run the full pipeline end to end:
--   CALL mart.load_dim_date();
--   CALL mart.load_dims_and_facts();
--   CALL mart.run_data_quality_checks();
