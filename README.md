# ClosureIQ

## Project overview

ClosureIQ is a financial close assistant built as an academic capstone. It combines deterministic accounting checks, two AI agents, policy retrieval and human review to help accountants investigate month-end exceptions.

## Core features

- Financial-file ingestion: Enquest ledger/trial balance and generic bank, AP invoice and asset adapters, with validation, quarantine and source lineage.
- Bank reconciliation, accrual review and straight-line depreciation validation.
- Two agents for financial review and policy-grounded exception analysis.
- Backend human approval/rejection of workflow results.

The backend implements these capabilities with integration limits: React workflow screens are mostly placeholders, accrual/depreciation runs still use supplied inputs, and approvals are held in memory. See the detailed guides for current scope.

## Architecture

React calls FastAPI. The ingestion service maps source files into canonical SQLite tables. WorkflowService uses LangGraph to coordinate MCP data queries, deterministic engines, two agents, ChromaDB policy retrieval and human review. Observability currently includes console logs and in-memory node traces.

## Tech stack

React 18 / Vite, FastAPI / SQLAlchemy / SQLite, MCP, LangGraph, Google Gemini (`google-genai`), ChromaDB, openpyxl / xlrd, and pytest.

## Setup and run

Use Python 3.11+ and Node.js 20. PowerShell, from the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = 'sqlite:///../closureiq.db'
$env:CHROMA_PERSIST_DIRECTORY = './chroma_data'
# Set GEMINI_API_KEY in this shell for live agent calls.

# Create missing tables; this does not migrate existing schemas.
python -c "from app.database.database import Base, engine; import app.database.models; Base.metadata.create_all(bind=engine)"
python ../scripts/ingest_policies.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Environment variables must be set explicitly; the backend does not automatically load `.env`. Policy ingestion may download an embedding model. Keep one worker because workflow checkpoints are in memory.

**Do not use `scripts/seed_database.py` for routine initialization:** it drops/recreates tables and can erase imported data.

In a second shell, from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173. API schemas: http://localhost:8000/docs. Detailed configuration, database guidance, Docker and test commands are in the [developer guide](docs/architecture/overview.md#setup-database-initialization-and-running).

## Documentation

- [Architecture, schema, setup, tests and project status](docs/architecture/overview.md)
- [Financial ingestion, Enquest provenance and synthetic examples](docs/ingestion/pipeline.md)
- [Agents, LangGraph branches and human review](docs/agents/specifications.md)
- [API endpoints and examples](docs/api/endpoints.md)
- [Financial engine rules](docs/financial_engine/rules.md)
- [MCP tools](docs/mcp/tools.md)
- [Policy ingestion and RAG](docs/rag/pipeline.md)
- [Observability and audit](docs/observability/telemetry.md)
