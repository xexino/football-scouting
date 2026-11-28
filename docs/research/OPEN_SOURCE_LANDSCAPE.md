# Open-source scouting projects on GitHub — analysis and adoption decision

Date: 2026-11-28. Method: GitHub repository search (9 queries, top 15 by stars each, ~140 results),
then a read-only shallow clone of the 11 most relevant projects to read their licence, data sources,
stack and code. No third-party code was executed. Star counts and dates are from the GitHub API on
the day of the review.

## 1. Bottom line

**Keep Raja Scout Intelligence as the base. Do not move onto another project, and do not merge another project's code base.**
Instead, adopt three permissively licensed **libraries** and re-implement two or three **ideas**
(with credit) inside our own architecture.

Why we keep our own project:

- **It is a product, the others are mostly portfolio pieces.** Every scouting repo found is a
  single-author project, usually a Streamlit or notebook showcase with 0–80 stars.
- **None of them has what a paying club needs**, all of which we already have:
  - multi-tenant isolation;
  - logins with 6 roles;
  - an audit log;
  - a recruitment pipeline with history;
  - evidence-tagged scouting reports;
  - subscriptions;
  - a security audit plus 136 tests.
- **Their code is mostly not usable legally.** Most repos have no licence (by default that means
  all rights reserved) or a non-commercial one.
- **Their data is the bigger blocker.** The data under these projects is scraped (FBref, Sofascore,
  Transfermarkt) or is StatsBomb Open Data. StatsBomb's own agreement forbids commercial use,
  *including analysis derived from the data*. Several authors confirm this restriction in their own
  documentation.

Taking any of them in would add legal risk without adding the parts we lack.

## 2. The project you named: `panospen/football-tactical-dashboard`

| Item | Finding |
|---|---|
| What it is | Streamlit dashboard: match analysis in 7 tabs (passing network, pressing/PPDA, build-up, shots & xG, player roles, radar), season per-90 view, cosine-similarity recruitment tool, and a 5-page PDF match report |
| Size / activity | ~5,300 lines of Python, 35 files, 4 stars, last commit 2026-04-07 |
| Licence | **No LICENSE file → all rights reserved.** We cannot copy or merge its code without written permission from the author |
| Data | StatsBomb Open Data only (La Liga 2015–21, UCL 2017–19, World Cups 2018/22, Euros 2020/24). Our register already lists it as `VERIFIED-NON-COMMERCIAL`: no third-party provision, and no commercial exploitation of the data *or of analysis derived from it* |
| Architecture | Single-user Streamlit app; no database, users, permissions or API. Caches Parquet on local disk |
| Quality | Clean, readable analysis code, and its per-90 maths is done correctly from season totals. It has no tests. |

**Verdict: do not merge.** It is a good *reference* for which match-analysis visuals scouts value.
The visuals themselves come from the `mplsoccer` library (MIT), which we can use directly. Section 4
lists the ones worth rebuilding on our own licensed data.

## 3. Candidates compared

| Repository | ★ | Licence | Data source | What it is | Usable by us? |
|---|---|---|---|---|---|
| panospen/football-tactical-dashboard | 4 | **None** | StatsBomb Open (non-commercial) | Streamlit tactical and match dashboard | No: no licence, non-commercial data |
| **aaronexposito0-creator/football-recruitment-platform** | 0 | **MIT** | StatsBomb Open (Euro 2024) | FastAPI + TypeScript recruitment research tool: discovery, explainable similarity, archetype "fit", shortlist, CSV/XLSX import, EN/ES/FR | **Ideas and code reusable with attribution.** Its data is not; it has no users or tenancy |
| LaErre9/Player_Scouting_Recommendation_System | 46 | **CC BY-NC 4.0** | FBref-derived CSV | Similarity + GPT-generated reports (IEEE paper) | No: non-commercial |
| MS3B09/Botola-Scout | 9 | Apache-2.0 | **Scraped** Sofascore + Transfermarkt | Streamlit scouting for Morocco's Botola Pro 2023/24 | Code yes, data **no** (scraping is against our rules). Shows there is demand for Botola coverage |
| KikeRev/smart_scout_app | 3 | MIT | **Scraped** FBref + Transfermarkt (45k players) | Django app with FIFA-style ratings and AI queries | Data no. "FIFA-style ratings" clash with our no-overclaiming rules |
| muthukumaranL/Football-Intelligence-Scouting-Platform | 1 | MIT | Synthetic / Kaggle | Streamlit "undervalued player" and "transfer success" ML | No: predictions on synthetic data; labels like "Rising Star" breach our AI rules |
| ArMat-Analytics/Contextual-Football-Scouting | 2 | MIT | StatsBomb 360 + scraped Transfermarkt | Research notebooks: EPV, decision quality, off-ball runs | Methodology reference only |
| olliestanley/autoscout | 3 | MIT | **Scraped** FBref | Python scouting scripts | No |
| talal-atiq/scout-reports | 3 | **None** | Event data | TypeScript platform with xT maps and pizza charts | No: no licence |
| alexislopesdossantos/football-analytics-pipeline | 4 | **None** | API-Football → PostgreSQL → Power BI | Pipeline + Power BI | No: no licence; Power BI |
| Neuttjee/football-scouting-platform | 1 | **None** | — | Next.js + Prisma club scouting app (Dutch) | No: no licence. Its repo also contains a committed `.env` file and a Node.js binary |

