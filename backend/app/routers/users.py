from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..models import User
from ..schemas import UserCreate, UserUpdate
from ..security import (
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    get_current_user,
    hash_password,
    require,
    validate_password_strength,
)
from ..serializers import user_out

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/roles", summary="Roles and their permissions")
def roles(_: User = Depends(get_current_user)):
    return [{"role": r, "label": ROLE_LABELS[r], "permissions": sorted(p)} for r, p in ROLE_PERMISSIONS.items()]


@router.get("/directory", summary="Minimal list of active users (for assignment pickers)")
def directory(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all()
    return [{"id": u.id, "full_name": u.full_name, "role": u.role, "region": u.region} for u in users]


@router.get("")
def list_users(_: User = Depends(require("users:manage")), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id)).all()]


@router.post("", status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require("users:manage")),
                db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "A user with this email already exists")
    validate_password_strength(body.password)
    user = User(email=email, full_name=body.full_name, role=body.role, region=body.region,
                hashed_password=hash_password(body.password))
    db.add(user)
    db.flush()
    audit.log(db, admin, "user.create", "user", user.id, {"email": email, "role": body.role}, request)
    db.commit()
    return user_out(user)


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, admin: User = Depends(require("users:manage")),
                db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (changes.get("is_active") is False or ("role" in changes and changes["role"] != admin.role)):
        raise HTTPException(400, "You cannot deactivate yourself or change your own role")
    if "password" in changes:
        validate_password_strength(changes["password"])
        user.hashed_password = hash_password(changes.pop("password"))
        changes["password"] = "***changed***"
    for k, v in changes.items():
        if k != "password":
            setattr(user, k, v)
    audit.log(db, admin, "user.update", "user", user.id, changes, request)
    db.commit()
    return user_out(user)
