from src.triage_agent.rag.embeddings import embed_text
try:
    v = embed_text('test embedding')
    print('len', len(v))
except Exception as e:
    import traceback
    traceback.print_exc()
