# Analytics methodology

Implemented in `backend/app/analytics.py`. The guiding rule: **describe output honestly,
never overstate what statistics prove.**

## Normalisation

* **Per 90:** `value / minutes × 90`, on season totals.
* **Ratios:** `completed / attempted × 100`, only when attempts reach a minimum
  (e.g. 100 passes, 40 defensive duels, 25 aerial duels, 20 dribbles) — otherwise `n/a`.
* **Multiple seasons / competitions** are summed before normalising. If any row lacks a
  field, the aggregate for that field is `null` (incomplete coverage is not hidden).
* **Missing ≠ zero.** Nothing is imputed.

## League adjustment

Volume metrics (per-90 counts) may be multiplied by the competition's
`strength_coefficient` (1.0 = reference level). The coefficient must have a recorded
`coefficient_source`. Ratios are never adjusted. Raw values are always displayed next to
adjusted ones. The demo coefficients are fictional; replace them with a documented
methodology (e.g. derived from club Elo / continental results) before relying on them.

## Percentiles

For each position, the reference pool is every player in the database whose primary
position matches and who has ≥ `MIN_MINUTES_POOL` minutes in the season analysed.
Percentile = `(below + ½ equal) / n × 100`, inverted for lower-is-better metrics (fouls,
goals conceded). Pools under 5 give no percentile; pools under 20 are flagged as coarse.
The pool reflects **who Raja has chosen to track**, not world football.

## Position profiles

| Pos | Indicators |
|---|---|
| GK | Save %, goals prevented /90 (PSxG − GA), goals conceded /90, clean sheet %, pass %, long pass %, aerials won |
| CB | Defensive duel %, defensive duels, interceptions, aerials won, aerial %, clearances, pass %, progressive passes, long pass % |
| FB | Defensive duel %, tackles won, interceptions, progressive passes, progressive carries, crosses, cross %, xA, recoveries |
| DM | Interceptions, recoveries, tackles won, defensive duel %, pass %, progressive passes, long pass %, aerial %, pressures |
| CM | Pass %, progressive passes, final-third passes, progressive carries, key passes, xA, recoveries, defensive duel %, npxG |
| AM | xA, key passes, npxG, NP goals, dribbles, progressive carries, final-third passes, box touches, pressures |
| W | npxG, NP goals, xA, dribbles, dribble %, progressive carries, crosses, box touches, key passes |
| ST | NP goals, npxG, shots, npxG/shot, box touches, xA, aerials won, aerial %, pressures |

## Consistency

Per season: minutes, minutes share (`minutes / (team matches × 90)`), start rate and profile
metrics. Season-to-season variation = coefficient of variation of each per-90 metric across
seasons with ≥ `MIN_MINUTES_RELIABLE` minutes.

## Tactical role fit (model estimate)

Weighted mean of the player's percentiles for indicators the staff associate with a role
(e.g. *Ball-playing centre-back*: progressive passes ×3, pass % ×2, long pass % ×2,
defensive duel % ×2, aerial % ×2, interceptions ×1). Data coverage is reported. The weights
are a hypothesis owned by the technical staff (edit `TACTICAL_ROLES`), not a truth.

## Data-derived strengths & weaknesses

Profile metrics ≥ 70th percentile / ≤ 30th percentile. Labelled “data-derived”.

## What the platform deliberately does not do

* Produce a single “player rating”.
* Infer personality, mentality or character from statistics.
* Treat correlation with team results as evidence of individual quality.
* Treat highlight clips as complete match analysis.
* Make signing decisions — reports leave the recommendation to authorised staff.
