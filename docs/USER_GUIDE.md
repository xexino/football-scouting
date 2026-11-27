# User guide

## Roles at a glance

| Role | Typical work | Notable rights |
|---|---|---|
| **Sporting Director** | Decisions and budget | Approve, open negotiations, confirm signings, set budget, see financials, audit log |
| **Head of Scouting** | Runs the department | Manage players & stats, import, video, finalise reports, assign scouts, delete players |
| **Data Analyst** | Data quality and analysis | Add/import statistics, create players, reports, move pipeline (scouting stages) |
| **Video Scout** | Video analysis | Link licensed footage, timestamped observations, match reports |
| **Regional Scout** | Live scouting in a territory | Add players, live match reports, reports, move pipeline (scouting stages) |
| **Administrator** | IT / access | Users, backups, everything |

Fees, salaries and agent names are hidden from Video and Regional Scouts and Data Analysts.
The full matrix is in **Administration → Role permissions**.

## Core workflow

1. **Find** — *Player database*. Combine profile filters with statistical indicators
   ("Progressive passes /90 ≥ 4", "Aerial duel success % ≥ 60"). Sort by any metric.
   Tick players to compare them.
2. **Identify** — open a player and click **+ Add to pipeline**. Give a reason, priority and
   assigned scout. The player enters *Identified*.
3. **Observe & analyse** — on the *Statistics & analytics* tab read per-90 values, percentiles,
   consistency and tactical role fit, **including the caveats box**. Record decisions by
   moving the player to *Under Observation*, *Data Analysis*, *Video Analysis*.
4. **Video** — on the *Video* tab link **licensed** footage, tick the licence confirmation,
   mark whether it is a complete match, then log timestamped observations (category, phase,
   positive/neutral/negative, technical and tactical comments). Write a match report from
   the footage.
5. **Shortlist** — requires at least one match report. Then *Live Scouting*: regional scouts
   file **Live scouting reports** from the *Match reports* tab.
6. **Report** — **Generate report** creates a draft that compiles all evidence. Each line is
   labelled:
   * `DATA` — from an identified data source (source shown)
   * `SCOUT` — opinion of a named scout
   * `MODEL` — platform calculation (percentiles, role fit, risk flags)
   * `FICTIONAL` — demo data
   * `NO EVIDENCE` / `INPUT REQUIRED` — gaps to close
   Scouts add their own assessments with **+ Add scout assessment** (labelled `SCOUT` and
   attributed). The Head of Scouting sets recommendation, potential and risk, then
   **Finalise** (locks the report).
7. **Approve → Negotiate → Sign** — Sporting Director only. *Approved* requires a finalised
   report. *Signed* is only reachable from *Negotiation* and is final.

Every stage change needs a written rationale and is stored permanently (name, time, from/to
stage) — see the *Pipeline history* tab and the dashboard.

### Pipeline rules

* Stages advance one at a time. The Sporting Director may skip stages; the skip is recorded.
* Moving back to an earlier stage is always allowed (with rationale).
* *Rejected* can be reached from any stage (approved/negotiation only by the Sporting Director)
  and can be re-opened into a scouting stage.

## Reading the analytics responsibly

* **Per 90** values below 900 minutes are flagged *small sample*.
* **Percentiles** compare against players *in this database* at the same position with
  ≥450 minutes — the pool is shown. With fewer than 5 players no percentile is given.
* **League-adjusted** values only appear when the competition has a documented strength
  coefficient. They are approximations.
* **Role fit** is a weighted average of percentiles for indicators linked to a role in the club's
  game model. It is a screening aid, not a rating.
* Numbers describe *what a player did* in his team's context. They do not prove quality —
  always combine them with full-match video and live viewing.

See [ANALYTICS.md](ANALYTICS.md) for formulas.

## Video scouting rules

* Only link footage your organization is licensed or authorised to view. The platform stores links,
  never files.
* Highlight packages are always flagged and reports based on them display
  “Based on highlights only — not equivalent to complete match analysis”. They cannot be
  registered as full matches.

## Importing data

*Data import* (Head of Scouting, Data Analyst, Administrator):

1. Register the **data source** with its licence terms.
2. Download the players or stats CSV template.
3. Upload with **Dry run** ticked to validate; fix row errors; run again without dry run.

Empty cells are stored as *not available*. Re-importing the same player (name + date of
birth) updates the record; statistics are unique per player/season/competition/source.

## Dashboard

Shows database size (real vs fictional, stale records), the recruitment funnel, budget
(committed = signed; pending = approved + negotiation, using estimated fees), priority targets,
shortlist, players under observation, 12-week activity and per-scout productivity.

## Administration

Users (create, change role, deactivate, reset password), recruitment budgets, full JSON
export, CSV export, role-permission matrix and the audit log of all actions (logins, edits,
imports, exports, pipeline decisions).
