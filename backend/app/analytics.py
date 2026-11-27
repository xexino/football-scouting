"""Position-specific player analytics.

Methodology (also documented in docs/ANALYTICS.md):

* Counting statistics are normalised per 90 minutes: ``value / minutes * 90``.
* Ratios (completion %, duel success %) use attempted actions as denominator and are
  only reported when the denominator is large enough to be meaningful.
* League adjustment multiplies per-90 *volume* metrics by the competition's
  ``strength_coefficient``. It is only applied when a coefficient with a documented
  source exists, and raw values are always shown alongside adjusted ones.
* Percentiles compare a player only against players **in this database** with the same
  primary position and at least ``MIN_MINUTES_POOL`` minutes. They describe relative
  output within that sample — they are *not* a measure of player quality, and output
  is heavily influenced by team style, role and game state.
* Missing values stay missing. Nothing is imputed.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import settings
from .models import STAT_FIELDS, Player, PlayerSeasonStats

# --------------------------------------------------------------------------- metric catalogue


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    kind: str  # "per90" | "ratio" | "derived"
    num: str | None = None
    den: str | None = None
    higher_is_better: bool = True
    min_den: int = 0  # minimum attempts for a ratio to be shown
    league_adjust: bool = False
    unit: str = ""
    group: str = "general"


METRICS: dict[str, Metric] = {
    m.key: m
    for m in [
        # Attacking
        Metric("np_goals_p90", "Non-penalty goals /90", "per90", "non_penalty_goals", league_adjust=True, group="attacking"),
        Metric("npxg_p90", "Non-penalty xG /90", "per90", "npxg", league_adjust=True, group="attacking"),
        Metric("shots_p90", "Shots /90", "per90", "shots", league_adjust=True, group="attacking"),
        Metric("npxg_per_shot", "npxG per shot", "ratio", "npxg", "shots", min_den=15, group="attacking"),
        Metric("assists_p90", "Assists /90", "per90", "assists", league_adjust=True, group="creation"),
        Metric("xa_p90", "Expected assists /90", "per90", "xa", league_adjust=True, group="creation"),
        Metric("key_passes_p90", "Key passes /90", "per90", "key_passes", league_adjust=True, group="creation"),
        Metric("touches_box_p90", "Touches in box /90", "per90", "touches_in_box", league_adjust=True, group="attacking"),
        # Passing & progression
        Metric("passes_p90", "Completed passes /90", "per90", "passes_completed", league_adjust=True, group="passing"),
        Metric("pass_pct", "Pass completion %", "ratio", "passes_completed", "passes_attempted", min_den=100, unit="%", group="passing"),
        Metric("prog_passes_p90", "Progressive passes /90", "per90", "progressive_passes", league_adjust=True, group="passing"),
        Metric("final_third_passes_p90", "Passes into final third /90", "per90", "passes_final_third", league_adjust=True, group="passing"),
        Metric("long_pass_pct", "Long pass completion %", "ratio", "long_passes_completed", "long_passes_attempted", min_den=30, unit="%", group="passing"),
        Metric("crosses_p90", "Completed crosses /90", "per90", "crosses_completed", league_adjust=True, group="passing"),
        Metric("cross_pct", "Cross completion %", "ratio", "crosses_completed", "crosses_attempted", min_den=20, unit="%", group="passing"),
        Metric("prog_carries_p90", "Progressive carries /90", "per90", "progressive_carries", league_adjust=True, group="progression"),
        Metric("dribbles_p90", "Successful dribbles /90", "per90", "dribbles_completed", league_adjust=True, group="progression"),
        Metric("dribble_pct", "Dribble success %", "ratio", "dribbles_completed", "dribbles_attempted", min_den=20, unit="%", group="progression"),
        # Defending
        Metric("tackles_won_p90", "Tackles won /90", "per90", "tackles_won", league_adjust=True, group="defending"),
        Metric("interceptions_p90", "Interceptions /90", "per90", "interceptions", league_adjust=True, group="defending"),
        Metric("recoveries_p90", "Ball recoveries /90", "per90", "recoveries", league_adjust=True, group="defending"),
        Metric("def_duels_p90", "Defensive duels /90", "per90", "defensive_duels", league_adjust=True, group="defending"),
        Metric("def_duel_pct", "Defensive duel success %", "ratio", "defensive_duels_won", "defensive_duels", min_den=40, unit="%", group="defending"),
        Metric("pressures_p90", "Pressures /90", "per90", "pressures", league_adjust=True, group="defending"),
        Metric("clearances_p90", "Clearances /90", "per90", "clearances", group="defending"),
        Metric("blocks_p90", "Blocks /90", "per90", "blocks", group="defending"),
        Metric("aerials_won_p90", "Aerial duels won /90", "per90", "aerial_duels_won", league_adjust=True, group="aerial"),
        Metric("aerial_pct", "Aerial duel success %", "ratio", "aerial_duels_won", "aerial_duels", min_den=25, unit="%", group="aerial"),
        Metric("fouls_p90", "Fouls committed /90", "per90", "fouls_committed", higher_is_better=False, group="discipline"),
        # Goalkeeping
        Metric("save_pct", "Save %", "ratio", "saves", "shots_on_target_faced", min_den=30, unit="%", group="goalkeeping"),
        Metric("goals_prevented_p90", "Goals prevented /90 (PSxG − GA)", "derived", group="goalkeeping"),
        Metric("goals_conceded_p90", "Goals conceded /90", "per90", "goals_conceded", higher_is_better=False, group="goalkeeping"),
        Metric("clean_sheet_pct", "Clean sheet %", "ratio", "clean_sheets", "appearances", min_den=10, unit="%", group="goalkeeping"),
    ]
}

POSITION_PROFILES: dict[str, list[str]] = {
    "GK": ["save_pct", "goals_prevented_p90", "goals_conceded_p90", "clean_sheet_pct", "pass_pct", "long_pass_pct", "aerials_won_p90"],
    "CB": ["def_duel_pct", "def_duels_p90", "interceptions_p90", "aerials_won_p90", "aerial_pct", "clearances_p90", "pass_pct", "prog_passes_p90", "long_pass_pct"],
    "FB": ["def_duel_pct", "tackles_won_p90", "interceptions_p90", "prog_passes_p90", "prog_carries_p90", "crosses_p90", "cross_pct", "xa_p90", "recoveries_p90"],
    "DM": ["interceptions_p90", "recoveries_p90", "tackles_won_p90", "def_duel_pct", "pass_pct", "prog_passes_p90", "long_pass_pct", "aerial_pct", "pressures_p90"],
    "CM": ["pass_pct", "prog_passes_p90", "final_third_passes_p90", "prog_carries_p90", "key_passes_p90", "xa_p90", "recoveries_p90", "def_duel_pct", "npxg_p90"],
    "AM": ["xa_p90", "key_passes_p90", "npxg_p90", "np_goals_p90", "dribbles_p90", "prog_carries_p90", "final_third_passes_p90", "touches_box_p90", "pressures_p90"],
    "W": ["npxg_p90", "np_goals_p90", "xa_p90", "dribbles_p90", "dribble_pct", "prog_carries_p90", "crosses_p90", "touches_box_p90", "key_passes_p90"],
    "ST": ["np_goals_p90", "npxg_p90", "shots_p90", "npxg_per_shot", "touches_box_p90", "xa_p90", "aerials_won_p90", "aerial_pct", "pressures_p90"],
}

# Tactical role templates used for model-based role fit. Weights express which data
# indicators are relevant to the role in a club's game model — they are a hypothesis set
# by the technical staff, not a quality verdict.
TACTICAL_ROLES: dict[str, dict] = {
    "ball_playing_cb": {"label": "Ball-playing centre-back", "position": "CB",
                        "weights": {"prog_passes_p90": 3, "pass_pct": 2, "long_pass_pct": 2, "def_duel_pct": 2, "aerial_pct": 2, "interceptions_p90": 1}},
    "stopper_cb": {"label": "Aggressive stopper", "position": "CB",
                   "weights": {"def_duels_p90": 3, "def_duel_pct": 3, "aerial_pct": 3, "aerials_won_p90": 2, "clearances_p90": 1}},
    "attacking_fb": {"label": "Attacking full-back", "position": "FB",
                     "weights": {"crosses_p90": 2, "xa_p90": 3, "prog_carries_p90": 2, "prog_passes_p90": 2, "def_duel_pct": 1}},
    "defensive_fb": {"label": "Defensive full-back", "position": "FB",
                     "weights": {"def_duel_pct": 3, "tackles_won_p90": 2, "interceptions_p90": 2, "aerial_pct": 1, "pass_pct": 1}},
    "anchor_dm": {"label": "Anchor / screening midfielder", "position": "DM",
                  "weights": {"interceptions_p90": 3, "recoveries_p90": 2, "def_duel_pct": 2, "pass_pct": 2, "aerial_pct": 1}},
    "deep_playmaker": {"label": "Deep-lying playmaker", "position": "DM",
                       "weights": {"prog_passes_p90": 3, "pass_pct": 2, "long_pass_pct": 2, "recoveries_p90": 1, "final_third_passes_p90": 2}},
    "box_to_box": {"label": "Box-to-box midfielder", "position": "CM",
                   "weights": {"prog_carries_p90": 2, "recoveries_p90": 2, "def_duel_pct": 1, "npxg_p90": 2, "prog_passes_p90": 2, "pressures_p90": 1}},
    "creative_10": {"label": "Creative number 10", "position": "AM",
                    "weights": {"xa_p90": 3, "key_passes_p90": 3, "final_third_passes_p90": 2, "dribbles_p90": 1, "npxg_p90": 1}},
    "inverted_winger": {"label": "Inverted winger", "position": "W",
                        "weights": {"npxg_p90": 3, "dribbles_p90": 2, "touches_box_p90": 2, "xa_p90": 2, "prog_carries_p90": 1}},
    "touchline_winger": {"label": "Touchline winger", "position": "W",
                         "weights": {"crosses_p90": 3, "dribbles_p90": 2, "dribble_pct": 1, "xa_p90": 2, "prog_carries_p90": 2}},
    "target_striker": {"label": "Target striker", "position": "ST",
                       "weights": {"aerials_won_p90": 3, "aerial_pct": 2, "np_goals_p90": 2, "npxg_p90": 2, "touches_box_p90": 1}},
    "pressing_striker": {"label": "Pressing striker", "position": "ST",
                         "weights": {"pressures_p90": 3, "npxg_p90": 2, "np_goals_p90": 2, "xa_p90": 1, "shots_p90": 1}},
    "sweeper_keeper": {"label": "Sweeper keeper", "position": "GK",
                       "weights": {"goals_prevented_p90": 3, "save_pct": 2, "pass_pct": 2, "long_pass_pct": 2}},
}

GENERAL_CAVEATS = [
    "Percentiles compare against players in this database only; the reference pool is not a representative sample of world football.",
    "Statistical output reflects team style, tactical role, opposition and game state — it describes what a player did, not how good the player is.",
    "Correlation between a metric and team success does not establish causation or player quality; combine data with full-match video and live scouting.",
]


# --------------------------------------------------------------------------- helpers
def age_on(dob: date | None, today: date | None = None) -> int | None:
    if dob is None:
        return None
    today = today or date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _sum_field(rows: list[PlayerSeasonStats], field: str) -> float | None:
    values = [getattr(r, field) for r in rows]
    if not values or any(v is None for v in values):
        return None  # incomplete coverage — do not pretend we know the total
    return float(sum(values))


def _adjusted_sum(rows: list[PlayerSeasonStats], field: str) -> float | None:
    total = 0.0
    for r in rows:
        v = getattr(r, field)
        coef = r.league.strength_coefficient if r.league is not None else None
        if v is None or coef is None:
            return None
        total += v * coef
    return total


def aggregate(rows: list[PlayerSeasonStats]) -> dict:
    """Sum season rows into a single totals dict (None where coverage is incomplete)."""
    totals = {f: _sum_field(rows, f) for f in STAT_FIELDS}
    totals["_adjusted"] = {f: _adjusted_sum(rows, f) for f in STAT_FIELDS}
    return totals


def compute_metric(metric: Metric, totals: dict, adjusted: bool = False) -> float | None:
    minutes = totals.get("minutes")
    if metric.kind == "per90":
        src = totals["_adjusted"] if adjusted and metric.league_adjust else totals
        if adjusted and not metric.league_adjust:
            src = totals
        value = src.get(metric.num)
        if value is None or not minutes:
            return None
        return round(value / minutes * 90, 3)
    if metric.kind == "ratio":
        num, den = totals.get(metric.num), totals.get(metric.den)
        if num is None or den is None or den < metric.min_den or den == 0:
            return None
        return round(num / den * 100, 1)
    if metric.key == "goals_prevented_p90":
        psxg, ga = totals.get("psxg_faced"), totals.get("goals_conceded")
        if psxg is None or ga is None or not minutes:
            return None
        return round((psxg - ga) / minutes * 90, 3)
    return None


def compute_all_metrics(totals: dict, adjusted: bool = False) -> dict[str, float | None]:
    return {k: compute_metric(m, totals, adjusted) for k, m in METRICS.items()}


def select_rows(player: Player, season: str | None) -> list[PlayerSeasonStats]:
    if not player.stats:
        return []
    if season == "all":
        return list(player.stats)
    if season is None:
        season = max(r.season for r in player.stats)
    return [r for r in player.stats if r.season == season]


# --------------------------------------------------------------------------- pools & percentiles
def build_pool(db: Session, position: str, season: str | None) -> dict[int, dict[str, float | None]]:
    """Metrics for every player at a position with enough minutes (season=None → each player's latest)."""
    players = db.scalars(
        select(Player).where(Player.primary_position == position).options(
            selectinload(Player.stats).selectinload(PlayerSeasonStats.league)
        )
    ).all()
    pool: dict[int, dict[str, float | None]] = {}
    for p in players:
        rows = select_rows(p, season)
        if not rows:
            continue
        totals = aggregate(rows)
        if (totals.get("minutes") or 0) < settings.min_minutes_pool:
            continue
        pool[p.id] = compute_all_metrics(totals)
    return pool


def percentile(value: float | None, population: list[float], higher_is_better: bool = True) -> float | None:
    if value is None or len(population) < 5:
        return None
    below = sum(1 for v in population if v < value)
    equal = sum(1 for v in population if v == value)
    pct = (below + 0.5 * equal) / len(population) * 100
    return round(pct if higher_is_better else 100 - pct, 1)


def percentiles_for(metrics: dict[str, float | None], pool: dict[int, dict]) -> dict[str, dict]:
    out = {}
    for key, metric in METRICS.items():
        population = [m[key] for m in pool.values() if m.get(key) is not None]
        out[key] = {
            "percentile": percentile(metrics.get(key), population, metric.higher_is_better),
            "pool_size": len(population),
        }
    return out


def role_fit(percentiles: dict[str, dict], role_key: str) -> dict | None:
    role = TACTICAL_ROLES.get(role_key)
    if role is None:
        return None
    weights = role["weights"]
    num = den = 0.0
    covered = []
    for key, w in weights.items():
        p = percentiles.get(key, {}).get("percentile")
        if p is None:
            continue
        num += p * w
        den += w
        covered.append(key)
    coverage = round(den / sum(weights.values()) * 100) if weights else 0
    return {
        "role": role_key,
        "label": role["label"],
        "score": round(num / den, 1) if den else None,
        "data_coverage_pct": coverage,
        "metrics_used": covered,
        "evidence_type": "model_estimate",
        "note": "Weighted average of database percentiles for the indicators the club's game model associates with this role. A screening aid, not a quality rating.",
    }


# --------------------------------------------------------------------------- consistency
def consistency(player: Player) -> dict:
    seasons = sorted({r.season for r in player.stats})
    per_season = []
    profile = POSITION_PROFILES.get(player.primary_position, [])
    for s in seasons:
        rows = [r for r in player.stats if r.season == s]
        totals = aggregate(rows)
        minutes = totals.get("minutes")
        tm = totals.get("team_matches")
        apps = totals.get("appearances")
        starts = totals.get("starts")
        per_season.append({
            "season": s,
            "minutes": minutes,
            "appearances": apps,
            "starts": starts,
            "minutes_share_pct": round(minutes / (tm * 90) * 100, 1) if minutes is not None and tm else None,
            "start_rate_pct": round(starts / apps * 100, 1) if starts is not None and apps else None,
            "metrics": {k: compute_metric(METRICS[k], totals) for k in profile},
        })
    variability = {}
    reliable = [s for s in per_season if (s["minutes"] or 0) >= settings.min_minutes_reliable]
    if len(reliable) >= 2:
        for k in profile:
            vals = [s["metrics"][k] for s in reliable if s["metrics"].get(k) is not None]
            if len(vals) >= 2 and statistics.mean(vals) != 0:
                variability[k] = round(statistics.pstdev(vals) / abs(statistics.mean(vals)) * 100, 1)
    return {
        "seasons": per_season,
        "season_to_season_variation_pct": variability,
        "note": "Variation is the coefficient of variation of per-90 output across seasons with ≥"
        f"{settings.min_minutes_reliable} minutes. Lower = more stable output. Role or club changes affect this.",
    }


# --------------------------------------------------------------------------- full analysis
def analyse_player(db: Session, player: Player, season: str | None = None) -> dict:
    rows = select_rows(player, season)
    position = player.primary_position
    caveats = list(GENERAL_CAVEATS)
    if player.is_fictional:
        caveats.insert(0, "FICTIONAL SAMPLE DATA — for demonstration only. Not real player statistics.")
    if not rows:
        return {
            "player_id": player.id,
            "season": season,
            "has_data": False,
            "caveats": ["No statistics recorded for this player. Import data from a licensed source or enter verified figures."],
        }
    totals = aggregate(rows)
    minutes = totals.get("minutes") or 0
    if minutes < settings.min_minutes_reliable:
        caveats.append(
            f"Small sample: {int(minutes)} minutes (< {settings.min_minutes_reliable}). Per-90 figures are unstable at this volume."
        )
    raw = compute_all_metrics(totals)
    adjusted = compute_all_metrics(totals, adjusted=True)
    league_adjustment_available = any(
        adjusted[k] is not None for k, m in METRICS.items() if m.league_adjust
    )
    if not league_adjustment_available:
        caveats.append("No league-strength coefficient available for this competition: values are not league-adjusted.")
    else:
        caveats.append("League-adjusted values use documented league coefficients; they are approximations and should not replace context.")

    effective_season = rows[0].season if season != "all" else "all"
    pool = build_pool(db, position, None if season == "all" else effective_season)
    pcts = percentiles_for(raw, pool)
    if len(pool) < 5:
        caveats.append(f"Reference pool too small ({len(pool)} {position}s): percentiles are not shown.")
    elif len(pool) < 20:
        caveats.append(f"Small reference pool ({len(pool)} {position}s with ≥{settings.min_minutes_pool} min): percentiles are coarse.")
    profile = POSITION_PROFILES.get(position, [])

    sources = sorted({r.data_source.name for r in rows if r.data_source})
    last_updated = max(r.last_updated for r in rows)
    roles = [k for k, r in TACTICAL_ROLES.items() if r["position"] == position]

    return {
        "player_id": player.id,
        "has_data": True,
        "season": effective_season,
        "position": position,
        "minutes": totals.get("minutes"),
        "sample_reliable": minutes >= settings.min_minutes_reliable,
        "totals": {k: v for k, v in totals.items() if not k.startswith("_")},
        "profile_metrics": [
            {
                "key": k,
                "label": METRICS[k].label,
                "group": METRICS[k].group,
                "unit": METRICS[k].unit,
                "higher_is_better": METRICS[k].higher_is_better,
                "value": raw.get(k),
                "league_adjusted": adjusted.get(k) if METRICS[k].league_adjust else None,
                **pcts.get(k, {}),
            }
            for k in profile
        ],
        "all_metrics": raw,
        "role_fit": [role_fit(pcts, r) for r in roles],
        "consistency": consistency(player),
        "provenance": {
            "evidence_type": "verified_data" if not player.is_fictional else "fictional_sample",
            "sources": sources,
            "last_updated": last_updated.isoformat() if last_updated else None,
            "is_fictional": any(r.is_fictional for r in rows),
        },
        "pool": {"position": position, "size": len(pool), "min_minutes": settings.min_minutes_pool},
        "caveats": caveats,
    }


def ordinal(n: float) -> str:
    n = int(round(n))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def strengths_weaknesses(profile_metrics: list[dict]) -> tuple[list[str], list[str]]:
    strengths = [f"{m['label']} ({ordinal(m['percentile'])} pct)" for m in profile_metrics
                 if m.get("percentile") is not None and m["percentile"] >= 70]
    weaknesses = [f"{m['label']} ({ordinal(m['percentile'])} pct)" for m in profile_metrics
                  if m.get("percentile") is not None and m["percentile"] <= 30]
    return strengths, weaknesses
