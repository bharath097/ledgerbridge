"""
alteryx_style_workflow.py

Mirrors an Alteryx-style visual ETL workflow using discrete, named steps
(Input -> Clean -> Join -> Filter -> Output), including an error-routing
branch, the way Alteryx separates a "valid" and "invalid" output anchor.

Workflow diagram (also in docs/data_flow_diagram.png):

  [Input: Manual Adjustments CSV]        [Input: Fund Dimension CSV]
                |                                    |
                v                                    |
      [Clean: normalize donor names]                 |
                |                                    |
                +---------------> [Join: attach fund info] <------------+
                                          |
                                          v
                              [Filter: valid vs invalid]
                                    /            \\
                                   v              v
                    [Output: clean CSV]   [Output: error log CSV]

Real-world use case simulated: Foundation accounting staff maintain a manual
"pledge adjustment / write-off" spreadsheet by hand. This workflow cleans it,
joins in fund metadata, and separates valid records from ones needing
human follow-up -- exactly the kind of task Alteryx is used for by
non-engineering analysts.
"""

import pandas as pd

RAW_DIR = "raw"
OUT_DIR = "output"


# --- INPUT TOOLS -----------------------------------------------------------

def load_donor_adjustments() -> pd.DataFrame:
    return pd.read_csv(f"{RAW_DIR}/donor_manual_adjustments.csv")


def load_fund_dimension() -> pd.DataFrame:
    return pd.read_csv(f"{RAW_DIR}/dim_fund.csv")


# --- DATA CLEANSING TOOL -----------------------------------------------------

def clean_donor_names(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["donor_name"] = (
        df["donor_name"].astype(str).str.strip().str.replace(r"\s+", " ", regex=True).str.title()
    )
    return df


# --- JOIN TOOL ---------------------------------------------------------------

def join_fund_info(adjustments_df: pd.DataFrame, fund_df: pd.DataFrame) -> pd.DataFrame:
    joined = adjustments_df.merge(fund_df, on="fund_id", how="left", indicator=True)
    return joined


# --- FILTER TOOL (this is Alteryx's classic "True/False" output anchors) ----

def filter_valid_records(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    is_valid = (
        df["adjustment_amount"].notna()
        & (df["_merge"] == "both")  # fund_id actually matched dim_fund
    )
    valid = df[is_valid].drop(columns=["_merge"])
    invalid = df[~is_valid].copy()

    invalid["error_reason"] = invalid.apply(
        lambda r: "Missing adjustment_amount" if pd.isna(r["adjustment_amount"])
        else "fund_id not found in dim_fund" if r["_merge"] != "both"
        else "Unknown",
        axis=1,
    )
    invalid = invalid.drop(columns=["_merge"])
    return valid, invalid


# --- OUTPUT TOOLS -------------------------------------------------------------

def output_results(valid: pd.DataFrame, invalid: pd.DataFrame) -> None:
    import os
    os.makedirs(OUT_DIR, exist_ok=True)
    valid.to_csv(f"{OUT_DIR}/clean_donor_adjustments.csv", index=False)
    invalid.to_csv(f"{OUT_DIR}/errors_log.csv", index=False)


# --- RUN THE "WORKFLOW" -------------------------------------------------------

def run():
    adjustments = load_donor_adjustments()
    funds = load_fund_dimension()

    adjustments = clean_donor_names(adjustments)
    joined = join_fund_info(adjustments, funds)
    valid, invalid = filter_valid_records(joined)
    output_results(valid, invalid)

    print("Alteryx-style workflow complete.")
    print(f"  Valid records:   {len(valid)}  -> output/clean_donor_adjustments.csv")
    print(f"  Invalid records: {len(invalid)} -> output/errors_log.csv")
    if len(invalid):
        print("  Error breakdown:")
        print(invalid["error_reason"].value_counts().to_string())


if __name__ == "__main__":
    run()
