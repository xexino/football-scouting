"""Fictional demonstration data.

EVERYTHING created here is FICTIONAL: players, clubs, leagues, statistics, fees, reports.
Each record is flagged ``is_fictional=True`` and linked to the data source
"FICTIONAL SAMPLE DATA", and the UI shows a FICTIONAL badge on all of it. The statistics
are randomly generated from position templates purely to exercise the software — they
must never be used for real recruitment decisions or presented as real performance data.
"""
from __future__ import annotations

import os
import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Club,
    DataSource,
    League,
    MatchReport,
    MatchVideo,
    PipelineEntry,
    PipelineEvent,
    Player,
    PlayerSeasonStats,
    RecruitmentBudget,
    User,
    VideoObservation,
)
from .report_generator import generate_report
from .models import ScoutingReport
from .security import hash_password

FICTIONAL_SOURCE = "FICTIONAL SAMPLE DATA"
DEMO_USERS = [
    ("admin@raja-scout.local", "System Administrator", "administrator", None),
    ("director@raja-scout.local", "Demo Sporting Director", "sporting_director", None),
    ("head.scouting@raja-scout.local", "Demo Head of Scouting", "head_of_scouting", None),
    ("analyst@raja-scout.local", "Demo Data Analyst", "data_analyst", None),
    ("video@raja-scout.local", "Demo Video Scout", "video_scout", None),
    ("scout.westafrica@raja-scout.local", "Demo Regional Scout (West Africa)", "regional_scout", "West Africa"),
    ("scout.europe@raja-scout.local", "Demo Regional Scout (Europe)", "regional_scout", "Europe"),
]

# (fictional league name, country, tier, coefficient)
LEAGUES = [
    ("Fictional Premier Division", "Morocco", 1, 1.00),
    ("Fictional Ligue Pro", "Senegal", 1, 0.80),
    ("Fictional Ligue 1", "Côte d'Ivoire", 1, 0.80),
    ("Fictional Elite League", "Algeria", 1, 0.95),
    ("Fictional Ligue Pro", "Tunisia", 1, 0.95),
    ("Fictional Premier League", "Egypt", 1, 1.00),
    ("Fictional Premier League", "Ghana", 1, 0.75),
    ("Fictional Professional League", "Nigeria", 1, 0.75),
    ("Fictional Second Division", "Portugal", 2, 1.10),
    ("Fictional Ligue 2", "France", 2, 1.20),
    ("Fictional Challenger League", "Belgium", 2, 1.10),
    ("Fictional Premier League", "Mali", 1, 0.70),
]

CLUB_NAMES = [
    "Dunes Athletic", "Atlas Rovers", "Harbour City SC", "Red Cedar FC", "Oasis United", "Falcon Town",
    "Copperhill FC", "Silver Delta", "Northgate Wanderers", "Sunridge FC", "Granite Bay", "Lionfield",
    "Coral Coast FC", "Ironwood SC", "Palmview United", "Riverside Stars", "Blue Mesa", "Amber Valley",
    "Kestrel FC", "Saltmarsh Town", "Highplain Rangers", "Cobalt City", "Jade Harbour", "Stonebridge FC",
    "Emerald Plains", "Thunder Creek", "Westwind SC", "Goldcrest FC", "Mistral Athletic", "Baobab United",
    "Sandstone FC", "Horizon SC", "Marble Rock", "Crescent United", "Ivory Dawn", "Cedar Point",
]

FIRST = ["Amadou", "Youssef", "Kwame", "Idrissa", "Malik", "Samuel", "Karim", "Ousmane", "Ibrahim", "Tiago",
         "Moussa", "Hamza", "Kofi", "Bilal", "Lamine", "Adel", "Chidi", "Rayan", "Sékou", "Nabil", "Emeka",
         "Anas", "Cheikh", "Mehdi", "Jules", "Yaw", "Ilyas", "Bakary", "Omar", "Théo", "Aziz", "Sadio"]
