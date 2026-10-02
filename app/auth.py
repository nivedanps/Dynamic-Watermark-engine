from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from jose import JWTError, jwt, ExpiredSignatureError
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from .config import settings
from .models import TokenData, User, UserInDB, Role

# Initialize PasswordHash using pwdlib with Argon2
password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# In-memory repository with pre-computed Argon2 hashes (no runtime hashing on import)
fake_users_db: Dict[str, dict] = {
    "admin1": {
        "username": "admin1",
        "user_id": "USR-001",
        "school_name": "Excelsoft Academy",
        "role": Role.ADMIN,
        "hashed_password": "$argon2id$v=19$m=65536,t=3,p=4$sFoJKvXc+Ou4A5LzPzeorQ$zOWrWFoLX7bUKLPh3ZCBR4nwG0rjm/dmBkQWFXGo2Cc",
        "disabled": False,
    },
    "teacher1": {
        "username": "teacher1",
        "user_id": "USR-002",
        "school_name": "Excelsoft Academy",
        "role": Role.TEACHER,
        "hashed_password": "$argon2id$v=19$m=65536,t=3,p=4$hVLYJAn/YykHWSOWel/B8A$6laxo0YkotnwKLh/fGsKwcY6zyboeaME/fObjpK9KHg",
        "disabled": False,
    },
    "student1": {
        "username": "student1",
        "user_id": "USR-003",
        "school_name": "Excelsoft Academy",
        "role": Role.STUDENT,
        "hashed_password": "$argon2id$v=19$m=65536,t=3,p=4$1SFDP4SINU+PlEJh69Sr8Q$vBfoM+flTpCQw1sWuLWXX8GvzzW4tF9zrIuuxkEA8JE",
        "disabled": False,
    },
}

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against the stored Argon2 hash."""
    return password_hash.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Generates an Argon2 hash from a plain password string."""
    return password_hash.hash(password)

def get_user(db: Dict[str, dict], username: str) -> Optional[UserInDB]:
    """Fetches user record from the repository."""
    if username in db:
        user_dict = db[username]
        return UserInDB(**user_dict)
    return None

def authenticate_user(db: Dict[str, dict], username: str, password: str) -> Optional[UserInDB]:
    """Authenticates credentials against the user database."""
    user = get_user(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Creates a signed HS256 JWT access token with expiration and claims."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def decode_jwt_token(token: str) -> User:
    """Decodes JWT, validates identity claims, and retrieves the active user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: Optional[str] = payload.get("sub")
        user_id: Optional[str] = payload.get("user_id")
        role_str: Optional[str] = payload.get("role")

        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username, user_id=user_id, role=Role(role_str) if role_str else None)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (JWTError, ValueError):
        raise credentials_exception

    user = get_user(fake_users_db, username=token_data.username)
    if user is None:
        raise credentials_exception
    return User(
        username=user.username,
        user_id=user.user_id,
        school_name=user.school_name,
        role=user.role,
        disabled=user.disabled
    )

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Dependency that resolves the active user from Bearer token."""
    return decode_jwt_token(token)

async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Ensures that the authenticated user account is active."""
    if current_user.disabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    return current_user

