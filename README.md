# Ally Consumer Bank — AI Use Case Portfolio

**Live demo:** https://rudiselbrett-lab.github.io/director-ai-strategy/

A working demonstration of one process for every AI idea — so capacity goes to
what's worth building. Built as a single self-contained HTML page with four views:

- **Portfolio** — health and staleness tracking, a WSJF-ranked backlog against a
  capacity line, per-use-case suggested actions, and a filterable use case table.
- **Weekly Status** — RAG for the portfolio and its three elements, what changed
  since last week, which use cases and forums the coming week turns on, and the
  portfolio-level risks. Previous weeks are kept as issued.
- **Operating Model** — the mission, core principles, eight-stage lifecycle with
  accountable roles, five standing forums with decision rights, and next steps.
- **Intake** — a mock of the fifteen-minute use case intake form with live
  answer coaching.

All data is illustrative and this is not an Ally system of record. In production
Jira is the system of record and this page is the view; health, staleness,
capacity, and the weekly ratings recompute against the current date on every
load. To change the data, edit the `USE_CASES` and `TRENDS` arrays at the top of
the script in `ai-use-case-dashboard.html`.

Branding lives in four CSS custom properties (`--brand`, `--brand-2`,
`--accent`, `--accent-bright`) in the `:root` block — the values there are
approximated from Ally's public identity, and swapping them retints the whole
page. Status colors are deliberately excluded: green, amber, red, and orange are
reserved for health and never themed.

Deployed to GitHub Pages automatically on every push to `main`.
