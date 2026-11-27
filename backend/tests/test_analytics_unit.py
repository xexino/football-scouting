"""Pure unit tests for the analytics maths (no HTTP)."""
from types import SimpleNamespace

from app.analytics import METRICS, aggregate, compute_metric, ordinal, percentile, role_fit
from app.models import STAT_FIELDS


def row(league_coef=None, **values):
    d = {f: None for f in STAT_FIELDS}
    d.update(values)
    league = SimpleNamespace(strength_coefficient=league_coef) if league_coef is not None else None
    return SimpleNamespace(league=league, **d)


def test_per90_normalisation():
    totals = aggregate([row(minutes=1800, progressive_passes=100)])
    assert compute_metric(METRICS["prog_passes_p90"], totals) == 5.0


def test_missing_values_are_not_zero():
    totals = aggregate([row(minutes=900)])
    assert compute_metric(METRICS["prog_passes_p90"], totals) is None


def test_aggregate_incomplete_coverage_is_none():
    totals = aggregate([row(minutes=900, interceptions=10), row(minutes=900, interceptions=None)])
    assert totals["minutes"] == 1800
    assert totals["interceptions"] is None


def test_ratio_requires_minimum_attempts():
    small = aggregate([row(minutes=900, aerial_duels=10, aerial_duels_won=8)])
    assert compute_metric(METRICS["aerial_pct"], small) is None
    big = aggregate([row(minutes=900, aerial_duels=50, aerial_duels_won=30)])
    assert compute_metric(METRICS["aerial_pct"], big) == 60.0


def test_league_adjustment_only_with_coefficient():
    with_coef = aggregate([row(league_coef=0.8, minutes=900, interceptions=20)])
    assert compute_metric(METRICS["interceptions_p90"], with_coef, adjusted=True) == 1.6
    without = aggregate([row(minutes=900, interceptions=20)])
    assert compute_metric(METRICS["interceptions_p90"], without, adjusted=True) is None
    # ratios are never league-adjusted
    assert METRICS["pass_pct"].league_adjust is False


def test_goals_prevented():
    totals = aggregate([row(minutes=900, psxg_faced=12.0, goals_conceded=9)])
    assert compute_metric(METRICS["goals_prevented_p90"], totals) == 0.3


def test_percentile_needs_population_and_handles_direction():
    assert percentile(5, [1, 2, 3]) is None
    pop = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert percentile(10, pop) == 95.0
    assert percentile(1, pop, higher_is_better=False) == 95.0


def test_role_fit_reports_coverage():
    pcts = {"aerials_won_p90": {"percentile": 80}, "aerial_pct": {"percentile": 60}}
    fit = role_fit(pcts, "target_striker")
    assert fit["evidence_type"] == "model_estimate"
    assert fit["score"] == round((80 * 3 + 60 * 2) / 5, 1)
    assert fit["data_coverage_pct"] == 50


def test_ordinal():
    assert [ordinal(x) for x in (1, 2, 3, 4, 11, 12, 13, 21, 81, 96)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "81st", "96th"]
