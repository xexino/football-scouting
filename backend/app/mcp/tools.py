"""Raja Scout MCP tools.

Every tool is a thin adapter over the existing REST endpoint functions and application
services (``app.routers.*``, ``app.analytics``): no business logic is duplicated here, so
role-based redaction, tenant isolation and validation behave exactly as in the web app.

Privacy defaults: the organization's private assessment (tactical opinion, availability,
notes, valuation, salary, agent) is *left out* unless the caller explicitly asks for it with
``include_private_assessment=true`` — and even then financial fields stay subject to the
``financials:read`` permission. Included private fields are grouped under
``organisation_private`` so agents (and humans reviewing tool output) can see that they must
not be forwarded to external tools or data providers.
"""
from __future__ import annotations

from collections import Counter

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..analytics import METRICS, aggregate, compute_all_metrics, select_rows
from ..models import ASSESSMENT_FIELDS, FINANCIAL_FIELDS, Player
from ..routers import compare as compare_router
from ..routers import dashboard as dashboard_router
from ..routers import pipeline as pipeline_router
from ..routers import players as players_router
from ..routers import reports as reports_router
from ..routers import video as video_router
from ..schemas import ObservationIn, PipelineMove, ReportGenerateIn
from ..security import has_permission
from .gateway import ToolSpec, call_endpoint

PRIVATE_NOTICE = ("Organisation-private data of your club. Do not send it to external tools, data providers "
                  "or third parties.")
EVIDENCE_NOTICE = ("Statistical indicators from recorded data only. They describe past output, not future "
                   "success, and are not a substitute for live/video scouting.")
MAX_PAGE_SIZE = 50


# --------------------------------------------------------------------------- shaping
def shape_player(item: dict, include_private: bool) -> dict:
    out = {k: v for k, v in item.items() if k not in ASSESSMENT_FIELDS}
    out.pop("financials_redacted", None)
    if include_private:
        private = {k: item.get(k) for k in ASSESSMENT_FIELDS}
        if item.get("financials_redacted"):
            for f in FINANCIAL_FIELDS:
                private.pop(f, None)
            private["financials"] = "hidden for your role"
        out["organisation_private"] = {"notice": PRIVATE_NOTICE, **private}
    return out


def _search(ctx, db, **kw) -> dict:
    return call_endpoint(players_router.search_players, ctx, db, **kw)


def _search_all(ctx, db, **kw) -> list[dict]:
    items, page = [], 1
    while True:
        res = _search(ctx, db, page=page, page_size=200, **kw)
        items += res["items"]
        if page * 200 >= res["total"]:
            return items
        page += 1


# --------------------------------------------------------------------------- read tools
def search_players(ctx, db, *, query=None, positions=None, primary_only=False, age_min=None, age_max=None,
                   nationality=None, league_country=None, min_minutes=None, stat_filters=None,
                   sort="full_name", order="asc", page=1, page_size=25, include_private_assessment=False):
    res = _search(ctx, db, q=query, position=",".join(positions) if positions else None, primary_only=primary_only,
                  age_min=age_min, age_max=age_max, nationality=nationality, league_country=league_country,
                  min_minutes=min_minutes, stat_filters=stat_filters, sort=sort, order=order, page=page,
                  page_size=min(page_size, MAX_PAGE_SIZE))
    return {"total": res["total"], "page": res["page"], "page_size": res["page_size"],
            "items": [shape_player(i, include_private_assessment) for i in res["items"]]}


def get_player_profile(ctx, db, *, player_id, include_private_assessment=False):
    p = call_endpoint(players_router.get_player, ctx, db, player_id=player_id)
    seasons = [{"season": s["season"], "league": s["league_name"], "club": s["club_name"],
                "minutes": s.get("minutes"), "data_source": s["data_source"], "is_fictional": s["is_fictional"]}
               for s in p.pop("stats", [])]
    out = shape_player(p, include_private_assessment)
    out["seasons"] = seasons
    return out


def get_player_statistics(ctx, db, *, player_id, season=None):
    lines = call_endpoint(players_router.list_stats, ctx, db, player_id=player_id)
    analytics = call_endpoint(players_router.player_analytics, ctx, db, player_id=player_id, season=season)
    return {"player_id": player_id, "season_lines": lines, "analytics": analytics, "notice": EVIDENCE_NOTICE}


def find_young_talents(ctx, db, *, max_age=21, positions=None, metric="prog_passes_p90", min_minutes=450,
                       nationality=None, league_country=None, limit=15):
    res = _search(ctx, db, age_max=max_age, position=",".join(positions) if positions else None,
                  min_minutes=min_minutes, nationality=nationality, league_country=league_country,
                  sort=f"metric:{metric}", order="desc" if METRICS[metric].higher_is_better else "asc",
                  page=1, page_size=min(limit, MAX_PAGE_SIZE))
    return {
        "criteria": {"max_age": max_age, "positions": positions, "ranked_by": metric,
                     "metric_label": METRICS[metric].label, "min_minutes_latest_season": min_minutes},
        "total_matching": res["total"],
        "candidates": [shape_player(i, False) for i in res["items"]],
        "notice": EVIDENCE_NOTICE + " A ranking is a starting list for scouting, never a verdict on potential.",
    }