LAST = ["Diallo-Fict", "Benali-Fict", "Mensah-Fict", "Traoré-Fict", "Haddad-Fict", "Okafor-Fict", "Cissé-Fict",
        "El Amrani-Fict", "Koné-Fict", "Boateng-Fict", "Saidi-Fict", "Ndiaye-Fict", "Mansouri-Fict", "Adeyemi-Fict",
        "Keita-Fict", "Tahiri-Fict", "Owusu-Fict", "Camara-Fict", "Ziani-Fict", "Bamba-Fict", "Fofana-Fict",
        "Chraibi-Fict", "Asante-Fict", "Sylla-Fict", "Mokrani-Fict", "Eze-Fict", "Dembélé-Fict", "Rahmani-Fict"]

NATIONALITY_BY_COUNTRY = {
    "Morocco": "Morocco", "Senegal": "Senegal", "Côte d'Ivoire": "Côte d'Ivoire", "Algeria": "Algeria",
    "Tunisia": "Tunisia", "Egypt": "Egypt", "Ghana": "Ghana", "Nigeria": "Nigeria", "Portugal": "Portugal",
    "France": "France", "Belgium": "Belgium", "Mali": "Mali",
}
POS_WEIGHTS = {"GK": 6, "CB": 14, "FB": 13, "DM": 9, "CM": 12, "AM": 8, "W": 14, "ST": 12}
SECONDARY = {"GK": [], "CB": ["DM", "FB"], "FB": ["W", "CB"], "DM": ["CM", "CB"], "CM": ["DM", "AM"],
             "AM": ["CM", "W"], "W": ["AM", "ST", "FB"], "ST": ["W", "AM"]}
ROLE_NAMES = {"GK": ["Sweeper keeper", "Shot-stopper"], "CB": ["Ball-playing centre-back", "Aggressive stopper"],
              "FB": ["Attacking full-back", "Defensive full-back"], "DM": ["Anchor", "Deep-lying playmaker"],
              "CM": ["Box-to-box", "Progressive passer"], "AM": ["Creative 10", "Second striker"],
              "W": ["Inverted winger", "Touchline winger"], "ST": ["Target striker", "Pressing striker"]}

# Per-90 templates: passes, pass%, prog, f3, long_att, long%, cross_att, cross%, prog_carry, drib_att, drib%,
# box_touches, tackles, int, recoveries, def_duels, dduel%, aerials, aerial%, clear, blocks, press, fouls,
# shots, npxg/shot, xa, key passes
T = {
    "GK": (24, 72, 0.4, 0.5, 7.5, 45, 0, 0, 0.1, 0.05, 80, 0, 0.05, 0.3, 5.5, 0.2, 60, 0.9, 85, 0.9, 0.0, 0.1, 0.1, 0, 0, 0.01, 0.02),
    "CB": (44, 84, 3.2, 3.0, 4.5, 58, 0.1, 25, 0.9, 0.4, 60, 0.5, 1.4, 1.6, 6.5, 5.5, 64, 4.8, 60, 4.5, 0.9, 6, 0.9, 0.6, 0.09, 0.03, 0.2),
    "FB": (40, 79, 4.0, 4.5, 2.0, 50, 2.8, 26, 2.5, 1.5, 55, 1.4, 1.8, 1.3, 6.0, 6.5, 58, 2.2, 50, 2.0, 0.7, 11, 1.1, 0.7, 0.07, 0.12, 0.9),
    "DM": (50, 86, 4.8, 5.0, 3.5, 66, 0.2, 20, 1.3, 0.8, 58, 0.5, 2.3, 1.9, 7.5, 7.5, 60, 2.6, 52, 2.0, 0.8, 14, 1.4, 0.8, 0.07, 0.07, 0.7),
    "CM": (46, 82, 5.2, 5.8, 2.4, 60, 0.6, 24, 2.0, 1.6, 57, 1.3, 1.8, 1.2, 6.2, 6.0, 55, 1.8, 46, 0.9, 0.6, 15, 1.2, 1.4, 0.08, 0.13, 1.3),
    "AM": (38, 79, 4.2, 5.5, 1.2, 52, 1.2, 25, 2.8, 3.2, 54, 3.2, 1.0, 0.6, 4.6, 4.5, 46, 1.2, 38, 0.3, 0.3, 16, 1.1, 2.2, 0.10, 0.22, 2.2),
    "W": (28, 76, 2.6, 3.8, 0.6, 40, 3.2, 24, 3.8, 4.8, 52, 4.2, 0.9, 0.5, 4.0, 5.0, 44, 1.1, 34, 0.2, 0.2, 14, 0.9, 2.4, 0.11, 0.18, 1.7),
    "ST": (20, 70, 1.2, 1.8, 0.4, 38, 0.6, 22, 1.4, 2.0, 46, 5.8, 0.5, 0.3, 2.8, 3.2, 40, 4.8, 44, 0.5, 0.2, 13, 1.3, 3.0, 0.14, 0.11, 1.0),
}


