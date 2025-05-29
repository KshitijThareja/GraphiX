from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional
from ..services.callgraph import CallgraphGenerator
from ..models.base import oauth2_scheme, Settings
from pydantic import HttpUrl
from jose import JWTError, jwt

router = APIRouter(prefix="/analysis")
settings = Settings()


async def get_current_user(token: str = Depends(oauth2_scheme)):
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
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception


@router.post("/callgraph")
async def generate_callgraph(
    repo_url: HttpUrl,
    token: str = Depends(oauth2_scheme),
    current_user: str = Depends(get_current_user),
):
    generator = CallgraphGenerator()
    try:
        repo_path = await generator.clone_repository(str(repo_url), token)
        callgraph = await generator.analyze_repository(repo_path)
        await generator.cleanup()
        return callgraph
    except Exception as e:
        await generator.cleanup()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate callgraph: {str(e)}",
        )


def _enrich_django(callgraph: dict) -> dict:
    for node in callgraph["nodes"]:
        if "views." in node["id"]:
            node["framework"] = "django"
            node["type"] = "view"
            if node["id"].endswith("View"):
                node["tags"] = ["class-based-view"]
            elif "api_" in node["id"]:
                node["tags"] = ["api-view"]
    return callgraph


def _enrich_flask(callgraph: dict) -> dict:
    for node in callgraph["nodes"]:
        if "routes." in node["id"] or "blueprints." in node["id"]:
            node["framework"] = "flask"
            node["type"] = "route"
            if "get_" in node["id"]:
                node["tags"] = ["http-get"]
            elif "post_" in node["id"]:
                node["tags"] = ["http-post"]
    return callgraph


@router.post("/enrich")
async def enrich_callgraph(
    callgraph: dict,
    framework: Optional[str] = Query(
        None, description="Framework to detect (django, flask, fastapi)"
    ),
    current_user: str = Depends(get_current_user),
):
    try:
        if framework == "django":
            return _enrich_django(callgraph)
        elif framework == "flask":
            return _enrich_flask(callgraph)
        return callgraph
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to enrich callgraph: {str(e)}",
        )
