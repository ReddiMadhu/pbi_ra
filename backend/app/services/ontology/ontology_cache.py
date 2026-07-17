import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.ontology import KPIOntologyCache


class OntologyCache:
    ONTOLOGY_VERSION = "v1"

    def __init__(self, db: Session, ontology_version: str | None = None):
        self.db = db
        self.ontology_version = ontology_version or self.ONTOLOGY_VERSION
        # Pending rows stored in-memory (keyed by cache_key) instead of
        # being added to the SQLAlchemy session.  This avoids duplicate
        # INSERT attempts entirely — the session never sees these objects
        # until flush() writes them with INSERT OR IGNORE.
        self._pending_rows: dict[str, dict] = {}

    def _make_key(
        self,
        kpi_name: str,
        lineage: list[str],
        aggregation: str,
        sector: str | None = None,
        subdomain: str | None = None,
    ) -> str:
        # Normalize: treat UNKNOWN/NONE as empty for cache purposes
        agg = (aggregation or "").upper()
        if agg in ("UNKNOWN", "NONE", ""):
            agg = ""
        payload = (
            (kpi_name or "").strip().lower()
            + json.dumps(sorted(lineage), sort_keys=True)
            + agg
            + (sector or "")
            + (subdomain or "")
            + self.ontology_version
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(
        self,
        kpi_name: str,
        lineage: list[str],
        aggregation: str,
        sector: str | None = None,
        subdomain: str | None = None,
    ) -> dict | None:
        key = self._make_key(kpi_name, lineage, aggregation, sector, subdomain)

        # Check in-memory pending rows first (these haven't been flushed yet)
        if key in self._pending_rows:
            row_data = self._pending_rows[key]
            return {
                "matched_kpi_id": row_data["canonical_kpi_id"],
                "similarity_score": row_data["similarity_score"],
                "confidence_score": row_data["confidence_score"],
                "similarity_rationale": row_data["similarity_rationale"],
                "confidence_rationale": row_data["confidence_rationale"],
                "model_used": row_data["model_used"],
            }

        # Fall back to database query
        row = self.db.query(KPIOntologyCache).filter(KPIOntologyCache.cache_key == key).first()
        if not row:
            return None
        return {
            "matched_kpi_id": row.canonical_kpi_id,
            "similarity_score": row.similarity_score,
            "confidence_score": row.confidence_score,
            "similarity_rationale": row.similarity_rationale,
            "confidence_rationale": row.confidence_rationale,
            "model_used": row.model_used,
        }

    def set(
        self,
        kpi_name: str,
        lineage: list[str],
        aggregation: str,
        result: dict,
        *,
        sector: str | None = None,
        subdomain: str | None = None,
        commit: bool = True,
    ) -> None:
        key = self._make_key(kpi_name, lineage, aggregation, sector, subdomain)

        # Already pending — skip
        if key in self._pending_rows:
            return

        row_data = {
            "cache_key": key,
            "canonical_kpi_id": result.get("matched_kpi_id"),
            "similarity_score": result.get("similarity_score"),
            "confidence_score": result.get("confidence_score"),
            "similarity_rationale": result.get("similarity_rationale"),
            "confidence_rationale": result.get("confidence_rationale"),
            "model_used": result.get("model_used"),
            "computed_at": datetime.utcnow(),
        }
        self._pending_rows[key] = row_data

        if commit:
            self.flush()

    def flush(self) -> None:
        """Write all pending rows to the database using INSERT OR IGNORE,
        then commit.  This is safe against duplicate keys from prior runs
        or concurrent sessions."""
        if self._pending_rows:
            for row_data in self._pending_rows.values():
                stmt = (
                    sqlite_insert(KPIOntologyCache)
                    .values(**row_data)
                    .on_conflict_do_nothing(index_elements=["cache_key"])
                )
                self.db.execute(stmt)
            self._pending_rows.clear()
        self.db.commit()

    def clear_all(self) -> int:
        """Delete every cache row — call after the ontology bank is modified."""
        count = self.db.query(KPIOntologyCache).delete()
        self.db.commit()
        self._pending_rows.clear()
        return count


def invalidate_ontology_cache(db) -> int:
    """Module-level helper: wipe the entire KPI ontology cache table."""
    from app.models.ontology import KPIOntologyCache as _Cache
    count = db.query(_Cache).delete()
    db.commit()
    return count
