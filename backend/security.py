import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import ALGORITHM, SECRET_KEY, TOKEN_EXPIRE_MINUTES
from .database import get_db
from .models import Document, User

ROLE_RANK = {"staff": 1, "manager": 2, "admin": 3}
# Minimum role needed to see a document of each confidentiality level
CONF_RANK = {"Public": 1, "Confidential": 2, "Restricted": 3}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


def create_access_token(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": username, "role": role, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_error = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise credentials_error
    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if not user or not user.is_active:
        raise credentials_error
    return user


def require_role(min_role: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[min_role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires '{min_role}' role or higher")
        return user
    return dependency


def allowed_levels(user: User) -> list[str]:
    return [level for level, rank in CONF_RANK.items() if rank <= ROLE_RANK[user.role]]


def can_view(user: User, doc: Document) -> bool:
    if doc.is_archived and user.role != "admin":
        return False
    return CONF_RANK[doc.confidentiality] <= ROLE_RANK[user.role]


def visible_documents(db: Session, user: User, include_archived: bool = False):
    query = db.query(Document).filter(Document.confidentiality.in_(allowed_levels(user)))
    if not (include_archived and user.role == "admin"):
        query = query.filter(Document.is_archived.is_(False))
    return query
