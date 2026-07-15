"""Refine and correct aliases, lineage, aggregation type, and dimensions of ontology KPIs using the LLM."""

import os
import sys
import json
import time
import argparse

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.llm import get_llm
from app.db.session import SessionLocal
from app.services.ontology.embedding_service import embed_ontology_kpis
from app.models.ontology import OntologyKPI

SEED_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app/db/seeds/ontology_kpis.json")


def refine_kpi_batch(llm, batch: list[dict]) -> list[dict]:
    """Send a batch of KPIs to the LLM to correct/refine their columns."""
    input_data = []
    for k in batch:
        input_data.append({
            "kpi_id": k["kpi_id"],
            "name": k["name"],
            "definition": k["definition"],
            "sector": k.get("sector"),
            "subdomain": k.get("subdomain"),
            "current_aliases": k.get("aliases"),
            "current_lineage": k.get("representative_lineage"),
        })

    prompt = f"""You are an expert BI data architect and insurance domain expert.
I have a list of insurance KPIs with their names, definitions, and sectors.
Your task is to refine and fill the following fields for each KPI, utilizing standard insurance terminology (e.g. claims, actuarial, underwriting, policy, agent, premium, risk, etc.):
1. aliases: Provide a list of true business aliases, abbreviations, acronyms, or common rephrasings (e.g., ["Loss Ratio", "LR"] for "Loss Ratio", or ["Declined Calls %", "Agent Decline Rate"] for "% Calls Agent Declined").
   - CRITICAL: DO NOT include domain names, sector names, or long descriptions. They must be actual alternative names of the KPI.
2. aggregation_type: Determine the correct default aggregation type from: SUM, AVG, COUNT, COUNTD, MIN, MAX, PCT, or NONE.
   - For ratios/percentages, use PCT or AVG.
   - For raw counts, use SUM or COUNT.
3. valid_dimensions: A list of standard, meaningful business dimensions that this KPI could reasonably be sliced or broken down by (e.g., ["State", "Agent", "Date", "Month", "Year", "Policy Type", "Campaign", "Channel"] for a marketing call metric).
4. representative_lineage: Standardize the list of physical database/visual lineage columns that would be required to compute this metric (e.g., ["Declined Calls Count", "Total Calls Count"] for declining rate).

Input KPIs:
{json.dumps(input_data, indent=2)}

Return a JSON array containing objects with:
- kpi_id (string, MUST match input)
- aliases (list of strings)
- aggregation_type (string)
- valid_dimensions (list of strings)
- representative_lineage (list of strings)

Format your response as a valid JSON array block only. Do not add any markdown explanation or extra text.
"""
    try:
        res = llm.invoke(prompt)
        content = res.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        
        parsed = json.loads(content.strip())
        return parsed
    except Exception as e:
        print(f"Error refining batch: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Refine ontology KPIs using LLM")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of KPIs to refine (for testing)")
    parser.add_argument("--batch-size", type=int, default=30, help="Batch size for LLM processing")
    args = parser.parse_args()

    llm = get_llm()
    if not llm:
        print("Error: LLM client is not configured. Set OPENAI_API_KEY or AZURE_OPENAI_API_KEY in .env.")
        sys.exit(1)

    if not os.path.exists(SEED_FILE):
        print(f"Error: Seed file not found at {SEED_FILE}")
        sys.exit(1)

    print(f"Reading KPIs from {SEED_FILE}...")
    with open(SEED_FILE, "r", encoding="utf-8") as f:
        kpis = json.load(f)

    total_kpis = len(kpis)
    print(f"Loaded {total_kpis} KPIs.")

    target_kpis = kpis
    if args.limit:
        target_kpis = kpis[:args.limit]
        print(f"Limiting refinement to first {args.limit} KPIs for testing.")

    refined_count = 0
    start_time = time.time()
    
    # Process in batches
    for i in range(0, len(target_kpis), args.batch_size):
        batch = target_kpis[i:i+args.batch_size]
        print(f"Processing batch {i//args.batch_size + 1} ({len(batch)} KPIs)...")
        
        # Try up to 3 times for robust error handling
        results = []
        for attempt in range(3):
            results = refine_kpi_batch(llm, batch)
            if results:
                break
            print(f"Attempt {attempt+1} failed. Retrying...")
            time.sleep(2)
            
        if not results:
            print("Failed to get results for batch. Skipping batch.")
            continue
            
        # Map results back to target KPIs
        results_by_id = {r["kpi_id"]: r for r in results if "kpi_id" in r}
        
        for kpi in batch:
            res_kpi = results_by_id.get(kpi["kpi_id"])
            if res_kpi:
                kpi["aliases"] = res_kpi.get("aliases", [])
                kpi["aggregation_type"] = res_kpi.get("aggregation_type", "UNKNOWN").upper()
                kpi["valid_dimensions"] = res_kpi.get("valid_dimensions", [])
                kpi["representative_lineage"] = res_kpi.get("representative_lineage", [])
                kpi["embedding"] = None  # Force re-embed since fields changed
                refined_count += 1
                
        print(f"Refined {refined_count} KPIs so far.")
        time.sleep(1) # Rate limit cushion

    # Save changes back to JSON seed file
    print(f"Saving changes back to {SEED_FILE}...")
    with open(SEED_FILE, "w", encoding="utf-8") as f:
        json.dump(kpis, f, indent=2, ensure_ascii=False)

    print("Importing refined KPIs to SQLite database...")
    # Trigger database reload by clearing tables and auto-seeding
    from app.db.seeds.seeder import seed_ontology_kpis
    db = SessionLocal()
    try:
        # Wipe only the ontology_kpis table to reload
        db.query(OntologyKPI).delete()
        db.commit()
        
        # Re-seed from the updated json
        seed_ontology_kpis(db)
        
        # Re-embed the KPIs using LLM embedding since aliases changed!
        print("Re-computing embeddings for updated KPIs...")
        embed_ontology_kpis(db)
        
        # Dump the KPIs again to save the new embeddings to JSON!
        print("Saving new embeddings back to JSON seed file...")
        cursor = db.connection().connection.cursor()
        cursor.execute("SELECT kpi_id, embedding FROM ontology_kpis")
        emb_map = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Encode embeddings as base64 in the JSON
        import base64
        for k in kpis:
            kpi_id = k["kpi_id"]
            if kpi_id in emb_map and emb_map[kpi_id] is not None:
                k.update({"embedding": base64.b64encode(emb_map[kpi_id]).decode("utf-8")})
                
        with open(SEED_FILE, "w", encoding="utf-8") as f:
            json.dump(kpis, f, indent=2, ensure_ascii=False)
            
        print("Database sync and JSON embedding backup complete.")
        
    except Exception as db_err:
        print(f"DB Update Error: {db_err}")
    finally:
        db.close()

    print(f"Ontology refinement complete! Refined {refined_count} KPIs in {time.time() - start_time:.1f} seconds.")


if __name__ == "__main__":
    main()
