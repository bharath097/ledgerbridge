"""
generate_paginated_statement.py

Simulates an SSRS-style "paginated report" -- a formally formatted,
print-exact financial statement, parameterized by fiscal month, as opposed
to an interactive dashboard. This is what SSRS/Power BI Report Builder
(both RDL-based) are for: official documents someone prints, signs, or
files -- not something you explore by clicking around.

Output: one PDF-ready HTML page per fiscal month, styled like a formal
accounting statement (fixed page size, header/footer, signature block).
"""

import json
import sys

with open("../output/dashboard_data.json") as f:
    DATA = json.load(f)


def build_statement(fiscal_year: int, fiscal_month: int) -> str:
    recon = DATA["page3_reconciliation"]["flagged"]
    month_names = ["", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun"]

    rows = [r for r in recon if r["fiscal_year"] == fiscal_year and r["fiscal_month"] == fiscal_month]
    all_by_fund = DATA["page3_reconciliation"]["by_fund_variance"]

    row_html = "".join(
        f"<tr><td>{r['fund']}</td><td class='num'>${r['gifts_recorded']:,.0f}</td>"
        f"<td class='num'>${r['gl_posted']:,.0f}</td><td class='num'>${r['variance']:,.0f}</td>"
        f"<td>{r['status']}</td></tr>"
        for r in rows
    ) or "<tr><td colspan='5' style='text-align:center;color:#777;'>No flagged variances this period.</td></tr>"

    return f"""
    <div class="statement-page">
      <div class="stmt-header">
        <div>
          <div class="stmt-org">UNIVERSITY FOUNDATION</div>
          <div class="stmt-title">Fund Reconciliation Statement</div>
        </div>
        <div class="stmt-meta">
          Period: {month_names[fiscal_month]} FY{fiscal_year}<br>
          Generated: {DATA['meta']['generated_at'][:10]}<br>
          Report ID: FRS-{fiscal_year}{fiscal_month:02d}
        </div>
      </div>
      <hr>
      <p class="stmt-note">This statement compares gift revenue recorded in the fundraising
      CRM against revenue posted to the General Ledger for the period above. Items flagged
      "Needs Review" exceed the standard timing-lag tolerance and require accounting follow-up.</p>

      <table class="stmt-table">
        <thead><tr><th>Fund</th><th>Gifts Recorded</th><th>GL Posted</th><th>Variance</th><th>Status</th></tr></thead>
        <tbody>{row_html}</tbody>
      </table>

      <div class="stmt-signoff">
        <div><span class="line"></span>Prepared by (Data Engineering)</div>
        <div><span class="line"></span>Reviewed by (Accounting)</div>
      </div>
      <div class="stmt-pagefoot">Page — University Foundation Fund Reconciliation Statement — Confidential</div>
    </div>
    """


def main():
    fys_months = sorted({(r["fiscal_year"], r["fiscal_month"]) for r in DATA["page3_reconciliation"]["flagged"]})
    if not fys_months:
        fys_months = [(DATA["meta"]["current_fy"], 1)]

    pages = "".join(build_statement(fy, fm) for fy, fm in fys_months)

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <title>Fund Reconciliation Statement</title>
    <style>
      @page {{ size: Letter; margin: 0.75in; }}
      body {{ font-family: Georgia, 'Times New Roman', serif; color: #1a1a1a; }}
      .statement-page {{ page-break-after: always; max-width: 7in; margin: 0 auto; padding-top: 20px; }}
      .stmt-header {{ display:flex; justify-content:space-between; align-items:flex-start; }}
      .stmt-org {{ font-size: 12px; letter-spacing:.08em; color:#555; }}
      .stmt-title {{ font-size: 22px; margin-top:2px; }}
      .stmt-meta {{ font-size: 11px; text-align:right; color:#444; line-height:1.5; }}
      hr {{ border:none; border-top:1px solid #333; margin: 14px 0 18px 0; }}
      .stmt-note {{ font-size: 12px; color:#333; margin-bottom:18px; }}
      table.stmt-table {{ width:100%; border-collapse:collapse; font-size:12px; }}
      .stmt-table th {{ text-align:left; border-bottom:1.5px solid #1a1a1a; padding:6px 8px; font-size:11px; }}
      .stmt-table td {{ padding:6px 8px; border-bottom:1px solid #ccc; }}
      td.num {{ text-align:right; font-variant-numeric: tabular-nums; }}
      .stmt-signoff {{ display:flex; gap:60px; margin-top:60px; font-size:11px; color:#333; }}
      .stmt-signoff .line {{ display:block; width:220px; border-bottom:1px solid #333; margin-bottom:6px; height:28px; }}
      .stmt-pagefoot {{ margin-top:40px; font-size:9px; color:#888; text-align:center; }}
    </style></head><body>{pages}</body></html>"""

    with open("paginated_reconciliation_statement.html", "w") as f:
        f.write(html)
    print(f"Generated {len(fys_months)} statement page(s) -> paginated_reconciliation_statement.html")
    print("(Open in a browser and Print -> Save as PDF for the final paginated-report artifact.)")


if __name__ == "__main__":
    main()
