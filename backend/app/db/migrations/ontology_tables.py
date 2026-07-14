"""Standalone migration script for ontology + rationalization tables."""
from sqlalchemy import text

from app.db.session import engine, Base
import app.models.postgres  # noqa: F401
import app.models.ontology  # noqa: F401
import app.models.rationalization  # noqa: F401


def migrate_ontology_kpi_scoped_unique(conn) -> bool:
    """
    Replace UNIQUE(name) with UNIQUE(name, sector, subdomain).

    Same Measurement(KPI) can exist in Marketing and Distribution independently.
    Returns True if a rebuild was performed.
    """
    tables = {
        r[0]
        for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
    }
    if "ontology_kpis" not in tables:
        return False

    name_only_unique = False
    for idx in conn.execute(text("PRAGMA index_list('ontology_kpis')")).fetchall():
        # seq, name, unique, origin, partial
        is_unique = bool(idx[2])
        idx_name = idx[1]
        if not is_unique:
            continue
        cols = [
            row[2]
            for row in conn.execute(text(f"PRAGMA index_info('{idx_name}')")).fetchall()
        ]
        if cols == ["name"]:
            name_only_unique = True
            break

    if not name_only_unique:
        row = conn.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='ontology_kpis'"
            )
        ).fetchone()
        create_sql = (row[0] or "").lower() if row else ""
        # Column-level UNIQUE on name (SQLAlchemy default): name VARCHAR NOT NULL UNIQUE
        if "name" in create_sql and "unique" in create_sql:
            # only rebuild if composite unique not already declared on table
            if "uq_okpi_name_sector_subdomain" not in create_sql:
                # Heuristic: "name ... unique" appears before other constraints
                name_pos = create_sql.find("name")
                if name_pos >= 0 and "unique" in create_sql[name_pos : name_pos + 80]:
                    name_only_unique = True

    # Always ensure composite unique index exists when possible
    try:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_okpi_name_sector_subdomain "
                "ON ontology_kpis (name, sector, subdomain)"
            )
        )
    except Exception:
        # May fail if old name-only unique still blocks rebuild path
        pass

    if not name_only_unique:
        return False

    conn.execute(text("DROP TABLE IF EXISTS ontology_kpis__scoped_mig"))
    conn.execute(
        text(
            """
            CREATE TABLE ontology_kpis__scoped_mig (
                kpi_id VARCHAR NOT NULL PRIMARY KEY,
                name VARCHAR NOT NULL,
                definition TEXT NOT NULL,
                domain VARCHAR,
                sector VARCHAR,
                subdomain VARCHAR,
                aliases TEXT,
                aggregation_type VARCHAR,
                valid_dimensions TEXT,
                representative_lineage TEXT,
                created_by VARCHAR NOT NULL,
                created_at DATETIME,
                status VARCHAR,
                embedding BLOB
            )
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO ontology_kpis__scoped_mig (
                kpi_id, name, definition, domain, sector, subdomain,
                aliases, aggregation_type, valid_dimensions, representative_lineage,
                created_by, created_at, status, embedding
            )
            SELECT
                kpi_id, name, definition, domain, sector, subdomain,
                aliases, aggregation_type, valid_dimensions, representative_lineage,
                created_by, created_at, status, embedding
            FROM ontology_kpis
            """
        )
    )
    conn.execute(text("DROP TABLE ontology_kpis"))
    conn.execute(text("ALTER TABLE ontology_kpis__scoped_mig RENAME TO ontology_kpis"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ontology_kpis_name ON ontology_kpis (name)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ontology_kpis_sector ON ontology_kpis (sector)"))
    conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_ontology_kpis_subdomain ON ontology_kpis (subdomain)")
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_okpi_sector_subdomain_status "
            "ON ontology_kpis (sector, subdomain, status)"
        )
    )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_okpi_name_sector_subdomain "
            "ON ontology_kpis (name, sector, subdomain)"
        )
    )
    return True


def run():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        rebuilt = migrate_ontology_kpi_scoped_unique(conn)
    print(
        "Ontology and rationalization tables ready."
        + (" Rebuilt ontology_kpis unique(name,sector,subdomain)." if rebuilt else "")
    )


if __name__ == "__main__":
    run()
