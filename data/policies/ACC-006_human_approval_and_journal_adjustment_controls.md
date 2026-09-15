# Human Approval and Journal Adjustment Controls

> **Notice**: Synthetic Demo Policy — For simulation and demonstration purposes only. This is not authoritative accounting advice or an internal policy of Enquest.

## Policy Metadata
- Policy ID: ACC-006
- Category: APPROVAL_CONTROLS
- Scope: HITL Workflows, Manual Journal Entries, and Close Adjustments

## Section 1: Human-in-the-Loop (HITL) Authorization
1. All AI agent recommendations for adjusting journal entries require explicit human approval before posting to the general ledger.
2. System recommendations must provide complete audit lineage, including source transaction ID, exception reference, and cited accounting policy.
3. Approvers must verify the proposed account codes, debit/credit balance equality, and financial period alignment prior to confirming.

## Section 2: Segregation of Duties and Dual Authorization
1. Strict segregation of duties applies: the preparer of an adjusting entry cannot approve the same entry.
2. Adjustments exceeding 50,000.00 KES require dual authorization from both a Financial Controller and the Chief Financial Officer.
3. Every approval or rejection decision must be recorded in the immutable audit event log with reviewer username, timestamp, and review rationale.
