import os
import logging
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2AuthorizationCodeBearer
from .models.base import Base, engine, settings, get_db
from .routers import auth, analysis
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from .models.user import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
Base.metadata.create_all(bind=engine)
app = FastAPI(
    title="GraphiX API",
    description="GitHub Codebase Evaluation Tool with Callgraphs and LLMs",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{settings.GITHUB_CLIENT_ID}",
    tokenUrl="token",
    scopes={"repo": "Access repositories", "user:email": "Get user email"},
)
app.include_router(auth.router)
app.include_router(analysis.router)


@app.on_event("startup")
async def startup_event():
    try:
        engine.connect()
        logger.info("✅ Database connection established")
    except Exception as e:
        logger.error(f"Failed to connect to database: {str(e)}")
        raise RuntimeError("Failed to connect to database")


@app.on_event("shutdown")
async def shutdown_event():
    engine.dispose()
    logger.info("❌ Database connection closed")


@app.get("/")
async def root():
    return {
        "message": "GraphiX API is running",
        "version": app.version,
        "environment": os.getenv("ENVIRONMENT", "development"),
    }


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str = payload.get("sub")
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.login == username).first()
    if user is None:
        raise credentials_exception
    return user


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=1,
        timeout_keep_alive=120,
    )
