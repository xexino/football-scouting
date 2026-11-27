"""SQLAlchemy ORM models.

Design principles:
* Every factual record (player profile, statistics) carries provenance: a data source,
  a ``last_updated`` timestamp and an ``is_fictional`` flag.
* Statistics columns are nullable. ``NULL`` means *not provided by the source*; it is
  never silently converted to zero.
* Scout opinions (match reports, video observations, scouting reports) are stored
  separately from verified data and always reference their author.

Multi-tenancy (see app/tenancy.py and docs/saas/01_ARCHITECTURE_AUDIT.md):
* ``TenantPrivate`` models belong to exactly one organization.
* ``SharedOrPrivate`` models are shared reference data when ``organization_id IS NULL``
  (curated by the platform) and private to one organization otherwise.
* Uniqueness is enforced per organization (partial unique indexes for shared rows).
* Child rows that must live in the same organization as their parent use composite
  foreign keys ``(parent_id, organization_id)``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .tenancy import SharedOrPrivate, TenantPrivate


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- enums
ROLES = (
    "administrator",          # organization administrator (club IT / owner)
    "sporting_director",
    "head_of_scouting",
    "data_analyst",
    "video_scout",
    "regional_scout",
)

POSITIONS = ("GK", "CB", "FB", "DM", "CM", "AM", "W", "ST")
POSITION_LABELS = {
    "GK": "Goalkeeper",
    "CB": "Centre-back",
    "FB": "Full-back / Wing-back",
    "DM": "Defensive midfielder",
    "CM": "Central midfielder",
    "AM": "Attacking midfielder",
    "W": "Winger",
    "ST": "Striker",
}

FEET = ("left", "right", "both")

AVAILABILITY = (
    "available",          # club open to sale / player seeking move
    "transfer_listed",
    "loan_possible",
    "free_agent",         # currently without club
    "contract_expiring",  # within 12 months
    "not_available",
    "unknown",
)

PIPELINE_STAGES = (
    "identified",
    "under_observation",
    "data_analysis",
    "video_analysis",
    "shortlisted",
    "live_scouting",
    "approved",
    "negotiation",
    "signed",
    "rejected",
)
PIPELINE_TERMINAL = ("signed", "rejected")

PRIORITIES = ("high", "medium", "low")

SOURCE_TYPES = ("manual", "csv_import", "api_import", "scout_observation", "fictional_sample")

VIDEO_LICENSES = (
    "licensed_full_match",   # licensed provider (e.g. contracted platform)
    "club_internal",         # recorded/owned by club or partner club
    "broadcast_licensed",    # broadcaster footage under a licence
    "highlights",            # highlight package — never equivalent to full match
)

OBSERVATION_CATEGORIES = (
    "passing",
    "progressive_pass",
    "ball_carrying",
    "dribble",
    "shooting",
    "chance_creation",
    "first_touch",
    "defensive_duel",
    "interception",
    "pressing",
    "aerial_duel",
    "positioning",
    "off_ball_movement",
    "transition",
    "set_piece",
    "goalkeeping",
    "communication",
    "work_rate",
    "decision_making",
    "other",
)
GAME_PHASES = (
    "in_possession",
    "out_of_possession",
    "attacking_transition",
    "defensive_transition",
    "set_piece",
)
OBSERVATION_ASSESSMENTS = ("positive", "neutral", "negative")

REPORT_OBSERVATION_TYPES = ("video_full_match", "video_highlights", "live")

RECOMMENDATIONS = (
    "sign",
    "shortlist",
    "continue_monitoring",
    "further_scouting_required",
    "reject",
)


LANGUAGES = ("en", "fr", "ar")
ORG_STATUSES = ("active", "suspended", "pending_deletion")


def _org_fk(nullable: bool = False):
    return mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=nullable)


# --------------------------------------------------------------------------- tenants
class Organization(Base):
    """A customer (club, federation, academy). The tenant boundary."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str | None] = mapped_column(String(40))
    country: Mapped[str | None] = mapped_column(String(100))
    primary_language: Mapped[str] = mapped_column(String(5), default="en")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    timezone: Mapped[str] = mapped_column(String(60), default="Africa/Casablanca")
    logo_data_url: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Membership(Base):
    """A user's role inside one organization. Users may belong to several organizations."""

    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(40))
    region: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship()

    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),)


