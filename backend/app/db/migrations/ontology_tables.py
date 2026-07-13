"""Standalone migration script for ontology + rationalization tables."""
from app.db.session import engine, Base
import app.models.postgres  # noqa: F401
import app.models.ontology  # noqa: F401
import app.models.rationalization  # noqa: F401


def run():
    Base.metadata.create_all(bind=engine)
    print("Ontology and rationalization tables created.")


if __name__ == "__main__":
    run()
