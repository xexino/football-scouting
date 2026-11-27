"""Members of the current organization. Users are global identities; what an organization
administrator manages is the *membership* (role, region, active) in their organization."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..database import get_db
from ..models import Membership, User
from ..schemas import UserCreate, UserUpdate
from ..security import (
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    Ctx,
    get_ctx,
    hash_password,
    require,
    validate_password_strength,
)
from ..serializers import member_out

router = APIRouter(prefix="/api/users", tags=["organization members"])


def _members(db: Session, ctx: Ctx):
    return select(Membership).where(Membership.organization_id == ctx.organization_id) \
        .options(selectinload(Membership.user))


def _membership(db: Session, ctx: Ctx, user_id: int) -> Membership:
    m = db.scalar(_members(db, ctx).where(Membership.user_id == user_id))
    if m is None:
        raise HTTPException(404, "User not found in this organization")
    return m


@router.get("/roles", summary="Roles and their permissions")
def roles(_: Ctx = Depends(get_ctx)):
    return [{"role": r, "label": ROLE_LABELS[r], "permissions": sorted(p)} for r, p in ROLE_PERMISSIONS.items()]


@router.get("/directory", summary="Active members of this organization (for assignment pickers)")
def directory(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    ms = db.scalars(_members(db, ctx).where(Membership.is_active.is_(True))).all()
    ms = [m for m in ms if m.user.is_active]
    return [{"id": m.user.id, "full_name": m.user.full_name, "role": m.role, "region": m.region}
            for m in sorted(ms, key=lambda m: m.user.full_name)]


@router.get("")
def list_users(ctx: Ctx = Depends(require("users:manage")), db: Session = Depends(get_db)):
    return [member_out(m) for m in db.scalars(_members(db, ctx).order_by(Membership.id)).all()]


@router.post("", status_code=201, summary="Add a member (creates the account if the email is new)")
def create_user(body: UserCreate, request: Request, ctx: Ctx = Depends(require("users:manage")),
                db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        validate_password_strength(body.password)
        user = User(email=email, full_name=body.full_name, hashed_password=hash_password(body.password))
        db.add(user)
        db.flush()
        created = True
    else:
        # Existing account (e.g. a consultant working for several clubs): we only add a
        # membership; we never change the credentials of an account we do not own.
        if db.scalar(select(Membership).where(Membership.user_id == user.id,
                                              Membership.organization_id == ctx.organization_id)):
            raise HTTPException(409, "This user is already a member of the organization")
        created = False
    m = Membership(user_id=user.id, organization_id=ctx.organization_id, role=body.role, region=body.region)
    db.add(m)
    db.flush()
    audit.log(db, ctx, "member.add", "user", user.id, {"email": email, "role": body.role, "new_account": created}, request)
    db.commit()
    db.refresh(m)
    return member_out(m)


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, ctx: Ctx = Depends(require("users:manage")),
                db: Session = Depends(get_db)):
    m = _membership(db, ctx, user_id)
    changes = body.model_dump(exclude_unset=True)
    if user_id == ctx.id and (changes.get("is_active") is False or ("role" in changes and changes["role"] != ctx.role)):
        raise HTTPException(400, "You cannot deactivate yourself or change your own role")
    if "password" in changes:
        others = db.scalar(select(func.count()).select_from(Membership).where(
            Membership.user_id == user_id, Membership.organization_id != ctx.organization_id))
        if others:
            raise HTTPException(403, "This account also belongs to another organization; "
                                     "only its owner can change the password")
        validate_password_strength(changes["password"])
        m.user.hashed_password = hash_password(changes.pop("password"))
        m.user.token_version += 1
        changes["password"] = "***changed***"
    if "full_name" in changes:
        others = db.scalar(select(func.count()).select_from(Membership).where(
            Membership.user_id == user_id, Membership.organization_id != ctx.organization_id))
        if others:
            raise HTTPException(403, "This account also belongs to another organization; name changes are not allowed")
        m.user.full_name = changes["full_name"]
    for k in ("role", "region", "is_active"):
        if k in changes:
            setattr(m, k, changes[k])
    audit.log(db, ctx, "member.update", "user", user_id, changes, request)
    db.commit()
    db.refresh(m)
    return member_out(m)