def compare_players(ctx, db, *, player_ids, season=None, tactical_role=None, allow_mixed_positions=False):
    body = compare_router.CompareIn(player_ids=player_ids, season=season, tactical_role=tactical_role,
                                    allow_mixed_positions=allow_mixed_positions)
    return call_endpoint(compare_router.compare, ctx, db, body=body)


def get_club_requirements(ctx, db):
    """Derived from the club's own recruitment data (there is no separate requirements record)."""
    board = call_endpoint(pipeline_router.board, ctx, db)
    active = [e for stage, col in board["columns"].items() if stage not in ("signed", "rejected") for e in col]
    by_pos: dict[str, Counter] = {}
    for e in active:
        pos = e["target_position"] or e["position"]
        by_pos.setdefault(pos, Counter())[e["priority"]] += 1
    out = {
        "organization": {"name": ctx.organization.name, "country": ctx.organization.country,
                         "currency": ctx.organization.currency},
        "positional_targets": [
            {"position": pos, "active_candidates": sum(c.values()), "high_priority": c.get("high", 0),
             "medium_priority": c.get("medium", 0), "low_priority": c.get("low", 0)}
            for pos, c in sorted(by_pos.items(), key=lambda kv: (-kv[1].get("high", 0), -sum(kv[1].values())))
        ],
        "derived_from": "active recruitment-pipeline entries (target position and priority)",
    }
    if has_permission(ctx, "financials:read"):
        out["budgets"] = call_endpoint(dashboard_router.list_budgets, ctx, db)
    else:
        out["budgets"] = "hidden for your role"
    return out


def get_recruitment_pipeline(ctx, db, *, stage=None, priority=None, position=None, assigned_to_me=False,
                             player_id=None):
    if player_id is not None:
        return {"entry": call_endpoint(pipeline_router.by_player, ctx, db, player_id=player_id)}
    board = call_endpoint(pipeline_router.board, ctx, db, priority=priority, position=position,
                          assigned_to_me=assigned_to_me)
    if stage:
        board["columns"] = {stage: board["columns"].get(stage, [])}
        board["total"] = len(board["columns"][stage])
    return board


def get_scouting_reports(ctx, db, *, player_id=None, report_id=None):
    if report_id is not None:
        return {"report": call_endpoint(reports_router.get_report, ctx, db, report_id=report_id)}
    return {"reports": call_endpoint(reports_router.list_reports, ctx, db, player_id=player_id)}


def generate_shortlist(ctx, db, *, position, metrics, max_age=None, min_minutes=900, exclude_in_pipeline=True,
                       limit=10):
    """Read-only: ranks candidates, saves nothing. Rank = mean percentile rank across the chosen
    metrics within the candidate pool (direction-aware)."""
    pool = _search_all(ctx, db, position=position, age_max=max_age, min_minutes=min_minutes,
                       pipeline_stage="none" if exclude_in_pipeline else None)
    ids = [i["id"] for i in pool]
    players = {p.id: p for p in db.scalars(select(Player).where(Player.id.in_(ids)).options(
        selectinload(Player.stats))).all()} if ids else {}
    values: dict[int, dict] = {}
    for item in pool:
        rows = select_rows(players[item["id"]], None)
        values[item["id"]] = compute_all_metrics(aggregate(rows)) if rows else {}
    ranks: dict[int, dict] = {pid: {} for pid in values}
    for m in metrics:
        have = [(pid, v[m]) for pid, v in values.items() if v.get(m) is not None]
        have.sort(key=lambda t: t[1], reverse=not METRICS[m].higher_is_better)
        n = len(have)
        for i, (pid, _) in enumerate(have):
            ranks[pid][m] = round(100 * (n - i) / n, 1) if n else None
    scored = []
    for item in pool:
        r = ranks[item["id"]]
        if len(r) < len(metrics):
            continue  # missing data for a requested metric: not ranked, not guessed
        scored.append({
            "player": shape_player(item, False),
            "metrics": {m: values[item["id"]][m] for m in metrics},
            "percentile_in_pool": r,
            "score": round(sum(r.values()) / len(r), 1),
        })
    scored.sort(key=lambda s: s["score"], reverse=True)
    return {
        "criteria": {"position": position, "metrics": metrics, "max_age": max_age,
                     "min_minutes_latest_season": min_minutes, "exclude_in_pipeline": exclude_in_pipeline},
        "pool_size": len(pool), "ranked": len(scored), "shortlist": scored[:limit],
        "method": "Mean of per-metric percentile ranks inside this candidate pool (latest season).",
        "saved": False,
        "notice": EVIDENCE_NOTICE + " Nothing was saved; add players to the pipeline in the app.",
    }


# --------------------------------------------------------------------------- write tools (disabled by default)
def _player_name(db, player_id):
    p = db.get(Player, player_id)
    if p is None:
        raise HTTPException(404, "Player not found")
    return p.full_name


