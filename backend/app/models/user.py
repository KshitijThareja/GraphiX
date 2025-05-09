from sqlalchemy import Column, Integer, String, Boolean
from ..models.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    github_id = Column(Integer, unique=True, index=True)
    login = Column(String, unique=True, index=True)
    name = Column(String)
    email = Column(String)
    avatar_url = Column(String)
    access_token = Column(String)
    is_active = Column(Boolean, default=True)
