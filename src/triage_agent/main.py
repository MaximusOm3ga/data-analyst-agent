from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from .schemas import CommonTicket, ClassificationOutput, KnowledgeBaseIngestRequest, KnowledgeBaseSearchResult
from .ingestion import web_form
from .classification import llm
from .enrichment import enricher
from .logging import shadow_log
from .kb.service import ingest_kb_documents, search_kb

app = FastAPI(title="IT Ticket Triage Agent - Prototype")

@app.post("/ingest/web_form", response_model=ClassificationOutput)
async def ingest_web_form(ticket: CommonTicket):
    try:
        # Enrichment (mocked)
        enrichment = enricher.enrich(ticket)

        # Classification (mocked LLM + RAG)
        classification = llm.classify(ticket, enrichment)

        # Shadow logging: write prediction but do not act
        shadow_log.log_prediction(ticket, enrichment, classification)

        return classification
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/kb/documents")
async def kb_documents(payload: KnowledgeBaseIngestRequest):
    try:
        result = ingest_kb_documents(payload.documents)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/kb/search", response_model=list[KnowledgeBaseSearchResult])
async def kb_search(query: str, limit: int = 5):
    try:
        return search_kb(query, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok", "kb_store": "ready"}
