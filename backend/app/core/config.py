from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Tableau Governance Platform"
    API_V1_STR: str = "/api/v1"
    
    # OpenAI - optional. If not set, AI classification gracefully falls back to mock data.
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini-2"
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # Silently ignore old Postgres/Neo4j vars in .env

settings = Settings()
