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

    def _make_key(
        self,
        lineage: list[str],
        aggregation: str,
        sector: str | None = None,
        subdomain: str | None = None,
    ) -> str:
        payload = (
            json.dumps(sorted(lineage), sort_keys=True)
            + (aggregation or "").upper()
            + (sector or "")
            + (subdomain or "")
            + self.ontology_version
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(
        self,
        lineage: list[str],
        aggregation: str,
        sector: str | None = None,
        subdomain: str | None = None,
    ) -> dict | None:
        key = self._make_key(lineage, aggregation, sector, subdomain)
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
        lineage: list[str],
        aggregation: str,
        result: dict,
        *,
        sector: str | None = None,
        subdomain: str | None = None,
        commit: bool = True,
    ) -> None:
        key = self._make_key(lineage, aggregation, sector, subdomain)
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
        if commit:
            self.db.commit()

    def flush(self) -> None:
        self.db.commit()
