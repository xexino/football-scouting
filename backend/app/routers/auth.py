from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..models import User, utcnow
from ..schemas import PasswordChange
from ..security import (
    check_login_allowed,
    clear_failed_logins,
    create_access_token,
    get_current_user,
    hash_password,
    record_failed_login,
    validate_password_strength,
    verify_password,
)
from ..serializers import user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/token", summary="Log in (OAuth2 password flow) and obtain a bearer token")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = form.username.strip().lower()
    check_login_allowed(email)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not user.is_active or not verify_password(form.password, user.hashed_password):
        record_failed_login(email)
        audit.log(db, None, "auth.login_failed", "user", None, {"email": email}, request)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    clear_failed_logins(email)
    user.last_login_at = utcnow()
    audit.log(db, user, "auth.login", "user", user.id, None, request)
    db.commit()
    return {"access_token": create_access_token(user), "token_type": "bearer", "user": user_out(user)}


@router.get("/me", summary="Current user and permissions")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.post("/change-password", status_code=204)
def change_password(body: PasswordChange, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    validate_password_strength(body.new_password)
    user.hashed_password = hash_password(body.new_password)
    audit.log(db, user, "auth.password_changed", "user", user.id, None, request)
    db.commit()
