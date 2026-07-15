"""Database seeder to initialize curated Ontology KPIs from JSON seed file."""

import json
import base64
import os
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.ontology import OntologyKPI

SEED_FILE = os.path.join(os.path.dirname(__file__), "ontology_kpis.json")


def seed_ontology_kpis(db: Session) -> int:
    """Seed ontology_kpis table from the local JSON file if empty."""
    try:
        # Check if table is already populated
        existing_count = db.query(OntologyKPI).count()
        if existing_count > 0:
            print(f"OntologyKPI table already has {existing_count} rows. Skipping seeding.")
            return 0

        if not os.path.exists(SEED_FILE):
            print(f"Warning: Seed file not found at {SEED_FILE}")
            return 0

        with open(SEED_FILE, "r", encoding="utf-8") as f:
            kpis = json.load(f)

        print(f"Loading {len(kpis)} KPIs from JSON seed file...")
        count = 0
        for k in kpis:
            # Decode base64 binary embedding back to raw bytes
            emb_bytes = None
            if k.get("embedding"):
                try:
                    emb_bytes = base64.b64decode(k["embedding"])
                except Exception:
                    pass

            # Parse datetime fields
            created_at = None
            if k.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(k["created_at"])
                except Exception:
                    created_at = datetime.utcnow()
            else:
                created_at = datetime.utcnow()

            # Decode JSON list strings if they were exported as stringified JSON
            def _parse_json_list(val):
                if not val:
                    return "[]"
                if isinstance(val, list):
                    return json.dumps(val)
                return str(val)

            kpi_obj = OntologyKPI(
                kpi_id=k["kpi_id"],
                name=k["name"],
                definition=k["definition"],
                domain=k.get("domain"),
                sector=k.get("sector"),
                subdomain=k.get("subdomain"),
                aliases=_parse_json_list(k.get("aliases")),
                aggregation_type=k.get("aggregation_type", "UNKNOWN"),
                valid_dimensions=_parse_json_list(k.get("valid_dimensions")),
                representative_lineage=_parse_json_list(k.get("representative_lineage")),
                created_by=k.get("created_by", "excel_seed"),
                created_at=created_at,
                status=k.get("status", "active"),
                embedding=emb_bytes,
            )
            db.add(kpi_obj)
            count += 1

        db.commit()
        print(f"Seeding completed successfully. Seeded {count} curated KPIs.")
        return count
    except Exception as e:
        db.rollback()
        print(f"Error seeding Curated KPIs: {e}")
        return 0
