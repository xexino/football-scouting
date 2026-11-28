from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..accounts import ensure_usable, hash_token
from ..models import Invitation, Membership, Organization, PasswordResetToken, User, utcnow
from ..schemas import PasswordChange
from ..security import (
    check_login_allowed,
    clear_failed_logins,
    create_access_token,
    decode_token,
    get_current_user,
    hash_password,
    oauth2_scheme,
    record_failed_login,
    validate_password_strength,
    verify_password,
)
from ..serializers import me_out
from ..tenancy import SYSTEM, set_tenant

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _active_memberships(db: Session, user: User) -> list[Membership]:
    return [m for m in db.scalars(select(Membership).where(Membership.user_id == user.id,
                                                           Membership.is_active.is_(True))).all()
            if m.organization.status != "pending_deletion"]


@router.post("/token", summary="Log in (OAuth2 password flow) and obtain a bearer token")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    set_tenant(db, SYSTEM)  # trusted auth operation: reads identities, writes audit rows
    email = form.username.strip().lower()
    ip = request.client.host if request.client else None  # behind a proxy: run uvicorn with --proxy-headers
    check_login_allowed(db, email, ip)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not user.is_active or not verify_password(form.password, user.hashed_password):
        record_failed_login(db, email, ip)
        audit.log(db, None, "auth.login_failed", "user", None, {"email": email}, request)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    memberships = sorted(_active_memberships(db, user), key=lambda m: m.organization.name.lower())
    if not memberships and not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is not attached to any active organization")
    clear_failed_logins(db, email)
    user.last_login_at = utcnow()
    org_id = memberships[0].organization_id if memberships else None
    audit.log(db, user, "auth.login", "user", user.id, None, request, organization_id=org_id)
    db.commit()
    return {"access_token": create_access_token(user, org_id), "token_type": "bearer", "organization_id": org_id}


class SwitchOrg(BaseModel):
    organization_id: int


@router.post("/switch-organization", summary="Get a token for another organization you belong to")
def switch_org(body: SwitchOrg, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    set_tenant(db, SYSTEM)
    m = next((m for m in _active_memberships(db, user) if m.organization_id == body.organization_id), None)
    if m is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a member of this organization")
    audit.log(db, user, "auth.switch_organization", "organization", m.organization_id, None, request,
              organization_id=m.organization_id)
    db.commit()
    return {"access_token": create_access_token(user, m.organization_id), "token_type": "bearer",
            "organization_id": m.organization_id}


@router.get("/me", summary="Current user, organizations, active organization and permissions")
def me(token: str = Depends(oauth2_scheme), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..security import Ctx
    org_id = decode_token(token).get("org")
    ctx = None
    if isinstance(org_id, int):
        m = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.organization_id == org_id,
                                                Membership.is_active.is_(True)))
        org = db.get(Organization, org_id)
        if m is not None and org is not None and org.status != "pending_deletion":
            ctx = Ctx(user=user, membership=m, organization=org)
    return me_out(user, ctx)


@router.post("/change-password", summary="Change password; revokes all other sessions and returns a new token")
def change_password(body: PasswordChange, request: Request, token: str = Depends(oauth2_scheme),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    validate_password_strength(body.new_password)
    set_tenant(db, SYSTEM)
    user.hashed_password = hash_password(body.new_password)
    user.token_version += 1  # revoke every other session
    org_id = decode_token(token).get("org")
    audit.log(db, user, "auth.password_changed", "user", user.id, None, request,
              organization_id=org_id if isinstance(org_id, int) else None)
    db.commit()
    return {"access_token": create_access_token(user, org_id if isinstance(org_id, int) else None),
            "token_type": "bearer"}


# --------------------------------------------------------------------------- invitations (public)
def _invitation(db: Session, raw: str) -> Invitation:
    set_tenant(db, SYSTEM)  # looked up by secret token before the user is authenticated
    return db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(raw)))


@router.get("/invitations/{token}", summary="Preview an invitation (public)")
def preview_invitation(token: str, db: Session = Depends(get_db)):
    inv = _invitation(db, token)
    ensure_usable(inv, "invitation")
    org = db.get(Organization, inv.organization_id)
    exists = db.scalar(select(User.id).where(func.lower(User.email) == inv.email)) is not None
    return {"organization": org.name, "email": inv.email, "role": inv.role, "existing_account": exists,
            "expires_at": inv.expires_at}


class AcceptInvitation(BaseModel):
    token: str
    password: str
    full_name: str | None = None


@router.post("/invitations/accept", summary="Accept an invitation (public). Existing accounts confirm with their password")
def accept_invitation(body: AcceptInvitation, request: Request, db: Session = Depends(get_db)):
    inv = _invitation(db, body.token)
    ensure_usable(inv, "invitation")
    org = db.get(Organization, inv.organization_id)
    if org is None or org.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This organization is not active")
    from ..subscriptions import assert_writable
    assert_writable(db, org, "POST")  # no new members while the workspace is read-only
    user = db.scalar(select(User).where(func.lower(User.email) == inv.email))
    if user is None:
        if not body.full_name or len(body.full_name.strip()) < 2:
            raise HTTPException(422, "Full name is required")
        validate_password_strength(body.password)
        user = User(email=inv.email, full_name=body.full_name.strip(), hashed_password=hash_password(body.password))
        db.add(user)
        db.flush()
    elif not user.is_active or not verify_password(body.password, user.hashed_password):
        # proves the invitee controls the existing account; a leaked link cannot attach someone else's account
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Enter the current password of your existing account")
    m = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.organization_id == org.id))
    if m is None:
        db.add(Membership(user_id=user.id, organization_id=org.id, role=inv.role, region=inv.region))
    else:
        m.is_active, m.role, m.region = True, inv.role, inv.region
    inv.accepted_at = utcnow()
    audit.log(db, user, "member.invite_accepted", "invitation", inv.id, {"email": inv.email, "role": inv.role},
              request, organization_id=org.id)
    db.commit()
    return {"access_token": create_access_token(user, org.id), "token_type": "bearer", "organization_id": org.id}


class ResetPassword(BaseModel):
    token: str
    new_password: str


@router.post("/password-reset", summary="Set a new password with a reset link (public)")
def reset_password(body: ResetPassword, request: Request, db: Session = Depends(get_db)):
    set_tenant(db, SYSTEM)
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(body.token)))
    ensure_usable(row, "password reset")
    validate_password_strength(body.new_password)
    user = db.get(User, row.user_id)
    user.hashed_password = hash_password(body.new_password)
    user.token_version += 1
    row.used_at = utcnow()
    audit.log(db, user, "auth.password_reset", "user", user.id, None, request)
    db.commit()
    return {"status": "ok"}
