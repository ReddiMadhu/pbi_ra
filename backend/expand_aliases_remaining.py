#!/usr/bin/env python
"""Re-run alias expansion ONLY for KPIs that weren't expanded in the first run."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.core.llm import get_llm
from app.db.session import SessionLocal
from app.models.ontology import OntologyKPI
from app.services.ontology.embedding_service import compute_embedding, embedding_to_blob
from app.services.ontology.ontology_cache import invalidate_ontology_cache

PROMPT_TEMPLATE = """You are an insurance industry data analytics expert.

Given this canonical KPI from an insurance ontology bank:
  Name: "{name}"
  Definition: "{definition}"
  Sector: {sector}
  Subdomain: {subdomain}
  Current Aliases: {current_aliases}

Generate 10 additional common business-language names that a Tableau dashboard
analyst might use to refer to this exact same metric. Include:
- Informal shortened names (e.g., "Policy Count" -> "Total Policies")  
- Full descriptive names (e.g., "Policy Count" -> "Total Insurance Policies")
- Names with "Total", "Average", "Avg", "Number of", "#" prefixes
- Common abbreviations

RULES:
- Each alias must refer to the SAME metric, just named differently
- Do NOT include the original name or existing aliases
- Do NOT include dimensional breakdowns (no "by Region", "by Agent", etc.)
- Output ONLY a JSON array of strings, nothing else"""


def main():
    db = SessionLocal()
    llm = get_llm(temperature=0.3)

    try:
        # Only KPIs with <= 5 aliases (not yet expanded)
        kpis = db.query(OntologyKPI).filter(OntologyKPI.status == "active").all()
        unexpanded = []
        for kpi in kpis:
            aliases = json.loads(kpi.aliases) if kpi.aliases else []
            if len(aliases) <= 5:
                unexpanded.append(kpi)

        print(f"KPIs needing expansion: {len(unexpanded)} / {len(kpis)}")

        expanded_count = 0
        for i, kpi in enumerate(unexpanded, 1):
            current_aliases = json.loads(kpi.aliases) if kpi.aliases else []

            prompt = PROMPT_TEMPLATE.format(
                name=kpi.name,
                definition=kpi.definition or "",
                sector=kpi.sector or "insurance",
                subdomain=kpi.subdomain or "general",
                current_aliases=json.dumps(current_aliases),
            )

            try:
                result = llm.invoke(prompt)
                content = (result.content or "").strip()
                match = re.search(r"\[.*\]", content, re.DOTALL)
                if match:
                    new_aliases = json.loads(match.group())
                    if isinstance(new_aliases, list):
                        existing_lower = {a.lower() for a in current_aliases}
                        existing_lower.add(kpi.name.lower())
                        new_aliases = [a for a in new_aliases if isinstance(a, str) and a.strip() and a.lower() not in existing_lower]
                        
                        if new_aliases:
                            merged = current_aliases + new_aliases
                            kpi.aliases = json.dumps(merged)
                            alias_text = f"{kpi.name} {kpi.definition} {' '.join(merged)}"
                            kpi.embedding = embedding_to_blob(compute_embedding(alias_text))
                            expanded_count += 1
                            if i <= 10 or i % 50 == 0:
                                print(f"  [{i}/{len(unexpanded)}] {kpi.name}: +{len(new_aliases)} aliases")
            except Exception as e:
                print(f"  [{i}] ERROR {kpi.name}: {e}")

            if i % 20 == 0:
                db.commit()

        db.commit()
        try:
            invalidate_ontology_cache(db)
        except Exception:
            pass

        print(f"\nDONE: Expanded {expanded_count}/{len(unexpanded)} remaining KPIs")

    finally:
        db.close()

if __name__ == "__main__":
    main()
