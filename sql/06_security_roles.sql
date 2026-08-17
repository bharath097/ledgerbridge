-- ============================================================================
-- 06_security_roles.sql
-- Basic role-based access design -- demonstrates the JD's "implement
-- Foundation data security policies" requirement. Two roles, least-privilege.
-- ============================================================================

-- Read-only role for analysts / Power BI service account -- can query the
-- mart (and dq results) but never touch raw or staging (which may contain
-- unmasked PII like email addresses before cleaning).
CREATE ROLE analyst_readonly;
GRANT USAGE ON SCHEMA mart TO analyst_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO analyst_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA mart GRANT SELECT ON TABLES TO analyst_readonly;

-- Engineer role -- full read/write on raw/stg/mart, can execute load
-- procedures, but not granted schema-drop / superuser rights
CREATE ROLE data_engineer;
GRANT USAGE ON SCHEMA raw, stg, mart TO data_engineer;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA raw, stg, mart TO data_engineer;
GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA mart TO data_engineer;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA mart TO data_engineer;

-- PII handling note: donor email addresses live only in raw/stg; the mart
-- layer intentionally excludes email from dim_donor exposed to Power BI,
-- so report viewers never see contact PII they don't need for reconciliation
-- or retention analysis. This is a deliberate governance choice, not an
-- oversight -- document it exactly like this in a real data dictionary.

-- Example: create named accounts and assign roles (adjust for real users)
-- CREATE USER pbi_service_account WITH PASSWORD '...';
-- GRANT analyst_readonly TO pbi_service_account;
-- CREATE USER jsmith WITH PASSWORD '...';
-- GRANT data_engineer TO jsmith;