def _now():
    return datetime.now(timezone.utc)


def _vary(rng: random.Random, x: float, t: float, spread: float = 0.18) -> float:
    return max(0.0, x * t * rng.gauss(1, spread))


def _stat_line(rng: random.Random, pos: str, talent: float, minutes: int, apps: int, starts: int) -> dict:
    (passes, pass_pct, prog, f3, long_att, long_pct, cross_att, cross_pct, pc, drib_att, drib_pct, box, tck, intc,
     rec, dd, dd_pct, aer, aer_pct, clr, blk, prs, fls, shots, xgps, xa, kp) = T[pos]
    n90 = minutes / 90
    c = lambda per90, t=talent, s=0.18: int(round(_vary(rng, per90, t, s) * n90))  # noqa: E731
    pct = lambda base, k=8: min(97, max(10, base + (talent - 1) * k * 10 / 2 + rng.gauss(0, 3)))  # noqa: E731

    pass_att = max(1, int(round(_vary(rng, passes, 1, 0.12) * n90 / (pass_pct / 100))))
    long_att_n = c(long_att, 1, 0.25)
    cross_att_n = c(cross_att, 1, 0.25)
    drib_att_n = c(drib_att, talent, 0.25)
    dd_n = c(dd, 1, 0.2)
    aer_n = c(aer, 1, 0.25)
    shots_n = c(shots, talent, 0.25)
    npxg = round(shots_n * max(0.03, rng.gauss(xgps, 0.02)), 2)
    pens = rng.randint(0, 3) if pos in ("ST", "AM", "W") and rng.random() < 0.4 else 0
    npg = max(0, int(round(npxg * rng.gauss(1.0 + (talent - 1) * 0.6, 0.3))))
    tck_n = c(tck, 1, 0.2)
    line = {
        "appearances": apps, "starts": starts, "minutes": minutes, "team_matches": 30,
        "goals": npg + pens, "non_penalty_goals": npg, "shots": shots_n,
        "shots_on_target": int(round(shots_n * min(0.6, max(0.2, rng.gauss(0.38, 0.06))))),
        "xg": round(npxg + pens * 0.76, 2), "npxg": npxg,
        "xa": round(_vary(rng, xa, talent, 0.25) * n90, 2), "key_passes": c(kp),
        "passes_attempted": pass_att, "passes_completed": int(pass_att * pct(pass_pct, 4) / 100),
        "progressive_passes": c(prog), "passes_final_third": c(f3),
        "long_passes_attempted": long_att_n, "long_passes_completed": int(long_att_n * pct(long_pct) / 100),
        "crosses_attempted": cross_att_n, "crosses_completed": int(cross_att_n * pct(cross_pct, 5) / 100),
        "progressive_carries": c(pc), "dribbles_attempted": drib_att_n,
        "dribbles_completed": int(drib_att_n * pct(drib_pct) / 100), "touches_in_box": c(box),
        "tackles": tck_n, "tackles_won": int(tck_n * min(0.85, max(0.4, rng.gauss(0.62, 0.06)))),
        "interceptions": c(intc), "recoveries": c(rec), "defensive_duels": dd_n,
        "defensive_duels_won": int(dd_n * pct(dd_pct) / 100), "aerial_duels": aer_n,
        "aerial_duels_won": int(aer_n * pct(aer_pct) / 100), "clearances": c(clr, 1), "blocks": c(blk, 1),
        "pressures": c(prs, 1, 0.22), "fouls_committed": c(fls, 1, 0.25),
        "yellow_cards": rng.randint(0, 8), "red_cards": 1 if rng.random() < 0.08 else 0,
    }
    if pos == "GK":
        sot = int(round(rng.gauss(3.6, 0.5) * n90))
        save_pct = pct(70, 6) / 100
        saves = int(sot * save_pct)
        ga = sot - saves
        line.update({"saves": saves, "shots_on_target_faced": sot, "goals_conceded": ga,
                     "clean_sheets": max(0, int(apps * rng.uniform(0.18, 0.4))),
                     "psxg_faced": round(ga + rng.gauss((talent - 1) * 6, 2.0), 2)})
        for k in ("non_penalty_goals", "goals", "shots", "shots_on_target", "npxg", "xg"):
            line[k] = 0
    else:
        line.update({"saves": None, "shots_on_target_faced": None, "goals_conceded": None,
                     "clean_sheets": None, "psxg_faced": None})
    # Simulate patchy source coverage: some lines lack pressures (realistic gap, left NULL).
    if rng.random() < 0.15:
        line["pressures"] = None
    return line


