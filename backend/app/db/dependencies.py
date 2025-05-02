from sqlalchemy.orm import Session
from ..models.base import SessionLocal

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()