### Established libraries (the realistic things to adopt)

| Library | ★ | Licence | Use for us | Decision |
|---|---|---|---|---|
| **andrewRowlinson/mplsoccer** | 556 | MIT | Pitch plots, shot maps, heatmaps, passing networks, radar and pizza charts | **Adopt** for player-profile and report visuals (server-side images / PDF) |
| **PySport/kloppy** | 574 | BSD-3 | One loader for event and tracking data from many providers (StatsBomb, Wyscout, Opta, SkillCorner…) | **Adopt** once a licensed provider is chosen; it stops us being tied to one provider |
| **ML-KULeuven/socceraction** | 831 | MIT | SPADL format, Expected Threat (xT), VAEP action values | **Adopt later**, only on licensed event data |
| roboflow/sports | 5,520 | MIT (code) | Computer-vision player tracking from match video | **Evaluate later.** Heavy GPU workload; detection models may carry other licences (UNVERIFIED); only on footage the club has rights to |
| probberechts/soccerdata | 2,148 | NOASSERTION | Scrapers for FBref, Sofascore, WhoScored… | **Reject for production** (scraping restricted sources) |
| oseymour/ScraperFC | 424 | GPL-3.0 | Scrapers | **Reject** (scraping + copyleft) |
| SkillCorner/opendata | 475 | MIT | 10 matches of broadcast tracking data | Use for internal R&D only, after the founder reads its terms |

## 4. What to take into our project (proposed, in order)

1. **Pitch visuals with `mplsoccer`**: shot map, action heatmap and radar on the player profile, and
   in a one-click PDF scouting report. These are the visuals panospen's dashboard shows; we would
   build them on our own (licensed or club-entered) data. *Small, safe, high visibility.*
2. **Explainable similarity** (idea and MIT code from football-recruitment-platform, credited):
   - "find players like X" over per-90 metrics, compared within the same position group;
   - only metrics both players have, and only above a minimum-minutes threshold;
   - a metric-by-metric explanation of the result;
   - the label "statistical likeness is not proof of quality", which fits our "no confusing
     correlation with quality" rule.
3. **Sample-size-aware percentiles**: show the comparison group and its size next to every
   percentile, and grey out small samples. That project's metric-governance document is a good
   checklist.
4. **Provider-neutral ingest via `kloppy`** when the founder approves a paid or licensed event-data
   provider. Add `socceraction` xT/VAEP on top only then.
5. **Botola Pro coverage**: Botola-Scout proves the demand. Its scraped data cannot be used. The
   route is a licensed provider (the coverage matrix in `docs/data/`) or club-entered data through
   our CSV import.

Not taken: FIFA-style overall ratings, "transfer success probability", and labels like
"Rising Star". They overclaim, and they conflict with the AI rules the founder set.

## 5. Founder decisions needed

- Approve step 1 (mplsoccer visuals + PDF report) as the next small PR. It needs no new data and
  costs nothing.
- If panospen's code itself is wanted, someone must ask the author for a licence. Rebuilding with
  mplsoccer is the cleaner path, and doesn't need their code.
- StatsBomb Open Data stays **internal research only**: never in the product or the demo.
