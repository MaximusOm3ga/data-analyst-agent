from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import ValidationError
from .schemas import AgentLoopResult, CommonTicket, KnowledgeBaseIngestRequest, KnowledgeBaseSearchResult
from .kb.service import ingest_kb_documents, search_kb, initialize_kb_store
from .orchestration.loop import run_ticket_loop
from .rag.store import get_store_name
from pathlib import Path

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
        import traceback, json
        tb = traceback.format_exc()
        # write traceback to a file for debugging
        with open("kb_upload_error.log", "a", encoding="utf-8") as fh:
            fh.write(tb + "\n")
        # return a concise error message but keep details in log
        raise HTTPException(status_code=500, detail="Internal server error while ingesting KB documents. See kb_upload_error.log for details.")


@app.post("/kb/upload-zip")
async def kb_upload_zip(file: UploadFile = File(...), default_category: str = "Other", default_owner: str = "IT"):
    """Accept a multipart .zip file, extract supported text files server-side and ingest into KB."""
    try:
        contents = await file.read()
        import io, zipfile
        allowed_suffixes = {".txt", ".md", ".rst", ".log", ".csv", ".json"}
        docs = []
        skipped = []
        with zipfile.ZipFile(io.BytesIO(contents), "r") as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            for member in members:
                inner_path = member.filename
                suffix = Path(inner_path).suffix.lower()
                if suffix not in allowed_suffixes:
                    skipped.append(inner_path)
                    continue
                try:
                    content_bytes = archive.read(member)
                    content = content_bytes.decode("utf-8", errors="ignore").strip()
                    if not content:
                        skipped.append(inner_path)
                        continue
                    doc_id = inner_path.replace("\\", "/").replace("/", "__")
                    docs.append({
                        "id": doc_id,
                        "title": Path(inner_path).stem or inner_path,
                        "content": content,
                        "source_url": f"zip://{inner_path}",
                        "category": default_category,
                        "metadata": {"owner": default_owner, "path_in_zip": inner_path},
                    })
                except Exception:
                    skipped.append(inner_path)
        if not docs:
            return {"ingested_chunks": 0, "documents": 0, "skipped_files": skipped}
        result = ingest_kb_documents(docs)
        result["skipped_files"] = skipped
        return result
    except Exception:
        import traceback
        tb = traceback.format_exc()
        with open("kb_upload_error.log", "a", encoding="utf-8") as fh:
            fh.write(tb + "\n")
        raise HTTPException(status_code=500, detail="Failed to process uploaded zip. See kb_upload_error.log for details.")


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
