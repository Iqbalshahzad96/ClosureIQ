# Bank Reconciliation Standard Operating Procedure

> **Notice**: Synthetic Demo Policy — For simulation and demonstration purposes only. This is not authoritative accounting advice or an internal policy of Enquest.

## Policy Metadata
- Policy ID: ACC-001
- Category: BANK_RECONCILIATION
- Scope: Cash and Bank General Ledger Accounts

## Section 1: Reconciliation Frequency and Execution
1. All general ledger cash accounts must be reconciled against official bank statements on a monthly basis following period close.
2. The reconciliation engine performs primary deterministic matching on normalized bank reference and exact transaction amount within a 0.01 currency tolerance.
3. Secondary matching applies a 3-day transaction date window for items with matching amounts and compatible description identifiers.

## Section 2: Exception Handling and Thresholds
1. Unmatched GL or bank transactions exceeding 50.00 KES must be flagged as exceptions for investigation.
2. Timing differences exceeding 30 calendar days must be evaluated for stale outstanding checks or unrecorded deposits.
3. Bank service charges, monthly account fees, and interest income identified on bank statements must be recorded via adjusting journal entries in the matching period.
