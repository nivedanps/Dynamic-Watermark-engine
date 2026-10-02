from typing import List, Sequence
from fastapi import Depends, HTTPException, status
from .models import User, Role
from .auth import get_current_active_user

class RoleChecker:
    """
    Reusable FastAPI dependency to enforce Role-Based Access Control (RBAC).
    """
    def __init__(self, allowed_roles: Sequence[Role]):
        self.allowed_roles = set(allowed_roles)

    def __call__(self, user: User = Depends(get_current_active_user)) -> User:
        if user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role '{user.role}'"
            )
        return user
