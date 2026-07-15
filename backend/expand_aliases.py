#!/usr/bin/env python
"""One-time LLM-powered alias expansion for ontology KPIs.

Iterates over all active ontology KPIs and uses the LLM to generate
comprehensive business-language aliases, then stores them back in the DB.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

load_dotenv()

from app.core.llm import get_llm
from app.db.session import SessionLocal
from app.models.ontology import OntologyKPI
from app.services.ontology.embedding_service import (
    clear_embedding_cache,
    compute_embedding,
    embedding_to_blob,
)
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
- Names that include the word "insurance" or domain context

RULES:
- Each alias must refer to the SAME metric, just named differently
- Do NOT include the original name or existing aliases
- Do NOT include dimensional breakdowns (no "by Region", "by Agent", etc.)
- Output ONLY a JSON array of strings, nothing else

Example output:
["Total Insurance Policies", "# of Policies", "Active Policy Count", "Policies Total", "Insurance Policy Volume", "Policy Book Size", "Total Active Policies", "Insured Policy Count", "Number of Active Policies", "Policy Tally"]"""


def expand_aliases_for_kpi(llm, kpi: OntologyKPI) -> list[str]:
    """Use the LLM to generate expanded aliases for a single KPI."""
    current_aliases = []
    try:
        current_aliases = json.loads(kpi.aliases) if kpi.aliases else []
    except Exception:
        pass

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

        # Extract JSON array from response
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            new_aliases = json.loads(match.group())
            if isinstance(new_aliases, list):
                # Filter out any that are already present
                existing_lower = {a.lower() for a in current_aliases}
                existing_lower.add(kpi.name.lower())
                new_aliases = [
                    a for a in new_aliases
                    if isinstance(a, str) and a.strip() and a.lower() not in existing_lower
                ]
                return new_aliases
    except Exception as e:
        print(f"  [ERROR] LLM failed for '{kpi.name}': {e}")
    return []


def main():
    print("=" * 60)
    print("LLM-Powered Alias Expansion for Ontology KPIs")
    print("=" * 60)

    db = SessionLocal()
    llm = get_llm(temperature=0.3)

    try:
        kpis = db.query(OntologyKPI).filter(OntologyKPI.status == "active").all()
        print(f"\nTotal active ontology KPIs: {len(kpis)}")

        expanded_count = 0
        total_new_aliases = 0

        for i, kpi in enumerate(kpis, 1):
            current_aliases = []
            try:
                current_aliases = json.loads(kpi.aliases) if kpi.aliases else []
            except Exception:
                pass

            print(f"\n[{i}/{len(kpis)}] {kpi.name} ({kpi.sector}/{kpi.subdomain})")
            print(f"  Current aliases ({len(current_aliases)}): {current_aliases}")

            new_aliases = expand_aliases_for_kpi(llm, kpi)

            if new_aliases:
                # Merge: keep existing + add new
                merged = current_aliases + new_aliases
                kpi.aliases = json.dumps(merged)

                # Recompute embedding with expanded alias text
                alias_text = f"{kpi.name} {kpi.definition} {' '.join(merged)}"
                new_emb = compute_embedding(alias_text)
                kpi.embedding = embedding_to_blob(new_emb)

                expanded_count += 1
                total_new_aliases += len(new_aliases)
                print(f"  + Added {len(new_aliases)} new aliases: {new_aliases[:3]}...")
            else:
                print(f"  - No new aliases generated")

            # Commit every 20 KPIs to avoid losing progress
            if i % 20 == 0:
                db.commit()
                print(f"\n  [CHECKPOINT] Committed {i} KPIs to database")

        # Final commit
        db.commit()

        # Invalidate ontology cache so new aliases take effect
        try:
            invalidate_ontology_cache(db)
        except Exception:
            pass

        print("\n" + "=" * 60)
        print(f"DONE: Expanded aliases for {expanded_count}/{len(kpis)} KPIs")
        print(f"Total new aliases added: {total_new_aliases}")
        print("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    main()