def create_demo_users(db: Session) -> dict[str, User]:
    password = os.getenv("DEMO_PASSWORD", "RajaDemo2026!")
    users = {}
    for email, name, role, region in DEMO_USERS:
        u = db.scalar(select(User).where(User.email == email))
        if u is None:
            u = User(email=email, full_name=name, role=role, region=region, hashed_password=hash_password(password))
            db.add(u)
        users[role if role != "regional_scout" else email] = u
    db.flush()
    return users


def seed(db: Session, n_players: int = 96) -> None:
    if db.scalar(select(DataSource).where(DataSource.name == FICTIONAL_SOURCE)):
        return
    rng = random.Random(20261127)
    users = create_demo_users(db)
    director = users["sporting_director"]
    head = users["head_of_scouting"]
    analyst = users["data_analyst"]
    video = users["video_scout"]
    wa = users["scout.westafrica@raja-scout.local"]
    eu = users["scout.europe@raja-scout.local"]

    src = DataSource(name=FICTIONAL_SOURCE, source_type="fictional_sample", is_fictional=True,
                     license_notes="Randomly generated demonstration data. Not real. Do not use for decisions.")
    db.add(src)
    db.add(DataSource(name="Raja internal scouting", source_type="scout_observation",
                      license_notes="Observations recorded by Raja CA staff."))
    db.flush()

    leagues = []
    for name, country, tier, coef in LEAGUES:
        lg = League(name=name, country=country, tier=tier, strength_coefficient=coef,
                    coefficient_source="Fictional demo coefficient — replace with a documented methodology",
                    is_fictional=True)
        db.add(lg)
        leagues.append(lg)
    db.flush()
    clubs = []
    names = iter(CLUB_NAMES)
    for lg in leagues:
        for _ in range(3):
            c = Club(name=f"{next(names)} (fictional)", country=lg.country, league_id=lg.id, is_fictional=True)
            c.league = lg
            db.add(c)
            clubs.append(c)
    db.flush()

    positions = [p for p, w in POS_WEIGHTS.items() for _ in range(w)]
    used_names = set()
    players = []
    today = date.today()
    for i in range(n_players):
        while True:
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if name not in used_names:
                used_names.add(name)
                break
        club = rng.choice(clubs)
        pos = positions[i % len(positions)] if i < len(positions) else rng.choice(positions)
        age = rng.randint(18, 32)
        dob = date(today.year - age, rng.randint(1, 12), rng.randint(1, 28))
        talent = max(0.7, min(1.35, rng.gauss(1.0, 0.13)))
        coef = club.league.strength_coefficient
        height = int(rng.gauss({"GK": 190, "CB": 187, "ST": 183, "FB": 176, "W": 174, "AM": 175}.get(pos, 179), 4.5))
        fee = int(round(max(100_000, 900_000 * talent ** 4 * coef ** 2 * (1.4 if age <= 23 else 1.0 if age <= 28 else 0.5)
                            * rng.uniform(0.7, 1.3)), -4))
        expiry = date(today.year + rng.choice([0, 1, 1, 2, 2, 3, 4]), 6, 30)
        if expiry < today:
            expiry = date(today.year + 1, 6, 30)
        months_left = (expiry.year - today.year) * 12 + expiry.month - today.month
        availability = ("contract_expiring" if months_left <= 12 else
                        rng.choice(["unknown", "unknown", "available", "transfer_listed", "loan_possible", "not_available"]))
        p = Player(
            full_name=name, date_of_birth=dob, nationality=NATIONALITY_BY_COUNTRY[club.country] if rng.random() < 0.75
            else rng.choice(list(NATIONALITY_BY_COUNTRY.values())),
            current_club_id=club.id, primary_position=pos,
            secondary_positions=rng.sample(SECONDARY[pos], k=min(len(SECONDARY[pos]), rng.randint(0, 2))),
            tactical_role=rng.choice(ROLE_NAMES[pos]), height_cm=height,
            weight_kg=int(height - 100 + rng.gauss(-4, 4)),
            preferred_foot=rng.choices(["right", "left", "both"], [70, 25, 5])[0],
            physical_profile=None, contract_expiry=expiry, estimated_fee_eur=fee,
            fee_estimate_source="Fictional estimate (demo)",
            salary_expectation_eur=int(round(fee * rng.uniform(0.12, 0.25), -3)),
            availability=availability, data_source_id=src.id, is_fictional=True,
            source_reference=f"FICT-{1000 + i}",
        )
        p.club = club
        db.add(p)
        db.flush()
        for season, prev_club in (("2024-25", club), ("2025-26", club)):
            apps = rng.randint(6, 30)
            starts = rng.randint(max(0, apps - 8), apps)
            minutes = int(starts * rng.uniform(70, 90) + (apps - starts) * rng.uniform(10, 30))
            line = _stat_line(rng, pos, talent, max(90, minutes), apps, starts)
            db.add(PlayerSeasonStats(player_id=p.id, season=season, league_id=prev_club.league_id,
                                     club_name=prev_club.name, data_source_id=src.id, is_fictional=True, **line))
        players.append((p, talent))
    db.flush()

    # ---- pipeline, video, reports (fictional workflow history)
    stages_plan = (["identified"] * 6 + ["under_observation"] * 6 + ["data_analysis"] * 4 + ["video_analysis"] * 4
                   + ["shortlisted"] * 4 + ["live_scouting"] * 2 + ["approved"] * 1 + ["negotiation"] * 1
                   + ["signed"] * 1 + ["rejected"] * 3)
    order = ["identified", "under_observation", "data_analysis", "video_analysis", "shortlisted", "live_scouting",
             "approved", "negotiation", "signed"]
    candidates = sorted(players, key=lambda x: -x[1])[: len(stages_plan) + 10]
    rng.shuffle(candidates)
    base_time = _now() - timedelta(days=80)
    for (p, talent), target in zip(candidates, stages_plan):
        scout = wa if p.club.league.country in ("Senegal", "Côte d'Ivoire", "Ghana", "Nigeria", "Mali") else \
            eu if p.club.league.country in ("Portugal", "France", "Belgium") else head
        e = PipelineEntry(player_id=p.id, stage="identified",
                          priority=rng.choices(["high", "medium", "low"], [3, 5, 2])[0],
                          target_position=p.primary_position, assigned_scout_id=scout.id, created_by_id=head.id,
                          created_at=base_time)
        db.add(e)
        db.flush()
        t = base_time + timedelta(days=rng.randint(0, 20))
        db.add(PipelineEvent(entry_id=e.id, from_stage=None, to_stage="identified",
                             note="Identified via database search (fictional demo)", user_id=scout.id, created_at=t))
        path = order[: order.index(target) + 1] if target != "rejected" else order[: rng.randint(2, 5)] + ["rejected"]
        actor = {"under_observation": scout, "data_analysis": analyst, "video_analysis": video, "shortlisted": head,
                 "live_scouting": head, "approved": director, "negotiation": director, "signed": director,
                 "rejected": head}
        prev = "identified"
        for st in path[1:]:
            t += timedelta(days=rng.randint(2, 8))
            if st in ("shortlisted",) or (st == "rejected" and order.index(prev) >= 3):
                _add_scouting_evidence(db, rng, p, talent, scout, video, t)
            if st == "approved":
                draft = generate_report(db, p)
                db.add(ScoutingReport(player_id=p.id, author_id=head.id, title=f"Scouting report — {p.full_name}",
                                      sections=draft["sections"], risk_level=draft["risk_level"], auto_generated=True,
                                      status="final", recommendation="sign", potential_rating=7, created_at=t))
            db.add(PipelineEvent(entry_id=e.id, from_stage=prev, to_stage=st, user_id=actor[st].id, created_at=t,
                                 note=_note(st)))
            prev = st
        e.stage = prev
        if prev == "rejected":
            e.rejection_reason = "Data and video profile below role requirements (fictional demo)."
        e.updated_at = t

    db.add(RecruitmentBudget(season="2026-27", transfer_budget_eur=6_000_000, wage_budget_eur=2_500_000,
                             notes="FICTIONAL demo budget"))
    db.commit()