def create_scouting_report(ctx, db, *, player_id, season=None, tactical_role=None):
    body = ReportGenerateIn(player_id=player_id, season=season, tactical_role=tactical_role)
    r = call_endpoint(reports_router.generate, ctx, db, body=body)
    return {"created": True, "report_id": r["id"], "title": r["title"], "status": r.get("status")}


def preview_create_scouting_report(ctx, db, *, player_id, season=None, tactical_role=None):
    return {"action": f"Create a draft, evidence-tagged scouting report for {_player_name(db, player_id)}"
                      f"{' (season ' + season + ')' if season else ''}."}


def add_video_observation(ctx, db, *, video_id, timestamp_seconds, category, assessment="neutral", phase=None,
                          technical_comment=None, tactical_comment=None):
    body = ObservationIn(timestamp_seconds=timestamp_seconds, category=category, phase=phase, assessment=assessment,
                         technical_comment=technical_comment, tactical_comment=tactical_comment)
    obs = call_endpoint(video_router.add_observation, ctx, db, video_id=video_id, body=body)
    return {"created": True, "observation_id": obs.id}


def preview_add_video_observation(ctx, db, *, video_id, timestamp_seconds, category, assessment="neutral", **_):
    v = call_endpoint(video_router.get_video, ctx, db, video_id=video_id)
    return {"action": f"Add a '{category}' observation ({assessment}) at {timestamp_seconds // 60}:"
                      f"{timestamp_seconds % 60:02d} to video '{v.get('title')}'."}


def update_recruitment_status(ctx, db, *, entry_id, to_stage, note):
    body = PipelineMove(to_stage=to_stage, note=note)
    e = call_endpoint(pipeline_router.move, ctx, db, entry_id=entry_id, body=body)
    return {"updated": True, "entry_id": e["id"], "player_name": e["player_name"], "stage": e["stage"]}


def preview_update_recruitment_status(ctx, db, *, entry_id, to_stage, note):
    e = call_endpoint(pipeline_router.get_entry, ctx, db, entry_id=entry_id)
    blockers = pipeline_router.check_transition(db, ctx, pipeline_router._entry(db, entry_id), to_stage)
    return {"action": f"Move {e['player_name']} from '{e['stage']}' to '{to_stage}'. Rationale: {note}",
            "warnings": blockers}


# --------------------------------------------------------------------------- registry
READ_TOOLS = {s.name: s for s in [
    ToolSpec("search_players", search_players, ("players:read",), routers=(players_router.search_players,),
             description="Search the player database (shared reference + your club's private records)."),
    ToolSpec("get_player_profile", get_player_profile, ("players:read",), routers=(players_router.get_player,),
             description="Profile of one player: identity, club, positions, contract, data provenance."),
    ToolSpec("get_player_statistics", get_player_statistics, ("players:read",),
             routers=(players_router.list_stats, players_router.player_analytics),
             description="Season stat lines plus per-90, percentile, consistency and role-fit analysis."),
    ToolSpec("find_young_talents", find_young_talents, ("players:read",), routers=(players_router.search_players,),
             description="Young players ranked by one metric, with a minimum-minutes threshold."),
    ToolSpec("compare_players", compare_players, ("players:read",), routers=(compare_router.compare,),
             description="Side-by-side comparison of 2-5 players in the same position group."),
    ToolSpec("get_club_requirements", get_club_requirements, ("pipeline:read",),
             routers=(pipeline_router.board,),
             description="Your club's open positional targets (from the pipeline) and budgets (if permitted)."),
    ToolSpec("get_recruitment_pipeline", get_recruitment_pipeline, ("pipeline:read",),
             routers=(pipeline_router.board, pipeline_router.by_player),
             description="Recruitment pipeline board, or the history of one player's entry."),
    ToolSpec("get_scouting_reports", get_scouting_reports, ("players:read",),
             routers=(reports_router.list_reports, reports_router.get_report),
             description="List scouting reports (optionally for one player) or read one report."),
    ToolSpec("generate_shortlist", generate_shortlist, ("players:read",), routers=(players_router.search_players,),
             description="Read-only ranked shortlist for a position from chosen metrics. Saves nothing."),
]}

WRITE_TOOLS = {s.name: s for s in [
    ToolSpec("create_scouting_report", create_scouting_report, ("reports:write",), write=True,
             preview=preview_create_scouting_report, routers=(reports_router.generate,),
             description="Create a draft evidence-tagged scouting report. Requires human approval."),
    ToolSpec("add_video_observation", add_video_observation, ("video:write",), write=True,
             preview=preview_add_video_observation, routers=(video_router.add_observation,),
             description="Add a timestamped observation to licensed footage. Requires human approval."),
    ToolSpec("update_recruitment_status", update_recruitment_status, ("pipeline:move",), write=True,
             preview=preview_update_recruitment_status, routers=(pipeline_router.move,),
             description="Move a pipeline entry to another stage (rationale required). Requires human approval."),
]}
