IT Ticket Triage Agent — Prototype (Python)

This scaffold implements a minimal FastAPI-based triage prototype in shadow mode.

Getting started:

1. Create a venv: python -m venv .venv
2. Activate it and install deps: pip install -r requirements.txt
3. Create a root `.env` file with your settings (see `.env.example`)
4. Run: uvicorn src.triage_agent.main:app --reload --host 127.0.0.1 --port 8000
5. (Optional admin UI) run: streamlit run ui/app.py
6. (Optional end-user portal) run: streamlit run ui/user_dashboard.py

Endpoints:
- POST /ingest/web_form -> runs the agent loop (enrich -> retrieve -> classify -> policy gate -> tool action -> audit log) and returns action + decision
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

Embeddings setup for real RAG retrieval (`.env`):
- `TRIAGE_EMBEDDINGS_MODE=auto|api|mock`
  - `auto`: use embeddings API when key is present, else fallback to mock embeddings
  - `api`: force real embeddings call
  - `mock`: deterministic mock embeddings (for local testing only)
- `TRIAGE_EMBEDDINGS_BASE_URL=https://api.groq.com/openai/v1`
- `TRIAGE_EMBEDDINGS_MODEL=text-embedding-3-small` (use an embedding-capable model)
- `TRIAGE_EMBEDDINGS_API_KEY=...` (falls back to `TRIAGE_LLM_API_KEY` if omitted)
- `TRIAGE_EMBEDDINGS_TIMEOUT_SECONDS=45`
- Optional: `KB_EMBEDDING_DIMENSION=1536` for pgvector schema consistency

Important reindex flow when switching from mock to real embeddings:
1. Set embeddings mode/model/key in `.env`.
2. Recreate or truncate your `rag_documents` table.
3. Call `POST /kb/init-store` to initialize schema with the correct vector dimension.
4. Re-upload all KB documents (`POST /kb/documents`), because old vectors are not compatible.

Streamlit UI (`ui/app.py`) features:
- KB store init + KB payload upload
- Zipped-folder KB upload (`.zip`) for text-like files (`.txt`, `.md`, `.rst`, `.log`, `.csv`, `.json`)
- Ticket submission and agent-loop result view
- KB semantic search
- Audit log viewer for `agent_loop_audit.log` and `shadow_predictions.log`

End-user Streamlit portal (`ui/user_dashboard.py`) features:
- Simple ticket submission form
- Resolution-focused output (summary, assigned team, priority, next steps)
- No raw JSON output

Tool-call execution mode (`.env`):
- `TRIAGE_TOOL_CALL_MODE=mock|http`
  - `mock`: local stub tools
  - `http`: calls external endpoints for real execution
- `TRIAGE_TOOL_HTTP_BASE_URL=http://host:port` (required in `http` mode)
- `TRIAGE_TOOL_HTTP_API_KEY=...` (optional bearer token)
- `TRIAGE_TOOL_HTTP_TIMEOUT_SECONDS=20`
- `TRIAGE_TOOL_HTTP_VERIFY_TLS=true|false`
- Endpoint overrides (optional):
  - `TRIAGE_TOOL_HTTP_ROUTE_PATH=/tools/route`
  - `TRIAGE_TOOL_HTTP_RESOLVE_PATH=/tools/resolve`
  - `TRIAGE_TOOL_HTTP_REVIEW_PATH=/tools/human-review`
  - `TRIAGE_TOOL_HTTP_PASSWORD_RESET_PATH=/tools/password-reset`
  - `TRIAGE_TOOL_HTTP_NETWORK_DIAGNOSTICS_PATH=/tools/network-diagnostics`
  - `TRIAGE_TOOL_HTTP_SOFTWARE_LICENSE_PATH=/tools/software-license`
  - `TRIAGE_TOOL_HTTP_SECURITY_CONTAIN_PATH=/tools/security-contain`

Action-to-tool routing in HTTP mode:
- `force_security_route`: runs `security-contain` first, then `route`
- `auto_route` / `auto_route_spotcheck`: calls `route`
- `auto_resolve`:
  - `Account/Password` or `Access Request` -> `password-reset`
  - `Network/VPN` -> `network-diagnostics`
  - `Software Install` -> `software-license`
  - fallback -> `resolve`
- `human_review` -> `human-review`

HTTP tool payload shape:
- `ticket`: normalized ticket fields
- `decision`: classifier decision fields
- `execution`: `{action, attempt, idempotency_key}`
