from app.db.session import engine, Base
import app.models.postgres

print("Dropping all tables...")
Base.metadata.drop_all(bind=engine)
print("Creating all tables...")
Base.metadata.create_all(bind=engine)
print("Database cleared successfully.")
