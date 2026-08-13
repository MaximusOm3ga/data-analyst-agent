IT Ticket Triage Agent — Prototype (Python)

This scaffold implements a minimal FastAPI-based triage prototype in shadow mode.

Getting started:

1. Create a venv: python -m venv .venv
2. Activate it and install deps: pip install -r requirements.txt
3. Run: uvicorn src.triage_agent.main:app --reload --host 127.0.0.1 --port 8000

Endpoints:
- POST /ingest/web_form -> accepts the common schema and returns a structured classification (shadow-mode)
- GET /health -> basic health check

Notes:
- LLM, enrichment, and RAG are mocked. Replace triage_agent.classification.llm.classify and triage_agent.enrichment.enricher.enrich with real integrations for production.
