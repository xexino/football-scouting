"""Members of the current organization. Users are global identities; what an organization
administrator manages is the *membership* (role, region, active) in their organization."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..database import get_db
from ..accounts import expiry, invalidate_reset_tokens, invitation_link, new_token, reset_link, send_link
from ..config import settings
from ..subscriptions import enforce_seat_limit
from ..models import Invitation, Membership, PasswordResetToken, User, utcnow
from pydantic import BaseModel, Field

from ..schemas import Role, UserCreate, UserUpdate
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
    enforce_seat_limit(db, ctx.organization)
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        validate_password_strength(body.password)
        user = User(email=email, full_name=body.full_name, hashed_password=hash_password(body.password))
        db.add(user)
        db.flush()
    else:
        # An account owned by someone else (possibly another organization's staff). Adding it
        # directly would attach a person without their consent and disclose their name, so the
        # owner must accept an invitation with their own password instead.
        raise HTTPException(409, "An account with this email already exists. Send an invitation instead; "
                                 "the person accepts it with their own password.")
    m = Membership(user_id=user.id, organization_id=ctx.organization_id, role=body.role, region=body.region)
    db.add(m)
    db.flush()
    audit.log(db, ctx, "member.add", "user", user.id, {"email": email, "role": body.role}, request)
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
    if changes.get("is_active") is True and not m.is_active:
        enforce_seat_limit(db, ctx.organization)
    for k in ("role", "region", "is_active"):
        if k in changes:
            setattr(m, k, changes[k])
    audit.log(db, ctx, "member.update", "user", user_id, changes, request)
    db.commit()
    db.refresh(m)
    return member_out(m)


# --------------------------------------------------------------------------- invitations
class InvitationIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    role: Role
    region: str | None = None


def _invitation_out(inv: Invitation) -> dict:
    status = ("accepted" if inv.accepted_at else "revoked" if inv.revoked_at else
              "expired" if _expired(inv.expires_at) else "pending")
    return {"id": inv.id, "email": inv.email, "role": inv.role, "region": inv.region, "status": status,
            "expires_at": inv.expires_at, "created_at": inv.created_at}


def _expired(ts) -> bool:
    from ..accounts import is_expired
    return is_expired(ts)


@router.get("/invitations", summary="Invitations of this organization")
def list_invitations(ctx: Ctx = Depends(require("users:manage")), db: Session = Depends(get_db)):
    return [_invitation_out(i) for i in db.scalars(select(Invitation).order_by(Invitation.created_at.desc())).all()]


@router.post("/invitations", status_code=201, summary="Invite a person (returns a single-use link, shown once)")
def create_invitation(body: InvitationIn, request: Request, ctx: Ctx = Depends(require("users:manage")),
                      db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing and db.scalar(select(Membership).where(Membership.user_id == existing.id,
                                                        Membership.organization_id == ctx.organization_id,
                                                        Membership.is_active.is_(True))):
        raise HTTPException(409, "This person is already an active member")
    for old in db.scalars(select(Invitation).where(func.lower(Invitation.email) == email,
                                                   Invitation.accepted_at.is_(None),
                                                   Invitation.revoked_at.is_(None))).all():
        old.revoked_at = utcnow()  # only one live invitation per address
    enforce_seat_limit(db, ctx.organization)  # pending invitations count as seats
    raw, digest = new_token()
    inv = Invitation(email=email, role=body.role, region=body.region, token_hash=digest,
                     expires_at=expiry(settings.invitation_ttl_hours), created_by_id=ctx.id)
    db.add(inv)
    db.flush()
    link = invitation_link(request, raw)
    emailed = send_link(email, f"Invitation to {ctx.organization.name}", link)
    audit.log(db, ctx, "member.invite", "invitation", inv.id, {"email": email, "role": body.role}, request)
    db.commit()
    return {**_invitation_out(inv), "invite_url": link, "emailed": emailed,
            "note": "Share this link privately with the invitee. It is shown only once."}


@router.delete("/invitations/{invitation_id}", status_code=204)
def revoke_invitation(invitation_id: int, request: Request, ctx: Ctx = Depends(require("users:manage")),
                      db: Session = Depends(get_db)):
    inv = db.get(Invitation, invitation_id)
    if inv is None:
        raise HTTPException(404, "Invitation not found")
    if inv.accepted_at is None and inv.revoked_at is None:
        inv.revoked_at = utcnow()
    audit.log(db, ctx, "member.invite_revoke", "invitation", inv.id, {"email": inv.email}, request)
    db.commit()


@router.post("/{user_id}/password-reset-link", summary="Create a single-use password reset link for a member")
def password_reset_link(user_id: int, request: Request, ctx: Ctx = Depends(require("users:manage")),
                        db: Session = Depends(get_db)):
    m = _membership(db, ctx, user_id)
    if db.scalar(select(func.count()).select_from(Membership).where(
            Membership.user_id == user_id, Membership.organization_id != ctx.organization_id)):
        raise HTTPException(403, "This account also belongs to another organization; its owner must reset it")
    if m.user.is_platform_admin:
        raise HTTPException(403, "Platform administrator accounts cannot be reset by an organization")
    invalidate_reset_tokens(db, user_id)  # only the newest link is valid
    raw, digest = new_token()
    db.add(PasswordResetToken(user_id=user_id, token_hash=digest, created_by_id=ctx.id,
                              expires_at=expiry(settings.password_reset_ttl_hours)))
    link = reset_link(request, raw)
    emailed = send_link(m.user.email, "Password reset", link)
    audit.log(db, ctx, "member.password_reset_link", "user", user_id, None, request)
    db.commit()
    return {"reset_url": link, "emailed": emailed, "expires_in_hours": settings.password_reset_ttl_hours}
