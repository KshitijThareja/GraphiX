import os
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./sql_app.db")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "your_github_client_id")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "your_github_client_secret")
    VECTOR_STORE_DIR: str = os.getenv("VECTOR_STORE_DIR", "./vector_data")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY", None)
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY", None)
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", None)
    DEFAULT_LLM_PROVIDER: str = os.getenv("DEFAULT_LLM_PROVIDER", "openai")
    
    # MongoDB Settings
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "graphix_db")

    class Config:
        env_file = ".env"

settings = Settings()