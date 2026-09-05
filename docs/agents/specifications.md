# AI Agents Specification

## Agent 1: Financial Review Agent
- **Purpose**: High-level anomaly detection, financial summary review, trend evaluation across GL accounts.
- **Inputs**: Reconciliation summary, policy summaries, account balances.
- **Outputs**: Review assessment, flagged high-level areas.
- **Constraints**: No raw mathematical calculations.

## Agent 2: Exception Analysis Agent
- **Purpose**: Root-cause analysis of specific discrepancies and exceptions.
- **Inputs**: Exception record, relevant GL transactions (via MCP), SOP policies (via RAG).
- **Outputs**: Root cause hypothesis, suggested adjustment entry, policy citations.
- **Constraints**: Recommendations must be submitted for Human-in-the-Loop review.
