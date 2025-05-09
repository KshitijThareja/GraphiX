from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from fastapi.security import OAuth2AuthorizationCodeBearer
from pathlib import Path

# Determine the correct .env file path
env_path = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    # Database Configuration
    DATABASE_URL: str = Field(
        default="sqlite:///./graphix.db",
        description="Database connection URL (SQLite or PostgreSQL)"
    )

    # GitHub OAuth Configuration
    GITHUB_CLIENT_ID: Optional[str] = Field(
        None,
        description="GitHub OAuth Client ID"
    )
    GITHUB_CLIENT_SECRET: Optional[str] = Field(
        None,
        description="GitHub OAuth Client Secret"
    )

    # Security Configuration
    SECRET_KEY: str = Field(
        default="dev-secret-key-change-me-in-prod",
        description="Secret key for JWT token signing"
    )
    ALGORITHM: str = Field(
        default="HS256",
        description="JWT signing algorithm"
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60 * 24 * 7,  # 7 days
        description="JWT token expiration time in minutes"
    )

    # OAuth2 Configuration
    OAUTH2_REDIRECT_URI: str = Field(
        default="http://localhost:3000/api/auth/callback/github",
        description="OAuth2 redirect URI"
    )

    GEMINI_API_KEY: str = Field(
        None,
        description="Gemini API key"
    )

    class Config:
        env_file = env_path if env_path.exists() else None
        env_file_encoding = "utf-8"
        extra = "allow"


# Initialize settings
settings = Settings()

# OAuth2 Scheme
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="https://github.com/login/oauth/authorize",
    tokenUrl="token",
    scopes={
        "repo": "Access repositories",
        "user:email": "Get user email"
    }
)

# Database engine configuration
if "sqlite" in settings.DATABASE_URL.lower():
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True
    )
else:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=30
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


Base.metadata.create_all(bind=engine)
