# Ally Consumer Bank — AI Use Case Portfolio

**Live demo:** https://rudiselbrett-lab.github.io/director-ai-strategy/

A working demonstration of one process for every AI idea — so capacity goes to
what's worth building. Built as a single self-contained HTML page with five views:

- **Operating Model** — the mission, core principles, eight-stage lifecycle with
  accountable roles, five standing forums with decision rights, and next steps.
- **Intake Form** — a mock of the fifteen-minute use case intake form with
  live answer coaching.
- **Portfolio Dashboard** — health and staleness tracking, a WSJF-ranked backlog
  against a capacity line, per-use-case suggested actions, and a filterable use
  case table.
- **Weekly Status** — RAG for the portfolio and its three elements, what changed
  since last week, which use cases and forums the coming week turns on, and the
  portfolio-level risks. Previous weeks are kept as issued.
- **Jira** — the same use cases as Jira issues, styled as Jira: the backlog view
  with workflow statuses and flagged rows, and one issue opened with its full
  field set and comment stream.

All data is illustrative and this is not an Ally system of record. In production
Jira is the system of record and this page is the view; health, staleness,
capacity, and the weekly ratings recompute against the current date on every
load.

## Building it from Python

`build_portfolio.py` is a single file with no dependencies — Python 3.8 or
newer and nothing else. The page template and the sample portfolio are both
embedded in it, so you can copy that one file to any machine and run it:

```
python3 build_portfolio.py            # writes ai-use-case-portfolio.html
python3 build_portfolio.py --open     # and opens it
```

To change the data, round-trip it through JSON or a spreadsheet:

```
python3 build_portfolio.py --write-data portfolio.json   # dump it
python3 build_portfolio.py --data portfolio.json         # rebuild from it

python3 build_portfolio.py --write-csv use_cases.csv     # just the use cases
python3 build_portfolio.py --csv use_cases.csv           # rebuild from it
```

The CSV path is the one a Jira export would take: export the issues, map the
columns, rebuild. List fields (`impact`, `risk`) are pipe-separated.

The script only supplies data. Health, staleness, completeness, WSJF rank, the
capacity line, suggested actions, the weekly ratings, forum sittings and the
portfolio risks are all computed in the page against the date it is opened —
so a page built today still reads correctly next month.

If `ai-use-case-dashboard.html` sits next to the script it is used as the
template, so you can iterate on the design and rebuild. Otherwise the embedded
copy is used. The data the script replaces is delimited by the `DATA BLOCK`
markers in that file.

## Editing the page directly

To change the data by hand instead, edit the `USE_CASES` and `TRENDS` arrays at
the top of the script in `ai-use-case-dashboard.html`.

Branding lives in four CSS custom properties (`--brand`, `--brand-2`,
`--accent`, `--accent-bright`) in the `:root` block — the values there are
approximated from Ally's public identity, and swapping them retints the whole
page. Status colors are deliberately excluded: green, amber, red, and orange are
reserved for health and never themed.

Deployed to GitHub Pages automatically on every push to `main`.
