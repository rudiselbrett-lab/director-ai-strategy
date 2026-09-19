# Ally Consumer Bank — AI Use Case Portfolio

**Live demo:** https://rudiselbrett-lab.github.io/director-ai-strategy/

A working demonstration of one way in for every AI idea — so capacity goes to
what's worth building. Built as a single self-contained HTML page with six views:

- **Operating Model** — the operating model document itself, section for
  section: the principle it opens on, the eight stages with the three things
  that have to be true to leave each, the intake and triage gates, cycle time
  by risk tier, the three weekly routines and their escalation rule, gate
  ownership and criteria, the results, and what it all means operationally.
  The stage cards, tier cards, routine boxes and gate table are drawn from the
  same stage, tier and routine definitions the rest of the page reads, so the
  document and the board cannot say different things.
- **Intake Form** — a mock of the fifteen-minute use case intake form with
  live answer coaching.
- **Portfolio Dashboard** — health and staleness tracking, a WSJF-ranked backlog
  against a capacity line, per-use-case suggested actions, a filterable use case
  table carrying each one's risk tier, and the trend panels.
- **Weekly Status** — RAG for the portfolio and its three elements, then the
  week as its three sittings produced it: what the front door took in and
  decided, what the standup found and escalated, and the Council's what's new,
  what we need to know, and what needs a decision or discussion. Each routine's
  sections come from its own definition, so renaming a routine or moving a
  stage rewrites the report. Previous weeks are kept as issued.
- **Jira** — the same use cases as Jira issues, styled as Jira: the eight
  stages with every issue sitting in one of them, graded against the gate for
  the stage it is in — which is how redness is decided, not a score across all
  eight at once. Then the backlog view with workflow statuses and flagged rows,
  and one issue opened with its full field set and comment stream. Nothing here
  says what to do about any of it; that is the weekly status's job, produced by
  the routines that actually meet.
- **AI First** — *The AI Operating System*: a written piece on running the work
  with AI as infrastructure rather than as a search box, in three layers —
  information, action, automation.

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

A CSV carries no authoring date, so a page built from one has `ANCHOR` set to
null and reads every date literally — which is what real data wants. Rebuild the
bundled sample that way and it looks overdue across the board, because its dates
are from when it was written. That is the sliding turned off, not a fault.

The script only supplies data. Health, staleness, completeness, WSJF rank, the
risk tier, the capacity line, suggested actions, the weekly ratings, routine
sittings and the portfolio risks are all computed in the page against the date
it is opened — so a page built today still reads correctly next month.

The risk tier has no column on purpose. It is derived from the risk flags, the
function and the impact a use case already carries, so a customer-facing credit
model cannot be filed as low tier by whoever is in a hurry.

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
