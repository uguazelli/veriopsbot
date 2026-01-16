import os
import secrets
from typing import Annotated, Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import APIKeyCookie

security = APIKeyCookie(name="session_token", auto_error=False)


def get_current_username(request: Request):
    token = request.cookies.get("session_token")
    if not token:
        return None

    correct_token = os.getenv("ADMIN_TOKEN", "secret-admin-token")

    if not secrets.compare_digest(token, correct_token):
        return None

    return "admin"


def require_auth(username: Annotated[Optional[str], Depends(get_current_username)]):
    if not username:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )
    return username