def _note(stage: str) -> str:
    return {
        "under_observation": "Assigned for regular monitoring.",
        "data_analysis": "Minutes and role profile sufficient for data review.",
        "video_analysis": "Data profile matches role template; request full-match video.",
        "shortlisted": "Video review positive across two full matches.",
        "live_scouting": "Schedule live viewing (home and away).",
        "approved": "Approved by Sporting Director after final report.",
        "negotiation": "Opening talks with selling club (no agent intermediary).",
        "signed": "Agreement concluded (fictional).",
        "rejected": "Does not meet requirements for target role.",
    }[stage] + " [FICTIONAL DEMO]"


def _add_scouting_evidence(db, rng, p, talent, scout, video_scout, when):
    v = MatchVideo(player_id=p.id, match_date=(when - timedelta(days=10)).date(), competition=p.club.league.name,
                   home_team=p.club.name, away_team="Opponent XI (fictional)",
                   video_url=f"https://licensed-video.example.com/match/{p.id}-{rng.randint(1000, 9999)}",
                   license_type="licensed_full_match", rights_holder="Example Licensed Provider (placeholder)",
                   license_confirmed=True, is_full_match=True, duration_minutes=96, created_by_id=video_scout.id,
                   notes="Placeholder link for demo — not a real video.", created_at=when)
    db.add(v)
    db.flush()
    cats = ["progressive_pass", "defensive_duel", "positioning", "pressing", "ball_carrying", "aerial_duel", "decision_making"]
    for _ in range(rng.randint(3, 6)):
        good = rng.random() < 0.45 + (talent - 1)
        db.add(VideoObservation(video_id=v.id, timestamp_seconds=rng.randint(60, 5700), category=rng.choice(cats),
                                phase=rng.choice(["in_possession", "out_of_possession", "attacking_transition", "defensive_transition"]),
                                assessment="positive" if good else rng.choice(["neutral", "negative"]),
                                technical_comment="Fictional demo observation: clean execution under pressure." if good
                                else "Fictional demo observation: execution broke down under pressure.",
                                tactical_comment="Fictional: good scanning before receiving." if good
                                else "Fictional: late to recognise the trigger to press.",
                                scout_id=video_scout.id, created_at=when))
    rating = max(4, min(9, int(round(6 + (talent - 1) * 8 + rng.gauss(0, 0.8)))))
    for author, otype, vid in ((video_scout, "video_full_match", v.id), (scout, "live", None)):
        db.add(MatchReport(player_id=p.id, video_id=vid, scout_id=author.id, observation_type=otype,
                           match_date=v.match_date, opponent="Opponent XI (fictional)", competition=v.competition,
                           position_played=p.primary_position, minutes_observed=90,
                           technical_rating=rating, tactical_rating=max(3, rating - rng.randint(0, 1)),
                           physical_rating=max(3, rating + rng.randint(-1, 1)), mental_rating=None,
                           overall_rating=rating,
                           technical_notes="Fictional demo note on first touch and passing range.",
                           tactical_notes="Fictional demo note on positioning and pressing triggers.",
                           physical_notes="Fictional demo note on acceleration and duel strength.",
                           strengths="Fictional: progressive passing, composure.",
                           weaknesses="Fictional: aerial timing, weak-foot use.",
                           summary="FICTIONAL DEMO REPORT.",
                           recommendation="shortlist" if rating >= 7 else "continue_monitoring",
                           created_at=when))
    db.flush()
