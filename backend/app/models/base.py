from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from fastapi.security import OAuth2AuthorizationCodeBearer
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / ".env"

class Settings(BaseSettings):
    DATABASE_URL: str = Field(
        default="sqlite:///./graphix.db",
        description="Database connection URL (SQLite or PostgreSQL)",
    )
    GITHUB_CLIENT_ID: Optional[str] = Field(None, description="GitHub OAuth Client ID")
    GITHUB_CLIENT_SECRET: Optional[str] = Field(
        None, description="GitHub OAuth Client Secret"
    )
    SECRET_KEY: str = Field(
        default="dev-secret-key-change-me-in-prod",
        description="Secret key for JWT token signing",
    )
    ALGORITHM: str = Field(default="HS256", description="JWT signing algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60 * 24 * 7, description="JWT token expiration time in minutes"
    )
    OAUTH2_REDIRECT_URI: str = Field(
        default="http://localhost:3000/api/auth/callback/github",
        description="OAuth2 redirect URI",
    )
    GEMINI_API_KEY: str = Field(None, description="Gemini API key")
    
    # LLM Provider settings
    OPENAI_API_KEY: Optional[str] = Field(None, description="OpenAI API key")
    OPENAI_MODEL: Optional[str] = Field("gpt-3.5-turbo", description="Default OpenAI model")
    ANTHROPIC_API_KEY: Optional[str] = Field(None, description="Anthropic API key")
    ANTHROPIC_MODEL: Optional[str] = Field("claude-3-sonnet-20240229", description="Default Anthropic model")
    DEFAULT_LLM_PROVIDER: Optional[str] = Field("openai", description="Default LLM provider to use")
    
    # Vector store settings
    VECTOR_STORE_DIR: Optional[str] = Field(None, description="Directory to store vector embeddings")
    VECTOR_STORE_PROVIDER: Optional[str] = Field("chroma", description="Vector store provider")

    class Config:
        env_file = env_path if env_path.exists() else None
        env_file_encoding = "utf-8"
        extra = "allow"


settings = Settings()
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="https://github.com/login/oauth/authorize",
    tokenUrl="token",
    scopes={"repo": "Access repositories", "user:email": "Get user email"},
)
if "sqlite" in settings.DATABASE_URL.lower():
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
else:
    engine = create_engine(
        settings.DATABASE_URL, pool_pre_ping=True, pool_size=20, max_overflow=30
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


Base.metadata.create_all(bind=engine)
