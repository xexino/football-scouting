# Product Council — charter

A small council of AI agents reviews the repository every day, reports risks and proposes what
to build next. **The founder keeps every business decision.** Agent definitions live in
`.claude/agents/`; a meeting is run with the `/council-meeting` skill.

## Members

| Agent | Role | Owns |
|---|---|---|
| `council-chair` | Product & delivery lead | Runs the meeting, sets ≤ 3 priorities, writes minutes and backlog, escalates founder decisions |
| `security-guardian` | Security & tenant isolation | Cross-tenant leaks, auth/RBAC, secrets, headers; runs isolation/security suites |
| `data-licensing-officer` | Data sources, licensing, data protection | Provider coverage, licensing register, quotas, Loi 09-08 / GDPR, "no unverified data in production" |
| `scouting-analyst` | Football recruitment expert | Methodology, young-talent discovery, AI-suggestion quality, data-vs-opinion separation |
| `qa-release-engineer` | Tests & releases | SQLite/PostgreSQL suites, migrations, browser smoke tests, regressions |
| `product-ux` | Club experience | Scout/director usability, FR/AR + RTL, mobile, accessibility, provenance badges |

Why these six: each owns a risk that has already caused real findings in this project
(isolation bugs, licensing traps, misleading analytics, migration bugs, UX regressions).
Deliberately absent: marketing/sales and finance agents — those decisions belong to the founder.

## Daily meeting

1. **Inputs** — previous minutes, `BACKLOG.md`, `git log` since last meeting, open founder questions.
2. **Reports** — each member reviews independently (in parallel) and reports findings with evidence
   (file:line, test command + result, document link). No evidence → not reported.
3. **Decision** — the chair ranks at most 3 priorities:
   security/isolation > legal/licensing > broken functionality > pilot-club value > polish.
4. **Output** — `docs/council/minutes/YYYY-MM-DD.md` and an updated `BACKLOG.md`.
5. **Optional delivery** — the council may implement **one small, low-risk item** from the
   approved backlog (bug fix, test, documentation) on a branch `council/YYYY-MM-DD`, with tests
   passing, and open a pull request for founder review. It never merges.

## Hard limits (cannot be overridden by any agent)

- No purchases, subscriptions, paid API plans or contracts.
- No new data provider in production unless the licensing register marks it VERIFIED for
  commercial use; no scraping; no bypassing bot protection.
- No secrets in the repository or frontend; no changes to environment/network/permission settings.
- No merges to the default branch, no deployments, no messages to external people.
- No claims of passing tests without the command and its output.

## Founder decisions (always escalated, with a recommendation)

Pricing and plans · paid data providers · licence interpretations · pilot-club agreements ·
anything public, irreversible or affecting real customer data.

## Minutes template

```
# Council minutes — YYYY-MM-DD
Attendees: chair, security, data, scouting, qa, ux
Changes since last meeting: <commits / PRs>
## Reports (one section per member: findings with severity + evidence)
## Decisions — priorities for the next 24 h (max 3, ranked, each with owner and acceptance test)
## Founder decisions needed (question · options · recommendation · deadline)
## Delivered today (branch / PR / tests run) — or "nothing delivered"
```