# --------------------------------------------------------------------------- users
class User(Base):
    """Global identity. Roles live on memberships, never on the user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Platform operators (the SaaS company). Manage organizations/subscriptions only;
    # they have NO access to tenant scouting data.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Incremented on password change / deactivation to revoke issued tokens.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuditLog(TenantPrivate, Base):
    """organization_id is NULL only for platform-level events, never visible to tenants."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = _org_fk(nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    user_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(60), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# --------------------------------------------------------------------------- provenance
class DataSource(SharedOrPrivate, Base):
    """Where a record came from, and under what terms it may be used."""

    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = _org_fk(nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(40))
    url: Mapped[str | None] = mapped_column(String(500))
    license_notes: Mapped[str | None] = mapped_column(Text)
    is_fictional: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("uq_data_source_shared_name", "name", unique=True,
              postgresql_where=text("organization_id IS NULL"), sqlite_where=text("organization_id IS NULL")),
        Index("uq_data_source_org_name", "organization_id", "name", unique=True,
              postgresql_where=text("organization_id IS NOT NULL"), sqlite_where=text("organization_id IS NOT NULL")),
    )


# --------------------------------------------------------------------------- football
class League(SharedOrPrivate, Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = _org_fk(nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(100))
    tier: Mapped[int | None] = mapped_column(Integer)
    # Optional league-strength coefficient (1.0 = reference level). Must be documented
    # with a source; when NULL no league adjustment is applied.
    strength_coefficient: Mapped[float | None] = mapped_column(Float)
    coefficient_source: Mapped[str | None] = mapped_column(String(300))
    is_fictional: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("uq_league_shared", "name", "country", unique=True,
              postgresql_where=text("organization_id IS NULL"), sqlite_where=text("organization_id IS NULL")),
        Index("uq_league_org", "organization_id", "name", "country", unique=True,
              postgresql_where=text("organization_id IS NOT NULL"), sqlite_where=text("organization_id IS NOT NULL")),
    )


class Club(SharedOrPrivate, Base):
    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = _org_fk(nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(100))
    league_id: Mapped[int | None] = mapped_column(ForeignKey("leagues.id", ondelete="SET NULL"))
    is_fictional: Mapped[bool] = mapped_column(Boolean, default=False)

    league: Mapped[League | None] = relationship()

    __table_args__ = (
        Index("uq_club_shared", "name", "country", unique=True,
              postgresql_where=text("organization_id IS NULL"), sqlite_where=text("organization_id IS NULL")),
        Index("uq_club_org", "organization_id", "name", "country", unique=True,
              postgresql_where=text("organization_id IS NOT NULL"), sqlite_where=text("organization_id IS NOT NULL")),
    )


