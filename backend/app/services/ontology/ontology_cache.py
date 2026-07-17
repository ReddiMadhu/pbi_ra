import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.ontology import KPIOntologyCache


class OntologyCache:
    ONTOLOGY_VERSION = "v1"

    def __init__(self, db: Session, ontology_version: str | None = None):
        self.db = db
        self.ontology_version = ontology_version or self.ONTOLOGY_VERSION
        # Track cache keys added to the session but not yet flushed,
        # so duplicates are skipped even when db.no_autoflush is active.
        self._pending_keys: set[str] = set()

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
        # Skip if this key is already pending in the session (unflushed)
        if key in self._pending_keys:
            return
        existing = self.db.query(KPIOntologyCache).filter(KPIOntologyCache.cache_key == key).first()
        if existing:
            return
        row = KPIOntologyCache(
            cache_key=key,
            canonical_kpi_id=result.get("matched_kpi_id"),
            similarity_score=result.get("similarity_score"),
            confidence_score=result.get("confidence_score"),
            similarity_rationale=result.get("similarity_rationale"),
            confidence_rationale=result.get("confidence_rationale"),
            model_used=result.get("model_used"),
            computed_at=datetime.utcnow(),
        )
        self.db.add(row)
        self._pending_keys.add(key)
        if commit:
            self.db.commit()
            self._pending_keys.discard(key)

    def flush(self) -> None:
        self.db.commit()
        self._pending_keys.clear()

    def clear_all(self) -> int:
        """Delete every cache row — call after the ontology bank is modified."""
        count = self.db.query(KPIOntologyCache).delete()
        self.db.commit()
        return count


def invalidate_ontology_cache(db) -> int:
    """Module-level helper: wipe the entire KPI ontology cache table."""
    from app.models.ontology import KPIOntologyCache as _Cache
    count = db.query(_Cache).delete()
    db.commit()
    return count
