---
name: council-meeting
description: Run the daily Raja Scout Intelligence product council — the six council agents review the repository in parallel, the chair sets at most three priorities, writes minutes and backlog, and lists founder decisions. Use when asked to run the council meeting or the daily review.
---
# Daily council meeting

Follow `docs/council/COUNCIL.md` exactly, including its hard limits.

1. **Prepare** — find the newest file in `docs/council/minutes/` (if any), read it and
   `docs/council/BACKLOG.md`; collect `git log --oneline` since that date (or the last 20 commits).
2. **Reports in parallel** — launch these agents with the Agent tool in ONE message, giving each
   the date of the previous meeting and the commit list:
   `security-guardian`, `data-licensing-officer`, `scouting-analyst`, `qa-release-engineer`, `product-ux`.
   Each must return findings with evidence and its top proposals.
3. **Chair** — pass all five reports to `council-chair`; it writes
   `docs/council/minutes/<today>.md` (template in the charter) and updates `docs/council/BACKLOG.md`.
4. **Optional delivery** — only if the minutes name one small, low-risk item as "deliver today":
   create branch `council/<today>`, implement it with tests, run the full test suite, commit,
   push the branch and open a pull request for the founder. Never merge.
5. **Finish** — commit the minutes and backlog on the working branch, push, and reply with a
   five-line summary: top priorities, founder decisions needed, what was delivered, test results.