class Player(SharedOrPrivate, Base):
    """Player *identity*. Shared (platform reference) or private to one organization.
    Club-specific valuation and opinion live in :class:`PlayerAssessment`."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = _org_fk(nullable=True)
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    known_as: Mapped[str | None] = mapped_column(String(120))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[str] = mapped_column(String(100), index=True)
    second_nationality: Mapped[str | None] = mapped_column(String(100))
    current_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id", ondelete="SET NULL"))
    primary_position: Mapped[str] = mapped_column(String(4), index=True)
    secondary_positions: Mapped[list | None] = mapped_column(JSON, default=list)
    height_cm: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[int | None] = mapped_column(Integer)
    preferred_foot: Mapped[str | None] = mapped_column(String(10))
    contract_expiry: Mapped[date | None] = mapped_column(Date)

    data_source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))
    source_reference: Mapped[str | None] = mapped_column(String(300))
    is_fictional: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    club: Mapped[Club | None] = relationship()
    data_source: Mapped[DataSource | None] = relationship()
    stats: Mapped[list["PlayerSeasonStats"]] = relationship(
        back_populates="player", cascade="all, delete-orphan", order_by="PlayerSeasonStats.season.desc()"
    )


ASSESSMENT_FIELDS = ("tactical_role", "physical_profile", "estimated_fee", "fee_estimate_source",
                     "salary_expectation", "availability", "agent_name", "notes")
FINANCIAL_FIELDS = ("estimated_fee", "fee_estimate_source", "salary_expectation", "agent_name")


class PlayerAssessment(TenantPrivate, Base):
    """One organization's private view of a player: valuation, availability, opinion.
    Amounts are in the organization's currency."""

    __tablename__ = "player_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    tactical_role: Mapped[str | None] = mapped_column(String(80))
    physical_profile: Mapped[str | None] = mapped_column(Text)
    estimated_fee: Mapped[int | None] = mapped_column(Integer)
    fee_estimate_source: Mapped[str | None] = mapped_column(String(300))
    salary_expectation: Mapped[int | None] = mapped_column(Integer)  # gross per year
    availability: Mapped[str] = mapped_column(String(30), default="unknown")
    agent_name: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("organization_id", "player_id", name="uq_assessment_org_player"),)


STAT_FIELDS = (
    # volume
    "appearances", "starts", "minutes", "team_matches",
    # attacking
    "goals", "non_penalty_goals", "assists", "shots", "shots_on_target", "xg", "npxg", "xa",
    "key_passes",
    # passing / progression
    "passes_attempted", "passes_completed", "progressive_passes", "passes_final_third",
    "long_passes_attempted", "long_passes_completed", "crosses_attempted", "crosses_completed",
    "progressive_carries", "dribbles_attempted", "dribbles_completed", "touches_in_box",
    # defending
    "tackles", "tackles_won", "interceptions", "recoveries", "defensive_duels",
    "defensive_duels_won", "aerial_duels", "aerial_duels_won", "clearances", "blocks",
    "pressures", "fouls_committed", "yellow_cards", "red_cards",
    # goalkeeping
    "saves", "shots_on_target_faced", "goals_conceded", "clean_sheets", "psxg_faced",
)
FLOAT_STAT_FIELDS = {"xg", "npxg", "xa", "psxg_faced"}


