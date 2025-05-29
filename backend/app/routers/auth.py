from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from jose import jwt
from pydantic import BaseModel
import httpx
from ..models.base import settings, get_db
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from ..models.user import User

router = APIRouter(prefix="/auth")
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="https://github.com/login/oauth/authorize",
    tokenUrl="https://github.com/login/oauth/access_token",
    scopes={"repo": "Access repositories", "user:email": "Get user email"},
)


class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


class GitHubUser(BaseModel):
    id: int
    login: str
    name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    access_token: str


class UserResponse(BaseModel):
    login: str
    name: Optional[str]
    email: Optional[str]
    avatar_url: Optional[str]


GITHUB_CLIENT_ID = settings.GITHUB_CLIENT_ID
GITHUB_CLIENT_SECRET = settings.GITHUB_CLIENT_SECRET
OAUTH2_REDIRECT_URI = settings.OAUTH2_REDIRECT_URI
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = 30


async def get_github_access_token(code: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": OAUTH2_REDIRECT_URI,
            },
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to get access token from GitHub",
            )
        return response.json().get("access_token")


async def get_github_user(access_token: str) -> GitHubUser:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to get user info from GitHub",
            )
        user_data = response.json()
        return GitHubUser(
            id=user_data.get("id"),
            login=user_data.get("login"),
            name=user_data.get("name"),
            email=user_data.get("email"),
            avatar_url=user_data.get("avatar_url"),
            access_token=access_token,
        )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


@router.get("/login")
async def login_github():
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={OAUTH2_REDIRECT_URI}"
        f"&scope=repo"
    )
    return {"url": url}


@router.get("/callback")
async def callback(code: str, db: Session = Depends(get_db)):
    try:
        if not code:
            raise HTTPException(
                status_code=400, detail="Authorization code not provided"
            )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": settings.OAUTH2_REDIRECT_URI,
                },
                headers={"Accept": "application/json"},
            )
        if response.status_code != 200 or "access_token" not in response.json():
            raise HTTPException(
                status_code=400, detail="Failed to obtain access token from GitHub"
            )
        access_token = response.json()["access_token"]
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            if user_response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to fetch user data")
            user_data = user_response.json()
            email_response = await client.get(
                "https://api.github.com/user/emails",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            email = None
            if email_response.status_code == 200:
                emails = email_response.json()
                primary_email = next(
                    (e["email"] for e in emails if e["primary"] and e["verified"]), None
                )
                email = primary_email or user_data.get("email")
        user = db.query(User).filter(User.login == user_data["login"]).first()
        if not user:
            user = User(
                login=user_data["login"],
                email=email,
                avatar_url=user_data.get("avatar_url"),
                access_token=access_token,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            user.email = email
            user.avatar_url = user_data.get("avatar_url")
            user.access_token = access_token
            db.commit()
            db.refresh(user)
        token_data = {"sub": user.login}
        token = jwt.encode(
            token_data, settings.SECRET_KEY, algorithm=settings.ALGORITHM
        )
        return {
            "access_token": token,
            "user": {
                "login": user.login,
                "email": user.email,
                "avatar_url": user.avatar_url,
            },
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process callback: {str(e)}",
        )
