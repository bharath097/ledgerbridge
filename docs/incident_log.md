# Incident Log

Write-ups of each data issue found during pipeline development, in the
format I'd actually use to document a real production incident: what
happened, how it was found, root cause, fix. (These issues were injected
deliberately in the synthetic data generator so the detection/reconciliation
logic has something real to catch — see `generate_synthetic_data.py` for
where each one is introduced.)

---

### INC-001 — Orphaned fund references in gift records
**Found by:** `stg.gifts_orphaned` view flagging 12 rows; also caught by
`test_known_orphaned_funds_are_detected` in CI.
**Symptom:** 12 gifts in the Salesforce extract reference `fund_id = FND-999`,
which does not exist in `dim_fund`.
**Root cause:** Simulates a fund being merged or retired in the CRM without
the historical gift records being re-pointed to the surviving fund — a
common real-world cleanup gap when Advancement consolidates funds.
**Fix applied:** Staging layer filters these out of `stg.gifts` rather than
silently dropping them from the pipeline entirely — they're captured in
`stg.gifts_orphaned` so accounting/Advancement can decide the correct
fund mapping, and the DQ check keeps the issue visible until resolved.

### INC-002 — Duplicate donor records from inconsistent name formatting
**Found by:** Manual QA of `dim_donor` row counts vs. expected unique donors.
**Symptom:** ~15 donors appeared twice under different `donor_id`s — same
person, but one record all-uppercase with extra whitespace.
**Root cause:** Manual data entry / import inconsistency, a very common
CRM data quality issue.
**Fix applied:** `stg.donors` normalizes name casing/whitespace and dedupes
on the normalized name, keeping the earliest donor_id. **Caveat noted for
the team:** normalized-name matching is a blunt instrument — it would
incorrectly merge two different people who share an identical name. A
production fix should use a proper donor-matching/survivorship rule
(e.g. matching on email + name, or a CRM-side merge) rather than this
staging-layer workaround.

### INC-003 — Missing GL batch for the week of 2025-03-10
**Found by:** `mart.dq_results` check "every gift has a matching GL entry" —
44 gifts with no corresponding `fact_gl_transactions` row.
**Symptom:** All gifts recorded that week are entirely absent from the GL
export.
**Root cause:** Simulates a failed nightly batch load from NetSuite (the
kind of silent pipeline failure the JD explicitly calls out troubleshooting
for).
**Fix applied:** In a real deployment, `orchestration/run_pipeline.py`'s
failure handling (non-zero exit code + log entry) would have caught this
at load time. Since it wasn't caught upstream here, the fix is at the
reconciliation layer: the fund/month rows show as 100% variance and are
flagged "Needs Review," which is exactly the signal that should trigger
a re-run of the missing batch.

### INC-004 — Rounding/currency mismatch on ~20 GL transactions
**Found by:** `test_gl_transactions_balance_per_transaction`; also
`mart.dq_results` "GL transactions balance (debit=credit)".
**Root cause:** Simulates a currency-precision issue introduced during
journal entry posting (e.g. a $0.01 rounding difference between the
sub-ledger and the GL).
**Fix applied:** Left visible rather than auto-corrected — a $0.01
difference is immaterial individually but should never be silently
"fixed" in accounting data; it needs an actual adjusting entry.

### INC-005 — Journal entries coded to the wrong fund
**Found by:** Fund reconciliation view — funds showing an unexplained
recorded-vs-posted variance that didn't match the missing-batch or
orphaned-fund issues above.
**Root cause:** Simulates a manual journal-entry coding error (a common
real error when a bookkeeper mistypes or misreads a fund segment code).
**Fix applied:** No pipeline-side fix is appropriate here — this is a
source-system data entry error, not a pipeline bug. The correct action is
for the reconciliation report to surface it (it does, in the "Needs Review"
rows) so accounting corrects the journal entry at the source.

### INC-006 — Pledge overpayments (paid_amount > pledged_amount)
**Found by:** `mart.dq_results` "paid_amount <= pledged_amount";
`test_pledge_overpayments_flagged_correctly`.
**Root cause:** Simulates a data entry error where a payment was applied
against the wrong pledge, or a pledge amount was corrected downward after
payments were already recorded.
**Fix applied:** Flagged via `has_overpayment_flag`, not corrected — this
is a business decision (write off the excess? reallocate it?) that belongs
to Advancement/accounting, not something a pipeline should decide silently.

---

**Pattern across all six:** the pipeline's job is to *surface* discrepancies
clearly and consistently, not to guess at silent fixes for financial data.
Every fix above either (a) is a legitimate staging-layer cleanup with a
documented caveat, or (b) is deliberately left visible for a human decision.
