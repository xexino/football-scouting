from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..models import Membership, Organization, User, utcnow
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
    check_login_allowed(email)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not user.is_active or not verify_password(form.password, user.hashed_password):
        record_failed_login(email)
        audit.log(db, None, "auth.login_failed", "user", None, {"email": email}, request)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    memberships = sorted(_active_memberships(db, user), key=lambda m: m.organization.name.lower())
    if not memberships and not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is not attached to any active organization")
    clear_failed_logins(email)
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
