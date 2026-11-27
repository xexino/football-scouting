"""Automated scouting-report drafting.

The generator is deterministic and rule-based: it assembles a draft from the evidence
held in the platform and labels **every** item with its evidence type so readers can
always distinguish facts from opinions:

* ``verified_data``      – figures from an identified data source (with source name)
* ``fictional_sample``   – demonstration data, never to be used for decisions
* ``scout_opinion``      – a named scout's judgement from a match report / video note
* ``model_estimate``     – platform calculations (percentiles, role fit, risk flags)
* ``insufficient_evidence`` – the platform has no basis to comment
* ``scout_input_required``  – must be completed by a human before finalising

The draft never invents qualitative judgements. Narrative assessment must come from scouts.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .analytics import METRICS, TACTICAL_ROLES, age_on, analyse_player, ordinal, role_fit, strengths_weaknesses
from .assessments import get_assessment
from .models import MatchReport, MatchVideo, Player, POSITION_LABELS

TECHNICAL_METRICS = ["pass_pct", "prog_passes_p90", "key_passes_p90", "dribble_pct", "dribbles_p90",
                     "long_pass_pct", "cross_pct", "npxg_per_shot", "save_pct"]
PHYSICAL_METRICS = ["aerial_pct", "aerials_won_p90", "def_duel_pct", "pressures_p90"]


def _item(evidence_type: str, text: str, source: str | None = None, **extra) -> dict:
    return {"evidence_type": evidence_type, "text": text, "source": source, **extra}


def _fmt(v, unit=""):
    if v is None:
        return "n/a"
    return f"{v:.2f}{unit}" if isinstance(v, float) and unit != "%" else f"{v}{unit}"


def _scout_items(reports: list[MatchReport], field: str) -> list[dict]:
    items = []
    for r in reports:
        text = getattr(r, field)
        if text:
            scope = " [HIGHLIGHTS ONLY]" if r.observation_type == "video_highlights" else ""
            items.append(_item(
                "scout_opinion", text,
                source=f"{r.scout.full_name if r.scout else 'Unknown scout'} — {r.observation_type.replace('_', ' ')}"
                       f"{scope}, {r.match_date or 'date n/a'} vs {r.opponent or 'n/a'}",
                match_report_id=r.id,
            ))
    return items


def _avg_rating(reports: list[MatchReport], field: str) -> dict | None:
    vals = [getattr(r, field) for r in reports if getattr(r, field) is not None]
    if not vals:
        return None
    return _item("scout_opinion", f"Average scout rating: {sum(vals) / len(vals):.1f}/10 across {len(vals)} report(s).",
                 source="Aggregated match reports")


def generate_report(db: Session, player: Player, season: str | None = None, tactical_role: str | None = None,
                    org=None) -> dict:
    a = analyse_player(db, player, season)
    assessment = get_assessment(db, player.id)  # this organization's private view only
    availability = assessment.availability if assessment else "unknown"
    physical_profile = assessment.physical_profile if assessment else None
    data_type = "fictional_sample" if player.is_fictional else "verified_data"
    src = ", ".join(a.get("provenance", {}).get("sources", [])) if a.get("has_data") else None
    profile_src = player.data_source.name if player.data_source else "Player record"

    reports = db.scalars(select(MatchReport).where(MatchReport.player_id == player.id)
                         .options(selectinload(MatchReport.scout)).order_by(MatchReport.match_date)).all()
    videos = db.scalars(select(MatchVideo).where(MatchVideo.player_id == player.id)
                        .options(selectinload(MatchVideo.observations))).all()
    pm = {m["key"]: m for m in a.get("profile_metrics", [])}
    allm = a.get("all_metrics") or {}

    sections: dict[str, dict] = {}

    # ---- profile
    club = player.club
    age = age_on(player.date_of_birth)
    sections["profile"] = {"title": "Player profile", "items": [
        _item(data_type, f"{player.full_name}, {age if age is not None else 'age n/a'} years, {player.nationality}"
              f"{' / ' + player.second_nationality if player.second_nationality else ''}.", profile_src),
        _item(data_type, f"Club: {club.name if club else 'n/a'}"
              f"{' (' + club.league.name + ')' if club and club.league else ''}. Contract expiry: {player.contract_expiry or 'n/a'}."
              f" Availability (club assessment): {availability.replace('_', ' ')}.", profile_src),
        _item(data_type, f"Position: {POSITION_LABELS.get(player.primary_position)}"
              f"{'; also ' + ', '.join(player.secondary_positions) if player.secondary_positions else ''}."
              f" Preferred foot: {player.preferred_foot or 'n/a'}. Height: {player.height_cm or 'n/a'} cm.", profile_src),
    ]}

    # ---- statistics
    stat_items = []
    if a.get("has_data"):
        stat_items.append(_item(data_type, f"Season {a['season']}: {a['minutes']:.0f} minutes"
                                f" ({'reliable sample' if a['sample_reliable'] else 'SMALL SAMPLE — interpret with caution'}).", src))
        for m in a["profile_metrics"]:
            pct = f" — {ordinal(m['percentile'])} percentile of {m['pool_size']} {player.primary_position}s in database" \
                if m.get("percentile") is not None else ""
            adj = f" (league-adjusted {_fmt(m['league_adjusted'])})" if m.get("league_adjusted") is not None else ""
            stat_items.append(_item(data_type, f"{m['label']}: {_fmt(m['value'], m['unit'])}{adj}{pct}", src))
        strengths, weaknesses = strengths_weaknesses(a["profile_metrics"])
        if strengths:
            stat_items.append(_item("model_estimate", "Data-derived relative strengths: " + "; ".join(strengths) + "."))
        if weaknesses:
            stat_items.append(_item("model_estimate", "Data-derived relative weaknesses: " + "; ".join(weaknesses) + "."))
        for c in a["caveats"]:
            stat_items.append(_item("model_estimate", c, kind="caveat"))
    else:
        stat_items.append(_item("insufficient_evidence", "No statistical data recorded for this player."))
    sections["statistical_analysis"] = {"title": "Statistical analysis", "items": stat_items}

    # ---- technical
    tech = _scout_items(reports, "technical_notes")
    r = _avg_rating(reports, "technical_rating")
    tech += [r] if r else []
    for k in TECHNICAL_METRICS:
        if k == "save_pct" and player.primary_position != "GK":
            continue
        if allm.get(k) is not None:
            tech.append(_item(data_type, f"{METRICS[k].label}: {_fmt(allm[k], METRICS[k].unit)}", src))
    if not any(i["evidence_type"] == "scout_opinion" for i in tech):
        tech.insert(0, _item("insufficient_evidence", "No scout technical assessment yet — full-match video or live scouting required."))
    sections["technical"] = {"title": "Technical assessment", "items": tech}

    # ---- tactical
    tac = _scout_items(reports, "tactical_notes")
    r = _avg_rating(reports, "tactical_rating")
    tac += [r] if r else []
    for v in videos:
        for o in v.observations:
            if o.tactical_comment:
                tac.append(_item("scout_opinion", o.tactical_comment,
                                 source=f"Video observation @ {o.timestamp_seconds // 60}:{o.timestamp_seconds % 60:02d}, "
                                        f"{v.home_team} v {v.away_team}{'' if v.is_full_match else ' [NOT FULL MATCH]'}"))
    if a.get("has_data"):
        pcts = {k: {"percentile": m.get("percentile")} for k, m in pm.items()}
        roles = [tactical_role] if tactical_role in TACTICAL_ROLES else \
            [k for k, rr in TACTICAL_ROLES.items() if rr["position"] == player.primary_position]
        for rk in roles:
            fit = role_fit(pcts, rk)
            if fit and fit["score"] is not None:
                tac.append(_item("model_estimate", f"Role-fit indicator — {fit['label']}: {fit['score']:.0f}/100 "
                                 f"(data coverage {fit['data_coverage_pct']}%). Screening aid only."))
    if not any(i["evidence_type"] == "scout_opinion" for i in tac):
        tac.insert(0, _item("insufficient_evidence", "No scout tactical assessment yet."))
    sections["tactical"] = {"title": "Tactical understanding", "items": tac}

    # ---- physical
    phys = []
    if player.height_cm or player.weight_kg:
        phys.append(_item(data_type, f"Height {player.height_cm or 'n/a'} cm, weight {player.weight_kg or 'n/a'} kg.", profile_src))
    if physical_profile:
        phys.append(_item("scout_opinion", physical_profile, source="Club assessment — physical profile notes"))
    phys += _scout_items(reports, "physical_notes")
    r = _avg_rating(reports, "physical_rating")
    phys += [r] if r else []
    for k in PHYSICAL_METRICS:
        if allm.get(k) is not None:
            phys.append(_item(data_type, f"{METRICS[k].label}: {_fmt(allm[k], METRICS[k].unit)}", src))
    phys.append(_item("insufficient_evidence", "No physical testing / tracking data (speed, distance, sprints) recorded. "
                      "Medical and athletic testing required before any signing."))
    sections["physical"] = {"title": "Physical assessment", "items": phys}

    # ---- mental (scout evidence only)
    mental = _scout_items(reports, "mental_notes")
    r = _avg_rating(reports, "mental_rating")
    mental += [r] if r else []
    if not mental:
        mental = [_item("insufficient_evidence", "No mental or behavioural observations recorded by scouts. "
                        "The platform does not infer personality or character from statistics.")]
    sections["mental"] = {"title": "Mental & behavioural observations", "items": mental}

    # ---- video
    vid = []
    full = [v for v in videos if v.is_full_match]
    partial = [v for v in videos if not v.is_full_match]
    obs = [o for v in videos for o in v.observations]
    if videos:
        vid.append(_item("model_estimate", f"{len(full)} full-match video(s) and {len(partial)} partial/highlight video(s) "
                         f"linked; {len(obs)} timestamped observation(s)."))
        if obs:
            cats = Counter(o.category for o in obs)
            assess = Counter(o.assessment for o in obs)
            vid.append(_item("scout_opinion", "Observation categories: " + ", ".join(f"{c.replace('_', ' ')} ×{n}" for c, n in cats.most_common())
                             + f". Assessments: {assess.get('positive', 0)} positive, {assess.get('neutral', 0)} neutral, "
                               f"{assess.get('negative', 0)} negative.", source="Video observations"))
        for v in videos:
            for o in v.observations:
                if o.technical_comment:
                    vid.append(_item("scout_opinion", o.technical_comment,
                                     source=f"{o.timestamp_seconds // 60}:{o.timestamp_seconds % 60:02d} {o.category.replace('_', ' ')} "
                                            f"({o.assessment}), {v.home_team} v {v.away_team}"
                                            f"{'' if v.is_full_match else ' [NOT FULL MATCH]'}"))
        if not full:
            vid.append(_item("model_estimate", "WARNING: no full-match footage analysed. Highlights are not equivalent "
                             "to complete match analysis and over-represent positive actions.", kind="warning"))
    else:
        vid.append(_item("insufficient_evidence", "No video analysed yet."))
    sections["video_observations"] = {"title": "Video observations", "items": vid}

    # ---- potential & risk
    risk_flags = []
    if a.get("has_data") and not a.get("sample_reliable"):
        risk_flags.append("small statistical sample")
    if not a.get("has_data"):
        risk_flags.append("no statistical data")
    full_or_live = [r for r in reports if r.observation_type != "video_highlights"]
    if len(full_or_live) < 3:
        risk_flags.append(f"only {len(full_or_live)} full-match/live report(s) (recommend ≥3 from ≥2 scouts)")
    if len({r.scout_id for r in full_or_live}) < 2:
        risk_flags.append("assessment from fewer than two independent scouts")
    if player.is_fictional:
        risk_flags.append("FICTIONAL DATA — not usable for decisions")
    if player.contract_expiry and (player.contract_expiry - date.today()).days < 365:
        risk_flags.append("contract expires within 12 months (opportunity, but competition for signature)")
    if a.get("has_data") and not any(m.get("league_adjusted") is not None for m in a["profile_metrics"]):
        home = (getattr(org, "settings", None) or {}).get("home_league") or "your league"
        risk_flags.append(f"league strength unadjusted — output may not translate to {home}")
    level = "high" if len(risk_flags) >= 3 else "medium" if risk_flags else "low"
    pr = [_item("model_estimate", f"Evidence-risk indicator: {level.upper()}. Flags: "
                + ("; ".join(risk_flags) if risk_flags else "none") + ".", kind="risk")]
    if age is not None:
        pr.append(_item(data_type, f"Age {age}: " + ("development profile — potential assessment carries higher uncertainty."
                                                       if age <= 21 else "established profile." if age <= 29 else
                                                       "veteran profile — consider resale value and contract length."), profile_src))
    pr.append(_item("scout_input_required", "Potential rating (1–10) and injury/medical risk must be entered by the Head of Scouting."))
    sections["potential_risk"] = {"title": "Potential & risk assessment", "items": pr, "evidence_risk_level": level}

    # ---- recommendation
    recs = Counter(r.recommendation for r in reports if r.recommendation)
    rec_items = []
    if recs:
        rec_items.append(_item("scout_opinion", "Scout recommendations from match reports: " +
                               ", ".join(f"{k.replace('_', ' ')} ×{n}" for k, n in recs.most_common()) + ".",
                               source="Match reports"))
    else:
        rec_items.append(_item("insufficient_evidence", "No scout recommendations recorded yet."))
    rec_items.append(_item("scout_input_required", "Final recruitment recommendation must be set by an authorised user. "
                           "The platform does not make signing decisions."))
    sections["recommendation"] = {"title": "Recruitment recommendation", "items": rec_items}

    sections["_meta"] = {
        "generated_on": date.today().isoformat(),
        "season": a.get("season"),
        "generator": "Raja Scout Intelligence rule-based drafter v1",
        "is_fictional": player.is_fictional,
        "legend": {
            "verified_data": "From an identified data source",
            "fictional_sample": "Fictional demonstration data",
            "scout_opinion": "Judgement of a named scout",
            "model_estimate": "Platform calculation / rule-based flag",
            "insufficient_evidence": "No evidence available",
            "scout_input_required": "Must be completed by staff",
        },
    }
    return {"sections": sections, "risk_level": level}


def report_to_markdown(report, player: Player, org=None) -> str:
    s = report.sections
    lines = [f"# {report.title}", ""]
    if org is not None:
        lines += [f"**{org.name}** — confidential recruitment document", ""]
    if player.is_fictional:
        lines += ["> **FICTIONAL SAMPLE DATA — demonstration only.**", ""]
    lines += [f"Status: **{report.status}** · Recommendation: **{report.recommendation or 'not set'}** · "
              f"Potential: {report.potential_rating or 'n/a'}/10 · Risk: {report.risk_level or 'n/a'}", ""]
    tags = {"verified_data": "DATA", "fictional_sample": "FICTIONAL", "scout_opinion": "SCOUT",
            "model_estimate": "MODEL", "insufficient_evidence": "NO EVIDENCE", "scout_input_required": "INPUT REQUIRED"}
    for key, sec in s.items():
        if key.startswith("_"):
            continue
        lines += [f"## {sec.get('title', key)}", ""]
        for it in sec.get("items", []):
            src = f" _(source: {it['source']})_" if it.get("source") else ""
            lines.append(f"- **[{tags.get(it['evidence_type'], it['evidence_type'])}]** {it['text']}{src}")
        lines.append("")
    lines += ["---", "Legend: DATA = verified source data · SCOUT = scout opinion · MODEL = platform calculation · "
              "FICTIONAL = demo data · NO EVIDENCE / INPUT REQUIRED = gaps to close before decision."]
    footer = ((org.settings or {}).get("report_footer") if org is not None else None)
    if footer:
        lines += ["", footer]
    lines += ["", "_Generated with Raja Scout Intelligence (independent software)._"]
    return "\n".join(lines)
