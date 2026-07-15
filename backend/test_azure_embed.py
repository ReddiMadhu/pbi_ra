import sys, os
sys.path.insert(0, os.getcwd())
os.environ["PYTHONIOENCODING"] = "utf-8"
from dotenv import load_dotenv
load_dotenv()

import app.services.ontology.embedding_service as emb_svc
emb_svc._embedding_network_failed = False
emb_svc._embedding_cache.clear()

from app.services.ontology.embedding_service import compute_embedding, cosine_similarity

print("Testing Azure OpenAI text-embedding-3-small...")
print("  AZURE_OPENAI_API_KEY set:", bool(os.getenv("AZURE_OPENAI_API_KEY")))
print("  AZURE_OPENAI_ENDPOINT:", os.getenv("AZURE_OPENAI_ENDPOINT"))
print("  Deployment:", os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"))

try:
    e1 = compute_embedding("Total Insurance Policies")
    print("\n[OK] Embedding returned! Dimension:", len(e1))
    
    if len(e1) == 128:
        print("[WARN] Got 128-dim vector = LOCAL HASH fallback, NOT Azure.")
    else:
        print("[OK] Got", len(e1), "-dim vector = REAL Azure embedding!")
    
    pairs = [
        ("Total Insurance Policies", "Policy Count"),
        ("Average Claim Amount", "Claims Severity"),
        ("Days to Settle Claim", "Average Claim Settlement Time"),
        ("Total Insurance Policies by Car Make", "Policy Count"),
        ("Avg Claim Cost", "Claims Severity"),
        ("Loss Ratio", "Loss Ratio"),
        ("Retention Rate", "Retention Rate"),
        ("Total Insurance Policies", "Average Claim Settlement Time"),
    ]
    
    print("\n--- Semantic Similarity Tests ---")
    for a, b in pairs:
        ea = compute_embedding(a)
        eb = compute_embedding(b)
        sim = cosine_similarity(ea, eb)
        label = "HIGH" if sim >= 0.50 else "LOW"
        print("  [%s] %.4f  '%s' vs '%s'" % (label, sim, a, b))

except Exception as e:
    print("\n[FAIL] Embedding call FAILED:", str(e))
    import traceback
    traceback.print_exc()
