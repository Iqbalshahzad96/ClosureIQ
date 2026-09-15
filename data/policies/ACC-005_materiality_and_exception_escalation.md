# Materiality and Exception Escalation Framework

> **Notice**: Synthetic Demo Policy — For simulation and demonstration purposes only. This is not authoritative accounting advice or an internal policy of Enquest.

## Policy Metadata
- Policy ID: ACC-005
- Category: MATERIALITY
- Scope: Close Exceptions, Variances, and Governance Escalation

## Section 1: Severity Classification Matrix
1. Financial discrepancies detected by automated close engines are classified according to the following thresholds:
   - CRITICAL: Variance amount exceeding 100,000.00 KES, suspected fraud indicators, or unmapped ledger accounts.
   - HIGH: Variance amount between 25,000.01 KES and 100,000.00 KES, or unreconciled breaks older than 60 days.
   - MEDIUM: Variance amount between 5,000.01 KES and 25,000.00 KES, or recurring accrual variances.
   - LOW: Variance amount less than or equal to 5,000.00 KES with documented audit lineage.

## Section 2: Escalation SLAs and Reporting
1. CRITICAL exceptions must be acknowledged by the Senior Accounting Manager within 4 business hours.
2. HIGH exceptions require documented root-cause investigation within 24 business hours.
3. MEDIUM exceptions must be resolved prior to the close of business on the final day of the financial close window.
4. No close period may be locked while unaddressed CRITICAL or HIGH exceptions remain open.
