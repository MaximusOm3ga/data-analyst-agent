from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from .schemas import AgentLoopResult, CommonTicket, KnowledgeBaseIngestRequest, KnowledgeBaseSearchResult
from .kb.service import ingest_kb_documents, search_kb, initialize_kb_store
from .orchestration.loop import run_ticket_loop
from .rag.store import get_store_name

app = FastAPI(title="IT Ticket Triage Agent - Prototype")

@app.post("/ingest/web_form", response_model=AgentLoopResult)
async def ingest_web_form(ticket: CommonTicket):
    try:
        return run_ticket_loop(ticket)
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

@app.post("/kb/init-store")
async def kb_init_store():
    try:
        return initialize_kb_store()
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
    return {"status": "ok", "kb_store": get_store_name()}
