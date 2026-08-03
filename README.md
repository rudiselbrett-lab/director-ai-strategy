# AI Use Case Portfolio

**Live demo:** https://rudiselbrett-lab.github.io/director-ai-strategy/

A working demonstration of one process for every AI idea — so capacity goes to
what's worth building. Built as a single self-contained HTML page with three views:

- **Portfolio** — executive brief, health and staleness tracking, value and
  cycle-time trends, a WSJF-ranked backlog, and a filterable use case table.
- **Operating Model** — the mission, core principles, eight-stage lifecycle with
  accountable roles, operating routines, and next steps.
- **Intake** — a mock of the fifteen-minute use case intake form with live
  answer coaching.

All data is illustrative. In production, Jira is the system of record and this
page is the view; health, staleness, and the executive brief recompute against
the current date on every load. To change the data, edit the `USE_CASES` and
`TRENDS` arrays at the top of the script in `ai-use-case-dashboard.html`.

Deployed to GitHub Pages automatically on every push to `main`.