class PlayerSeasonStats(SharedOrPrivate, Base):
    """Season-level statistics for one player in one competition, from one source.
    Shared only when the platform is licensed to redistribute them; stats imported by an
    organization are always private to it."""

    __tablename__ = "player_season_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = _org_fk(nullable=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    season: Mapped[str] = mapped_column(String(20))
    league_id: Mapped[int | None] = mapped_column(ForeignKey("leagues.id", ondelete="SET NULL"))
    club_name: Mapped[str | None] = mapped_column(String(200))

    appearances: Mapped[int | None] = mapped_column(Integer)
    starts: Mapped[int | None] = mapped_column(Integer)
    minutes: Mapped[int | None] = mapped_column(Integer)
    team_matches: Mapped[int | None] = mapped_column(Integer)
    goals: Mapped[int | None] = mapped_column(Integer)
    non_penalty_goals: Mapped[int | None] = mapped_column(Integer)
    assists: Mapped[int | None] = mapped_column(Integer)
    shots: Mapped[int | None] = mapped_column(Integer)
    shots_on_target: Mapped[int | None] = mapped_column(Integer)
    xg: Mapped[float | None] = mapped_column(Float)
    npxg: Mapped[float | None] = mapped_column(Float)
    xa: Mapped[float | None] = mapped_column(Float)
    key_passes: Mapped[int | None] = mapped_column(Integer)
    passes_attempted: Mapped[int | None] = mapped_column(Integer)
    passes_completed: Mapped[int | None] = mapped_column(Integer)
    progressive_passes: Mapped[int | None] = mapped_column(Integer)
    passes_final_third: Mapped[int | None] = mapped_column(Integer)
    long_passes_attempted: Mapped[int | None] = mapped_column(Integer)
    long_passes_completed: Mapped[int | None] = mapped_column(Integer)
    crosses_attempted: Mapped[int | None] = mapped_column(Integer)
    crosses_completed: Mapped[int | None] = mapped_column(Integer)
    progressive_carries: Mapped[int | None] = mapped_column(Integer)
    dribbles_attempted: Mapped[int | None] = mapped_column(Integer)
    dribbles_completed: Mapped[int | None] = mapped_column(Integer)
    touches_in_box: Mapped[int | None] = mapped_column(Integer)
    tackles: Mapped[int | None] = mapped_column(Integer)
    tackles_won: Mapped[int | None] = mapped_column(Integer)
    interceptions: Mapped[int | None] = mapped_column(Integer)
    recoveries: Mapped[int | None] = mapped_column(Integer)
    defensive_duels: Mapped[int | None] = mapped_column(Integer)
    defensive_duels_won: Mapped[int | None] = mapped_column(Integer)
    aerial_duels: Mapped[int | None] = mapped_column(Integer)
    aerial_duels_won: Mapped[int | None] = mapped_column(Integer)
    clearances: Mapped[int | None] = mapped_column(Integer)
    blocks: Mapped[int | None] = mapped_column(Integer)
    pressures: Mapped[int | None] = mapped_column(Integer)
    fouls_committed: Mapped[int | None] = mapped_column(Integer)
    yellow_cards: Mapped[int | None] = mapped_column(Integer)
    red_cards: Mapped[int | None] = mapped_column(Integer)
    saves: Mapped[int | None] = mapped_column(Integer)
    shots_on_target_faced: Mapped[int | None] = mapped_column(Integer)
    goals_conceded: Mapped[int | None] = mapped_column(Integer)
    clean_sheets: Mapped[int | None] = mapped_column(Integer)
    psxg_faced: Mapped[float | None] = mapped_column(Float)

    data_source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))
    is_fictional: Mapped[bool] = mapped_column(Boolean, default=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    player: Mapped[Player] = relationship(back_populates="stats")
    league: Mapped[League | None] = relationship()
    data_source: Mapped[DataSource | None] = relationship()

    __table_args__ = (
        UniqueConstraint("player_id", "season", "league_id", "data_source_id", name="uq_stats_player_season_src"),
    )


# --------------------------------------------------------------------------- video
class MatchVideo(TenantPrivate, Base):
    """A *link* to footage. The platform never hosts or redistributes footage."""

    __tablename__ = "match_videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    match_date: Mapped[date | None] = mapped_column(Date)
    competition: Mapped[str | None] = mapped_column(String(200))
    home_team: Mapped[str] = mapped_column(String(200))
    away_team: Mapped[str] = mapped_column(String(200))
    video_url: Mapped[str] = mapped_column(String(1000))
    license_type: Mapped[str] = mapped_column(String(40))
    rights_holder: Mapped[str] = mapped_column(String(200))
    license_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_full_match: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    observations: Mapped[list["VideoObservation"]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="VideoObservation.timestamp_seconds"
    )
    player: Mapped[Player] = relationship()

    __table_args__ = (UniqueConstraint("id", "organization_id", name="uq_match_video_id_org"),)


class VideoObservation(TenantPrivate, Base):
    __tablename__ = "video_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    video_id: Mapped[int] = mapped_column(Integer, index=True)
    timestamp_seconds: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(40))
    phase: Mapped[str | None] = mapped_column(String(40))
    assessment: Mapped[str] = mapped_column(String(10), default="neutral")
    technical_comment: Mapped[str | None] = mapped_column(Text)
    tactical_comment: Mapped[str | None] = mapped_column(Text)
    scout_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    video: Mapped[MatchVideo] = relationship(back_populates="observations",
                                             foreign_keys=[video_id], primaryjoin="VideoObservation.video_id == MatchVideo.id")
    scout: Mapped[User | None] = relationship()

    __table_args__ = (
        # Same-organization guarantee at database level.
        ForeignKeyConstraint(["video_id", "organization_id"], ["match_videos.id", "match_videos.organization_id"],
                             ondelete="CASCADE", name="fk_observation_video_same_org"),
    )


