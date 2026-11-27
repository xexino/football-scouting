"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import (
    AVAILABILITY,
    FEET,
    GAME_PHASES,
    OBSERVATION_ASSESSMENTS,
    OBSERVATION_CATEGORIES,
    PIPELINE_STAGES,
    POSITIONS,
    PRIORITIES,
    RECOMMENDATIONS,
    REPORT_OBSERVATION_TYPES,
    ROLES,
    SOURCE_TYPES,
    VIDEO_LICENSES,
)

Position = Literal[POSITIONS]  # type: ignore[valid-type]
Role = Literal[ROLES]  # type: ignore[valid-type]
Availability = Literal[AVAILABILITY]  # type: ignore[valid-type]
Foot = Literal[FEET]  # type: ignore[valid-type]
Stage = Literal[PIPELINE_STAGES]  # type: ignore[valid-type]
Priority = Literal[PRIORITIES]  # type: ignore[valid-type]
Recommendation = Literal[RECOMMENDATIONS]  # type: ignore[valid-type]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- auth / users
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(ORM):
    id: int
    email: str
    full_name: str
    role: str
    region: str | None
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None
    permissions: list[str] = []


class UserCreate(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    full_name: str = Field(min_length=2, max_length=200)
    role: Role
    region: str | None = None
    password: str


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: Role | None = None
    region: str | None = None
    is_active: bool | None = None
    password: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


# --------------------------------------------------------------------------- reference data
class DataSourceIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    source_type: Literal[SOURCE_TYPES]  # type: ignore[valid-type]
    url: str | None = None
    license_notes: str | None = None
    is_fictional: bool = False


class DataSourceOut(ORM):
    id: int
    name: str
    source_type: str
    url: str | None
    license_notes: str | None
    is_fictional: bool


class LeagueIn(BaseModel):
    name: str
    country: str
    tier: int | None = None
    strength_coefficient: float | None = Field(default=None, gt=0, le=2)
    coefficient_source: str | None = None
    is_fictional: bool = False

    @field_validator("coefficient_source")
    @classmethod
    def _source_required(cls, v, info):
        if info.data.get("strength_coefficient") is not None and not v:
            raise ValueError("coefficient_source is required when a strength coefficient is provided")
        return v


class LeagueOut(ORM):
    id: int
    name: str
    country: str
    tier: int | None
    strength_coefficient: float | None
    coefficient_source: str | None
    is_fictional: bool


class ClubIn(BaseModel):
    name: str
    country: str
    league_id: int | None = None
    is_fictional: bool = False


class ClubOut(ORM):
    id: int
    name: str
    country: str
    league_id: int | None
    is_fictional: bool


# --------------------------------------------------------------------------- players
class PlayerBase(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    known_as: str | None = None
    date_of_birth: date | None = None
    nationality: str
    second_nationality: str | None = None
    current_club_id: int | None = None
    primary_position: Position
    secondary_positions: list[Position] = []
    tactical_role: str | None = None
    height_cm: int | None = Field(default=None, ge=140, le=220)
    weight_kg: int | None = Field(default=None, ge=40, le=130)
    preferred_foot: Foot | None = None
    physical_profile: str | None = None
    contract_expiry: date | None = None
    estimated_fee_eur: int | None = Field(default=None, ge=0)
    fee_estimate_source: str | None = None
    salary_expectation_eur: int | None = Field(default=None, ge=0)
    availability: Availability = "unknown"
    agent_name: str | None = None
    notes: str | None = None
    data_source_id: int | None = None
    source_reference: str | None = None


class PlayerCreate(PlayerBase):
    pass


class PlayerUpdate(BaseModel):
    full_name: str | None = None
    known_as: str | None = None
    date_of_birth: date | None = None
    nationality: str | None = None
    second_nationality: str | None = None
    current_club_id: int | None = None
    primary_position: Position | None = None
    secondary_positions: list[Position] | None = None
    tactical_role: str | None = None
    height_cm: int | None = Field(default=None, ge=140, le=220)
    weight_kg: int | None = Field(default=None, ge=40, le=130)
    preferred_foot: Foot | None = None
    physical_profile: str | None = None
    contract_expiry: date | None = None
    estimated_fee_eur: int | None = Field(default=None, ge=0)
    fee_estimate_source: str | None = None
    salary_expectation_eur: int | None = Field(default=None, ge=0)
    availability: Availability | None = None
    agent_name: str | None = None
    notes: str | None = None
    data_source_id: int | None = None
    source_reference: str | None = None


class StatsIn(BaseModel):
    season: str = Field(pattern=r"^\d{4}(-\d{2,4})?$")
    league_id: int | None = None
    club_name: str | None = None
    data_source_id: int
    appearances: int | None = Field(default=None, ge=0)
    starts: int | None = Field(default=None, ge=0)
    minutes: int | None = Field(default=None, ge=0)
    team_matches: int | None = Field(default=None, ge=0)
    goals: int | None = Field(default=None, ge=0)
    non_penalty_goals: int | None = Field(default=None, ge=0)
    assists: int | None = Field(default=None, ge=0)
    shots: int | None = Field(default=None, ge=0)
    shots_on_target: int | None = Field(default=None, ge=0)
    xg: float | None = Field(default=None, ge=0)
    npxg: float | None = Field(default=None, ge=0)
    xa: float | None = Field(default=None, ge=0)
    key_passes: int | None = Field(default=None, ge=0)
    passes_attempted: int | None = Field(default=None, ge=0)
    passes_completed: int | None = Field(default=None, ge=0)
    progressive_passes: int | None = Field(default=None, ge=0)
    passes_final_third: int | None = Field(default=None, ge=0)
    long_passes_attempted: int | None = Field(default=None, ge=0)
    long_passes_completed: int | None = Field(default=None, ge=0)
    crosses_attempted: int | None = Field(default=None, ge=0)
    crosses_completed: int | None = Field(default=None, ge=0)
    progressive_carries: int | None = Field(default=None, ge=0)
    dribbles_attempted: int | None = Field(default=None, ge=0)
    dribbles_completed: int | None = Field(default=None, ge=0)
    touches_in_box: int | None = Field(default=None, ge=0)
    tackles: int | None = Field(default=None, ge=0)
    tackles_won: int | None = Field(default=None, ge=0)
    interceptions: int | None = Field(default=None, ge=0)
    recoveries: int | None = Field(default=None, ge=0)
    defensive_duels: int | None = Field(default=None, ge=0)
    defensive_duels_won: int | None = Field(default=None, ge=0)
    aerial_duels: int | None = Field(default=None, ge=0)
    aerial_duels_won: int | None = Field(default=None, ge=0)
    clearances: int | None = Field(default=None, ge=0)
    blocks: int | None = Field(default=None, ge=0)
    pressures: int | None = Field(default=None, ge=0)
    fouls_committed: int | None = Field(default=None, ge=0)
    yellow_cards: int | None = Field(default=None, ge=0)
    red_cards: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    shots_on_target_faced: int | None = Field(default=None, ge=0)
    goals_conceded: int | None = Field(default=None, ge=0)
    clean_sheets: int | None = Field(default=None, ge=0)
    psxg_faced: float | None = Field(default=None, ge=0)

    @field_validator("passes_completed", "dribbles_completed", "defensive_duels_won", "aerial_duels_won",
                     "long_passes_completed", "crosses_completed", "tackles_won", "shots_on_target",
                     "non_penalty_goals", "starts")
    @classmethod
    def _not_more_than_attempts(cls, v, info):
        pairs = {
            "passes_completed": "passes_attempted",
            "dribbles_completed": "dribbles_attempted",
            "defensive_duels_won": "defensive_duels",
            "aerial_duels_won": "aerial_duels",
            "long_passes_completed": "long_passes_attempted",
            "crosses_completed": "crosses_attempted",
            "tackles_won": "tackles",
            "shots_on_target": "shots",
            "non_penalty_goals": "goals",
            "starts": "appearances",
        }
        other = info.data.get(pairs[info.field_name])
        if v is not None and other is not None and v > other:
            raise ValueError(f"{info.field_name} cannot exceed {pairs[info.field_name]}")
        return v


# --------------------------------------------------------------------------- video
class VideoIn(BaseModel):
    player_id: int
    match_date: date | None = None
    competition: str | None = None
    home_team: str
    away_team: str
    video_url: str = Field(min_length=8, max_length=1000)
    license_type: Literal[VIDEO_LICENSES]  # type: ignore[valid-type]
    rights_holder: str = Field(min_length=2)
    license_confirmed: bool
    is_full_match: bool = False
    duration_minutes: int | None = Field(default=None, ge=1, le=200)
    notes: str | None = None

    @field_validator("video_url")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("video_url must be an http(s) link to the licensed platform")
        return v

    @field_validator("license_confirmed")
    @classmethod
    def _confirmed(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must confirm Raja holds a licence or authorisation to view this footage")
        return v

    @field_validator("is_full_match")
    @classmethod
    def _highlights_not_full(cls, v: bool, info) -> bool:
        if v and info.data.get("license_type") == "highlights":
            raise ValueError("Highlight packages cannot be registered as full-match footage")
        return v


class ObservationIn(BaseModel):
    timestamp_seconds: int = Field(ge=0, le=4 * 3600)
    category: Literal[OBSERVATION_CATEGORIES]  # type: ignore[valid-type]
    phase: Literal[GAME_PHASES] | None = None  # type: ignore[valid-type]
    assessment: Literal[OBSERVATION_ASSESSMENTS] = "neutral"  # type: ignore[valid-type]
    technical_comment: str | None = None
    tactical_comment: str | None = None


class ObservationOut(ORM):
    id: int
    video_id: int
    timestamp_seconds: int
    category: str
    phase: str | None
    assessment: str
    technical_comment: str | None
    tactical_comment: str | None
    scout_id: int | None
    created_at: datetime


class VideoOut(ORM):
    id: int
    player_id: int
    match_date: date | None
    competition: str | None
    home_team: str
    away_team: str
    video_url: str
    license_type: str
    rights_holder: str
    license_confirmed: bool
    is_full_match: bool
    duration_minutes: int | None
    notes: str | None
    created_by_id: int | None
    created_at: datetime
    observations: list[ObservationOut] = []


Rating = int | None


class MatchReportIn(BaseModel):
    player_id: int
    video_id: int | None = None
    observation_type: Literal[REPORT_OBSERVATION_TYPES]  # type: ignore[valid-type]
    match_date: date | None = None
    opponent: str | None = None
    competition: str | None = None
    position_played: Position | None = None
    minutes_observed: int | None = Field(default=None, ge=0, le=130)
    technical_rating: int | None = Field(default=None, ge=1, le=10)
    tactical_rating: int | None = Field(default=None, ge=1, le=10)
    physical_rating: int | None = Field(default=None, ge=1, le=10)
    mental_rating: int | None = Field(default=None, ge=1, le=10)
    overall_rating: int | None = Field(default=None, ge=1, le=10)
    technical_notes: str | None = None
    tactical_notes: str | None = None
    physical_notes: str | None = None
    mental_notes: str | None = None
    strengths: str | None = None
    weaknesses: str | None = None
    summary: str | None = None
    recommendation: Recommendation | None = None


class MatchReportOut(ORM):
    id: int
    player_id: int
    video_id: int | None
    scout_id: int | None
    scout_name: str | None = None
    observation_type: str
    is_complete_match_analysis: bool = False
    match_date: date | None
    opponent: str | None
    competition: str | None
    position_played: str | None
    minutes_observed: int | None
    technical_rating: int | None
    tactical_rating: int | None
    physical_rating: int | None
    mental_rating: int | None
    overall_rating: int | None
    technical_notes: str | None
    tactical_notes: str | None
    physical_notes: str | None
    mental_notes: str | None
    strengths: str | None
    weaknesses: str | None
    summary: str | None
    recommendation: str | None
    created_at: datetime


# --------------------------------------------------------------------------- scouting reports
class ReportGenerateIn(BaseModel):
    player_id: int
    season: str | None = None
    tactical_role: str | None = None


class ReportUpdate(BaseModel):
    title: str | None = None
    sections: dict | None = None
    recommendation: Recommendation | None = None
    potential_rating: int | None = Field(default=None, ge=1, le=10)
    risk_level: Literal["low", "medium", "high"] | None = None


class ReportOut(ORM):
    id: int
    player_id: int
    author_id: int | None
    author_name: str | None = None
    title: str
    status: str
    sections: dict
    recommendation: str | None
    potential_rating: int | None
    risk_level: str | None
    auto_generated: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- pipeline
class PipelineCreate(BaseModel):
    player_id: int
    priority: Priority = "medium"
    target_position: Position | None = None
    assigned_scout_id: int | None = None
    note: str | None = None


class PipelineMove(BaseModel):
    to_stage: Stage
    note: str = Field(min_length=3, description="Decision rationale — mandatory for the audit trail")


class PipelineUpdate(BaseModel):
    priority: Priority | None = None
    target_position: Position | None = None
    assigned_scout_id: int | None = None


class PipelineEventOut(ORM):
    id: int
    from_stage: str | None
    to_stage: str
    note: str | None
    user_id: int | None
    user_name: str | None = None
    created_at: datetime


class BudgetIn(BaseModel):
    season: str
    transfer_budget_eur: int = Field(ge=0)
    wage_budget_eur: int | None = Field(default=None, ge=0)
    notes: str | None = None


Token.model_rebuild()
