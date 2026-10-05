# AI-OS.xlsx: sheet reference

Five dashboard tabs (purple), then the data sheets (blue), then Commands,
Config and Read Me (grey). Read this before your first write in a session.

## Dashboards: read only, never write

| Tab | What it answers | Sections |
|---|---|---|
| **Home** | What needs me today? | Tiles (each links to its tab) · Needs you · Use cases needing attention · Done this week · Accomplishments per week |
| **Portfolio** | Where does every use case stand? | Tiles · Pipeline by stage · What starts next: WSJF against capacity · All open use cases · Value realized vs projected · Portfolio mix |
| **Weekly Status** | What did this week's three sittings produce? | Overall, Flow, Value, Risk and controls (Red/Amber/Green) · Weekly Intake · Tactical Standup · Portfolio Council |
| **Gates** | Which gates are failing and why? | Tiles · By stage · Tier clock · Gate exceptions |
| **Use Case** | Everything about one use case | Picker (cell E5) · status tiles · the eight-gate strip · the record · its Inventory and Done history · commands |

The **one cell you may write on a dashboard** is `Use Case!E5`, the picker,
when I say `show <KEY>`.

Every "Say this" column holds the exact command for that row.

## Rules for the data sheets

- Blue header = input column. Grey header = formula: never type in it.
- To add a row: the first row where column A is empty; fill only the blue
  columns. The grey formulas are already there, down to row 1001 (Use Cases
  to row 501).
- Never insert, delete, sort, or edit existing rows on a log sheet. A
  correction is a new row that references the old one.
- Dates are real dates, not text.

## Use Cases (Jira snapshot). Inputs A–W. Formulas X onward.

Replaced in full on each refresh (see `jira.md`). One row per use case.

| Col | Field | Rule |
|---|---|---|
| A | Key | Jira key, e.g. `AI-003` |
| B | Use case | Jira summary |
| C | Status | Exactly as Jira shows it. Config maps it to a stage |
| D | Function | Business function. Payments, Collections, Consumer Lending, Fraud Operations make it high tier |
| E | Owner | PM owner |
| F | Sponsor | Named business sponsor; leave blank or write "(sponsor not named)" if none |
| G | Opened | Jira Created |
| H | Updated | Jira Updated. Drives freshness, so it must be right |
| I | Target | Expected exit date of the **current** stage. Drives health |
| J | Risk flags | Pipe-separated: `NPI` · `Reg report` · `No human review` |
| K | Impact | Pipe-separated: `revenue` · `cost` · `cycle` · `risk` · `insight` |
| L | Value $K | Estimated annual value in $K; blank until sized |
| M | Size | Job size in delivery points |
| N | WSJF | WSJF score; blank until scored |
| O | Metric | `Y` if a success metric and stop condition are set |
| P | Data ready | `ready` · `partial` · `none` · blank if not assessed |
| Q | Baseline | `Y` if a baseline is measured |
| R | Waiting on | What it is blocked on, if anything |
| S | Decided | Date of the triage decision |
| T | Outcome | `Declined` or `Transferred` if closed that way |
| U | Closed | Date closed |
| V | Flagged | `Y` if flagged in Jira |
| W | Topic | Topics slug, if one matches |

Computed (read these, never write): Stage · Stage # · Days to target ·
Since update · Health (`On track` / `At risk` / `Overdue`) · Freshness
(`Fresh` / `Aging` / `Stale`) · Tier (`Low` / `Medium` / `High`) · Tier
days · Age · Tier clock (`Inside` / `Over` / `Past approval`) · Gate
(`Good` / `Warning` / `Critical`) · What the gate needs · Next forum ·
Capacity (`Committed` / `Candidate`) · WSJF rank · Cum. points · Capacity
line (`Fits` / `Below line`) · Attention · Why · Say this · Jira link, and
helper keys the dashboards sort by.

## Inventory (append-only). Inputs A–J. Formulas K onward.

| Col | Field | Rule |
|---|---|---|
| A | ID | `INV-` + 4 digits, next after the highest |
| B | Date | Date the information arrived |
| C | Type | `New` · `Know` · `Decision` · `Conflict` · `Confirmed` · `Resolved` |
| D | Topic | A slug from Topics column A. If none fits, ask |
| E | Summary | One sentence, plain, no customer data |
| F | From | The person it came from |
| G | Channel | `Meeting` · `Email` · `Teams` · `Call` · `Document` · `Jira` · `Session` |
| H | Confidence | `Confirmed` · `Unconfirmed` |
| I | Ref | Required for `Confirmed`, `Resolved`, `Conflict`: the INV ID it refers to |
| J | Use case | Related use case key, if any. This is what puts it on the Use Case tab |

## Done (append-only). Inputs A–E.

Date · Accomplishment (an outcome, past tense) · Topic · Use case key ·
Source (`Session` / `Email` / `Teams` / `Calendar`)

## Value. Inputs A–D.

Quarter · Projected $K · Realized $K · Complete (`Y` once the quarter is
closed and measured). Append a row per quarter. Update Realized only when I
give you the Council's number, and show me before/after.

## Answers, Reviews, Changes (append-only)

- **Answers:** ID (`Q-` + 4 digits) · Date · Question · Kind (`Answer` / `Routed` / `Reuse`) · Answer or route · Source · Asked by · Ref
- **Reviews:** Date · Artifact · Author · Passed (of 8) · Failed · Verdict (`Ready` / `Fix first`) · Top fix
- **Changes:** Date · What changed · From · To · References updated · Approved by

## Topics, People (reference; changes need my yes)

- **Topics:** slug · Name · Owner · Forum (`Weekly Intake` / `Tactical Standup` / `Portfolio Council`) · Use cases · Status · Notes doc
- **People:** Name · Role · Team · Works with me on · How they work (facts only) · Source · Last updated

## Config

You write only the snapshot stamp: **B20** SnapshotAt (date and time),
**B21** SnapshotSource, **B22** SnapshotCount.

Read, never change: B4 OwnerName · B5 JiraSite · B6 JiraProjects · B7
JiraScope · B8 SampleAsOf · B12–B15 thresholds · B16 CapacityPoints ·
stages A27:E34 · tiers A38:C40 · high-tier functions A43:A50 · status map
G27:H66 · **Jira field map J27:L49** (which Jira field fills each Use Cases
column). If a Jira status isn't in the map, tell me and propose the stage.