class MatchReport(TenantPrivate, Base):
    """An individual scout's report on one match (video or live)."""

    __tablename__ = "match_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("match_videos.id", ondelete="SET NULL"))
    scout_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    observation_type: Mapped[str] = mapped_column(String(30))
    match_date: Mapped[date | None] = mapped_column(Date)
    opponent: Mapped[str | None] = mapped_column(String(200))
    competition: Mapped[str | None] = mapped_column(String(200))
    position_played: Mapped[str | None] = mapped_column(String(4))
    minutes_observed: Mapped[int | None] = mapped_column(Integer)
    # 1–10 scout ratings (opinions). NULL = not assessed in this match.
    technical_rating: Mapped[int | None] = mapped_column(Integer)
    tactical_rating: Mapped[int | None] = mapped_column(Integer)
    physical_rating: Mapped[int | None] = mapped_column(Integer)
    mental_rating: Mapped[int | None] = mapped_column(Integer)
    overall_rating: Mapped[int | None] = mapped_column(Integer)
    technical_notes: Mapped[str | None] = mapped_column(Text)
    tactical_notes: Mapped[str | None] = mapped_column(Text)
    physical_notes: Mapped[str | None] = mapped_column(Text)
    mental_notes: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[str | None] = mapped_column(Text)
    weaknesses: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scout: Mapped[User | None] = relationship()
    video: Mapped[MatchVideo | None] = relationship()


# --------------------------------------------------------------------------- reports
class ScoutingReport(TenantPrivate, Base):
    """Consolidated recruitment report. ``sections`` holds evidence-tagged content."""

    __tablename__ = "scouting_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | final
    sections: Mapped[dict] = mapped_column(JSON)
    recommendation: Mapped[str | None] = mapped_column(String(40))
    potential_rating: Mapped[int | None] = mapped_column(Integer)  # 1-10, scout opinion
    risk_level: Mapped[str | None] = mapped_column(String(10))  # low | medium | high
    auto_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    author: Mapped[User | None] = relationship()
    player: Mapped[Player] = relationship()


# --------------------------------------------------------------------------- pipeline
class PipelineEntry(TenantPrivate, Base):
    __tablename__ = "pipeline_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(30), default="identified", index=True)
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    target_position: Mapped[str | None] = mapped_column(String(4))
    assigned_scout_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    player: Mapped[Player] = relationship()
    assigned_scout: Mapped[User | None] = relationship(foreign_keys=[assigned_scout_id])
    events: Mapped[list["PipelineEvent"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="PipelineEvent.created_at",
        primaryjoin="PipelineEntry.id == PipelineEvent.entry_id", foreign_keys="PipelineEvent.entry_id",
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "player_id", name="uq_pipeline_org_player"),
        UniqueConstraint("id", "organization_id", name="uq_pipeline_entry_id_org"),
    )


class PipelineEvent(TenantPrivate, Base):
    """Immutable history of every decision in the recruitment pipeline."""

    __tablename__ = "pipeline_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    entry_id: Mapped[int] = mapped_column(Integer, index=True)
    from_stage: Mapped[str | None] = mapped_column(String(30))
    to_stage: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    entry: Mapped[PipelineEntry] = relationship(
        back_populates="events", primaryjoin="PipelineEntry.id == PipelineEvent.entry_id",
        foreign_keys=[entry_id])
    user: Mapped[User | None] = relationship()

    __table_args__ = (
        ForeignKeyConstraint(["entry_id", "organization_id"], ["pipeline_entries.id", "pipeline_entries.organization_id"],
                             ondelete="CASCADE", name="fk_event_entry_same_org"),
    )


class RecruitmentBudget(TenantPrivate, Base):
    """Amounts in the organization's currency."""

    __tablename__ = "recruitment_budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    season: Mapped[str] = mapped_column(String(20))
    transfer_budget: Mapped[int] = mapped_column(Integer)
    wage_budget: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("organization_id", "season", name="uq_budget_org_season"),)


Index("ix_players_club", Player.current_club_id)
