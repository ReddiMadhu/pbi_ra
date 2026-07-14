"""One-time seed of ontology_kpis from existing dashboard AI summaries."""
import json
import uuid

from app.db.session import SessionLocal
from app.models.ontology import OntologyKPI
from app.models.postgres import Dashboard
from app.api.v1.kpi_graph import get_kpi_clusters
from app.services.ontology.embedding_service import embed_ontology_kpis


def bootstrap(min_kpis: int = 30) -> int:
    from app.db.session import engine, Base
    import app.models.ontology  # noqa: F401

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing = db.query(OntologyKPI).count()
        if existing >= min_kpis:
            print(f"Ontology bank already has {existing} KPIs; skipping bootstrap.")
            return existing

        unique_names: set[str] = set()
        kpi_defs: dict[str, str] = {}
        kpi_domains: dict[str, str] = {}

        for dash in db.query(Dashboard).all():
            if not dash.ai_summary:
                continue
            try:
                data = json.loads(dash.ai_summary) if dash.ai_summary.startswith("{") else {}
            except Exception:
                continue
            domain = dash.domain_classification or "General"
            for k in data.get("kpis", []):
                if isinstance(k, dict) and k.get("name"):
                    name = k["name"]
                    unique_names.add(name)
                    kpi_defs[name] = k.get("definition", "") or name
                    kpi_domains[name] = domain
                elif isinstance(k, str):
                    unique_names.add(k)
                    kpi_defs[k] = k
                    kpi_domains[k] = domain

        if not unique_names:
            print("No KPIs found in dashboard summaries.")
            return 0

        clusters = get_kpi_clusters(tuple(sorted(unique_names)))
        canonical_to_aliases: dict[str, set[str]] = {}
        for original, canonical in clusters.items():
            canonical_to_aliases.setdefault(canonical, set()).add(original)

        inserted = 0
        for canonical, aliases in canonical_to_aliases.items():
            if db.query(OntologyKPI).filter(OntologyKPI.name == canonical).first():
                continue
            alias_list = sorted(a for a in aliases if a != canonical)
            definition = kpi_defs.get(canonical) or next(
                (kpi_defs.get(a, "") for a in alias_list), canonical
            )
            domain = kpi_domains.get(canonical) or next(
                (kpi_domains.get(a, "General") for a in alias_list), "General"
            )
            db.add(
                OntologyKPI(
                    kpi_id=str(uuid.uuid4()),
                    name=canonical,
                    definition=definition or canonical,
                    domain=domain,
                    aliases=json.dumps(alias_list),
                    aggregation_type="UNKNOWN",
                    created_by="bootstrap_script",
                    status="active",
                )
            )
            inserted += 1

        db.commit()
        embed_ontology_kpis(db)
        total = db.query(OntologyKPI).count()
        print(f"Bootstrap complete: inserted {inserted}, total {total} KPIs.")
        return total
    finally:
        db.close()


if __name__ == "__main__":
    bootstrap()
