"""
pull_salesforce_data.py

Real Salesforce Developer Org integration (not simulated CSVs) — pulls
donor and gift data via the Salesforce REST API using SOQL, the way this
role would actually extract from Advancement's CRM.

Requires a free Salesforce Developer Edition org (developer.salesforce.com)
and the `simple-salesforce` package: pip install simple-salesforce

Credentials are read from environment variables — never hardcode them.
See .env.example for the expected variables.

This script assumes standard Salesforce objects (Contact, Opportunity,
Campaign) plus one custom field (Fund__c) representing fund designation —
a common pattern for nonprofit/advancement Salesforce orgs (this mirrors
how NPSP / Evergreen-style advancement packages structure gift data).
"""

import os
import pandas as pd
from simple_salesforce import Salesforce

def get_connection() -> Salesforce:
    return Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
        domain=os.environ.get("SF_DOMAIN", "login"),  # 'test' for sandbox
    )


# ---------------------------------------------------------------------------
# SOQL EXTRACTS
# ---------------------------------------------------------------------------

CONTACTS_SOQL = """
    SELECT Id, Name, AccountId, Email, MailingState,
           npsp__First_Gift_Date__c
    FROM Contact
    WHERE npsp__First_Gift_Date__c != NULL
"""

OPPORTUNITIES_SOQL = """
    SELECT Id, ContactId, Amount, CloseDate, Type, StageName,
           Fund__c, CampaignId
    FROM Opportunity
    WHERE StageName = 'Closed Won'
    ORDER BY CloseDate DESC
"""

CAMPAIGNS_SOQL = """
    SELECT Id, Name, ExpectedRevenue, StartDate, EndDate
    FROM Campaign
"""


def extract_to_dataframe(sf: Salesforce, soql: str) -> pd.DataFrame:
    """Runs a SOQL query and pages through all results (query_all handles
    Salesforce's default 2,000-record page limit automatically)."""
    result = sf.query_all(soql)
    records = result["records"]
    for r in records:
        r.pop("attributes", None)  # drop Salesforce's metadata envelope
    return pd.DataFrame(records)


def run_extract(output_dir="../raw"):
    sf = get_connection()

    contacts = extract_to_dataframe(sf, CONTACTS_SOQL)
    opportunities = extract_to_dataframe(sf, OPPORTUNITIES_SOQL)
    campaigns = extract_to_dataframe(sf, CAMPAIGNS_SOQL)

    contacts.to_csv(f"{output_dir}/salesforce_contacts_live.csv", index=False)
    opportunities.to_csv(f"{output_dir}/salesforce_opportunities_live.csv", index=False)
    campaigns.to_csv(f"{output_dir}/salesforce_campaigns_live.csv", index=False)

    print(f"Pulled {len(contacts)} contacts, {len(opportunities)} opportunities, "
          f"{len(campaigns)} campaigns from Salesforce.")


if __name__ == "__main__":
    run_extract()
