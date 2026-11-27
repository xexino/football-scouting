"""Tenant isolation, enforced centrally in the ORM layer.

Every request-scoped Session carries a *tenant context* in ``session.info["tenant"]``:

* ``NOT_SET`` (default) — any ORM statement touching a tenant table raises
  ``TenantContextMissing`` (fail closed).
* ``<int>``  — an organization id. All SELECT / UPDATE / DELETE statements are rewritten
  with ``with_loader_criteria`` so that

    - :class:`TenantPrivate` rows are visible only when ``organization_id == tenant``;
    - :class:`SharedOrPrivate` rows are visible when ``organization_id IS NULL`` (shared
      reference data) or ``== tenant``.

  The criteria also propagate to relationship / eager loads. On flush, new rows are
  stamped with the tenant id and any insert/update/delete of a row belonging to another
  organization — or of a *shared* reference row — raises ``TenantViolation``.
* ``SYSTEM`` — trusted maintenance code (migrations, CLI, platform operations). No filter.

Routers therefore never need to remember to filter by organization; the explicit checks
they still perform are defence in depth.
"""
from __future__ import annotations

from sqlalchemy import event, or_
from sqlalchemy.sql.util import find_tables
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria


class TenantPrivate:
    """Marker: row belongs to exactly one organization (``organization_id``)."""


class SharedOrPrivate:
    """Marker: ``organization_id`` NULL = shared reference row, else private to that org."""


class _Sentinel:
    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return self.name


NOT_SET = _Sentinel("NOT_SET")
SYSTEM = _Sentinel("SYSTEM")


class TenantContextMissing(RuntimeError):
    pass


class TenantViolation(PermissionError):
    pass


def set_tenant(session: Session, tenant) -> None:
    session.info["tenant"] = tenant


def get_tenant(session: Session):
    return session.info.get("tenant", NOT_SET)


def _is_tenant_class(cls) -> bool:
    return isinstance(cls, type) and issubclass(cls, (TenantPrivate, SharedOrPrivate))


_CLASSES: tuple[list, list] | None = None
_TABLES: set[str] | None = None


def _touches_tenant(state: ORMExecuteState) -> bool:
    """True if the statement involves a tenant table — via mapped entities *or* raw FROM
    clauses (e.g. ``select(func.count()).select_from(Model)``, joins, subqueries)."""
    global _TABLES
    if any(_is_tenant_class(m.class_) for m in state.all_mappers):
        return True
    if _TABLES is None:
        private, shared = _tenant_classes(state.session)
        _TABLES = {c.__table__.name for c in private + shared}
    tables = find_tables(state.statement, check_columns=True, include_aliases=True, include_joins=True,
                         include_selects=True, include_crud=True)
    return any(getattr(t, "name", None) in _TABLES for t in tables)


def _tenant_classes(session: Session) -> tuple[list, list]:
    """Concrete mapped classes per marker (computed once from the mapper registry)."""
    global _CLASSES
    if _CLASSES is None:
        from .database import Base
        classes = [m.class_ for m in Base.registry.mappers]
        _CLASSES = ([c for c in classes if issubclass(c, TenantPrivate)],
                    [c for c in classes if issubclass(c, SharedOrPrivate)])
    return _CLASSES


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_criteria(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    tenant = get_tenant(state.session)
    if tenant is SYSTEM:
        return
    if state.is_column_load or state.is_relationship_load:
        # criteria were attached to the parent statement and propagate automatically
        if tenant is NOT_SET and _touches_tenant(state):
            raise TenantContextMissing("Tenant context required")
        return
    if tenant is NOT_SET:
        if not state.is_orm_statement or _touches_tenant(state):
            raise TenantContextMissing("Tenant context required for this query")
        return
    if not state.is_orm_statement:
        raise TenantViolation("Core SQL statements are not allowed in a tenant context")
    private, shared = _tenant_classes(state.session)
    opts = [with_loader_criteria(c, c.organization_id == tenant, include_aliases=True) for c in private]
    opts += [with_loader_criteria(c, or_(c.organization_id.is_(None), c.organization_id == tenant),
                                  include_aliases=True) for c in shared]
    state.statement = state.statement.options(*opts)


@event.listens_for(Session, "before_flush")
def _guard_writes(session: Session, _ctx, _instances) -> None:
    tenant = get_tenant(session)
    if tenant is SYSTEM:
        return
    for obj in session.new:
        if not _is_tenant_class(type(obj)):
            continue
        if tenant is NOT_SET:
            raise TenantContextMissing(f"Tenant context required to create {type(obj).__name__}")
        if obj.organization_id is None:
            obj.organization_id = tenant
        elif obj.organization_id != tenant:
            raise TenantViolation(f"Cannot create {type(obj).__name__} for another organization")
    for obj in list(session.dirty) + list(session.deleted):
        if not _is_tenant_class(type(obj)):
            continue
        if obj in session.dirty and not session.is_modified(obj, include_collections=False):
            continue
        if tenant is NOT_SET:
            raise TenantContextMissing(f"Tenant context required to modify {type(obj).__name__}")
        if obj.organization_id != tenant:
            what = "shared reference data" if obj.organization_id is None else "another organization's data"
            raise TenantViolation(f"Cannot modify {what} ({type(obj).__name__})")
