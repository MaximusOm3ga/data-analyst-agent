from src.triage_agent.rag.in_memory import InMemoryVectorStore
from src.triage_agent.rag.ingest import ingest_documents


def test_ingest_and_retrieve():
    store = InMemoryVectorStore()
    docs = [
        {"id": "kb-1", "text": "How to reset your password. Follow these steps to reset your password.", "metadata": {"title": "Password reset"}},
        {"id": "kb-2", "text": "Troubleshooting VPN connectivity issues and steps to reconfigure the client.", "metadata": {"title": "VPN troubleshooting"}},
    ]
    ingest_documents(store, docs)

    # query similar to password reset
    results = store.retrieve("I forgot my password and need help")
    assert len(results) >= 1
    assert any("password" in r["text"].lower() or r["metadata"].get("title",""
               ).lower().find("password") >= 0 for r in results)

    # query VPN
    results2 = store.retrieve("Unable to connect to VPN from home")
    assert len(results2) >= 1
    assert any("vpn" in r["text"].lower() or r["metadata"].get("title",""
               ).lower().find("vpn") >= 0 for r in results2)
