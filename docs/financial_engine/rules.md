# Financial Engine Rules & Logic

## Workflows
1. **GL-to-Bank Reconciliation**:
   - Exact matching on Reference + Date + Amount (within configured tolerance e.g. $0.01).
   - Flagging unmatched bank transactions and unmatched ledger transactions.

2. **Accrual Validation**:
   - Compares period expense accruals against historical averages.
   - Detects missing recurring vendor accruals.

3. **Depreciation Validation**:
   - Straight-line formula verification: `(Cost - Salvage) / Useful_Life`.
   - Flags differences against posted depreciation ledger entries.
