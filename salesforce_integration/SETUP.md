# Salesforce Developer Org Setup

1. Sign up free at https://developer.salesforce.com/signup (no credit card, no time limit).
2. Install the free **Nonprofit Success Pack (NPSP)** from AppExchange — this
   gives you `npsp__First_Gift_Date__c` and proper gift/opportunity handling
   out of the box, matching how a real advancement org (like Evergreen,
   which is built on Salesforce) is structured.
3. Create one custom field: `Opportunity.Fund__c` (Text, 40 chars) — represents
   fund designation, since NPSP doesn't include this by default and every
   real advancement Salesforce org has some version of it.
4. Load sample data: Setup -> Data Import Wizard, or the Salesforce CLI
   (`sf data import tree`) using `raw/salesforce_contacts.csv` /
   `raw/salesforce_opportunities.csv` from this project as a source
   (you'll need to map columns to Contact/Opportunity fields).
5. Get your Security Token: Setup -> My Personal Information -> Reset
   Security Token (emailed to you).
6. `pip install simple-salesforce python-dotenv --break-system-packages`
7. Copy `.env.example` to `.env`, fill in credentials, run:
   `python3 pull_salesforce_data.py`

This is the one piece of the project that talks to a **real external API**
rather than synthetic CSVs — worth demoing live in an interview if asked
"have you actually used Salesforce," since it proves SOQL fluency and
API-based extraction, not just familiarity with the concept.
