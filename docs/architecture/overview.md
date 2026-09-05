# ClosureIQ System Architecture

## Architecture Overview

```mermaid
flowchart TD
    UI[React.js Frontend] -->|REST / JSON| API[FastAPI Backend]
    API --> ORCH[LangGraph AI Orchestrator]
    
    subgraph AI Layer
        ORCH --> AG1[Financial Review Agent 1]
        ORCH --> AG2[Exception Analysis Agent 2]
    end
    
    subgraph Grounding & Data
        AG2 --> RAG[RAG Layer: LangChain + ChromaDB]
        AG1 --> MCP[MCP Data Access Layer]
        AG2 --> MCP
        MCP --> DB[(SQLite Database)]
    end
    
    subgraph Observability
        API -.-> OBS[Observability Layer\nLogs / Metrics / Traces / HITL]
        ORCH -.-> OBS
    end
```

## Key Architectural Principles
1. **Deterministic Financial Truth**: Financial math is done in the Python financial engine, not LLMs.
2. **Exactly Two AI Agents**: Financial Review Agent and Exception Analysis Agent.
3. **Human-in-the-Loop (HITL)**: Recommendations require human sign-off.
4. **MCP Controlled Access**: Database is accessed via secure tool interfaces.
5. **RAG Policy Grounding**: Recommendations cite accounting SOPs.
6. **Observability**: Complete audit trail of run IDs, tokens, latencies, and decisions.
