IT Ticket Triage Agent — Prototype (Python)

This scaffold implements a minimal FastAPI-based triage prototype in shadow mode.

Getting started:

1. Create a venv: python -m venv .venv
2. Activate it and install deps: pip install -r requirements.txt
3. Create a root `.env` file with your settings (see `.env.example`)
4. Run: uvicorn src.triage_agent.main:app --reload --host 127.0.0.1 --port 8000
5. (Optional UI) run: streamlit run ui/app.py

Endpoints:
- POST /ingest/web_form -> runs the agent loop (enrich -> retrieve -> classify -> policy gate -> tool-action stub -> audit log) and returns action + decision
- POST /kb/init-store -> initializes KB store schema/resources (required for Postgres mode)
- POST /kb/documents -> ingests KB documents into vector store
- GET /kb/search -> searches KB chunks by semantic similarity
- GET /health -> basic health check

Notes:
- Enrichment is still mocked.
- Classifier supports a real OpenAI-compatible LLM call (including Groq) with heuristic fallback.

Vector store backends:
- Default: in-memory store (`KB_VECTOR_STORE=memory`)
- Postgres/pgvector: set in `.env`:
  - `KB_VECTOR_STORE=postgres`
  - `KB_POSTGRES_DSN=postgresql://USER:PASSWORD@HOST:5432/DBNAME`

For Postgres mode:
1. Ensure pgvector extension is available in your DB.
2. Put the values in a root-level `.env` file.
3. Call `POST /kb/init-store` once to create extension/table/index.
4. Ingest docs via `POST /kb/documents`.

LLM classifier setup (`.env`):
- `TRIAGE_CLASSIFIER_MODE=auto|llm|mock`
  - `auto`: use LLM if `TRIAGE_LLM_API_KEY` exists, else fallback to heuristic
  - `llm`: force real LLM call and fail if unavailable
  - `mock`: always use heuristic
- `TRIAGE_LLM_BASE_URL=https://api.groq.com/openai/v1`
- `TRIAGE_LLM_MODEL=openai/gpt-oss-120b` (change to the model you enabled)
- `TRIAGE_LLM_API_KEY=...`
- `TRIAGE_LLM_TIMEOUT_SECONDS=45`

Streamlit UI (`ui/app.py`) features:
- KB store init + KB payload upload
- Ticket submission and agent-loop result view
- KB semantic search
- Audit log viewer for `agent_loop_audit.log` and `shadow_predictions.log`
