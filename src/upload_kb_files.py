from pathlib import Path
import requests

API = "http://127.0.0.1:8000"
KB_DIR = Path("kb_files")

docs = []
for p in KB_DIR.rglob("*"):
    if p.suffix.lower() in {".txt", ".md"} and p.is_file():
        docs.append({
            "id": p.stem,
            "title": p.stem.replace("_", " ").title(),
            "content": p.read_text(encoding="utf-8", errors="ignore"),
            "source_url": str(p),
            "category": "Other",
            "metadata": {"filename": p.name, "path": str(p)},
        })

requests.post(f"{API}/kb/init-store", timeout=30)

resp = requests.post(f"{API}/kb/documents", json={"documents": docs}, timeout=120)
print(resp.status_code, resp.text)