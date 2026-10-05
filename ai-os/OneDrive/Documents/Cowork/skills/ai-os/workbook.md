# AI-OS.xlsx: sheet reference

Exact columns for every sheet you write to. Letters matter: fill only the
input columns listed, in the first row where column A is empty. Everything
to the right of the input columns is a formula already in place.

Dates are real dates (YYYY-MM-DD), not text.

## Inventory (append-only). Inputs A–J. Formulas K–O.

| Col | Field | Rule |
|---|---|---|
| A | ID | `INV-` + 4 digits, next number after the highest existing ID |
| B | Date | Date the information arrived |
| C | Type | `New` (what's new) · `Know` (what we need to know) · `Decision` (decision needed) · `Conflict` · `Confirmed` · `Resolved` |
| D | Topic | A slug from the Topics sheet, column A. If none fits, ask before inventing one |
| E | Summary | One sentence, plain, no customer data |
| F | From | The person it came from (as on the People sheet if they're there) |
| G | Channel | `Meeting` · `Email` · `Teams` · `Call` · `Document` · `Jira` · `Session` |
| H | Confidence | `Confirmed` (first-hand or verified) · `Unconfirmed` (second-hand) |
| I | Ref | Required for `Confirmed`, `Resolved`, `Conflict`: the INV ID it refers to |
| J | Jira | Related issue key, if any |

Computed (read only): K State (`Open`, `Closed`, `Unconfirmed`, `Confirmed`,
`Logged`) · L Age · M Severity · N Rank key · O Say this.

## Jira (snapshot). Inputs A–L. Formulas M–T.

| Col | Field | Rule |
|---|---|---|
| A | Key | e.g. `AIUC-104` |
| B | Summary | Issue summary |
| C | Status | Exactly as Jira shows it |
| D | Type | Epic, Story, Task... |
| E | Priority | |
| F | Assignee | Display name, or `Unassigned` |
| G | Created | Date |
| H | Updated | Date. Drives staleness, so it must be right |
| I | Due | Date or blank |
| J | Flagged | `Y` if flagged, an impediment, or labelled blocked; else blank |
| K | Labels | Comma-separated |
| L | Topic | Topic slug if the issue's key or label matches a Topics row (column E); else blank |

Computed: M Stage · N Days idle · O Stale after · P Health · Q Why · R Rank
key · S Say this · T Link.

## Done (append-only). Inputs A–E. Formulas F–H.

| Col | Field | Rule |
|---|---|---|
| A | Date | Day it was done |
| B | Accomplishment | An outcome, past tense. "Got MRM sign-off on X", not "met with MRM" |
| C | Topic | Slug |
| D | Jira | Key, if any |
| E | Source | `Session` · `Email` · `Teams` · `Calendar` |

## Answers (append-only). Inputs A–H. Formula I.

| Col | Field | Rule |
|---|---|---|
| A | ID | `Q-` + 4 digits |
| B | Date | |
| C | Question | As asked, minus anything personal |
| D | Kind | `Answer` · `Routed` · `Reuse` |
| E | Answer or route | |
| F | Source | Link or document it traces to, or who it was routed to |
| G | Asked by | |
| H | Ref | For `Reuse`: the Q ID reused |

## Reviews (append-only). Inputs A–G.

Date · Artifact · Author · Passed (of 8) · Failed · Verdict (`Ready` / `Fix first`) · Top fix

## Changes (append-only). Inputs A–F.

Date · What changed · From · To · References updated · Approved by

## Topics (reference). Inputs A–G. Formulas H–J.

Topic slug · Name · Owner · Forum (`Front door` / `Standup` / `Council`) ·
Jira label (key or label) · Status (`Active` / `Paused` / `Closed`) · Notes doc path

## People (reference). Inputs A–G.

Name · Role · Team · Works with me on (topic slugs) · How they work (facts
only) · Source · Last updated

## Config

You write only:

| Cell | Name | What |
|---|---|---|
| B17 | SnapshotAt | Date and time of this Jira pull |
| B18 | SnapshotSource | `Copilot connector (Jira Cloud)`, `Copilot connector (Jira Data Center)`, or `CSV: <file name>` |
| B19 | SnapshotCount | Number of issues written |

Read but never change: B4 OwnerName · B5 JiraSite · B6 JiraProjects ·
B7 JiraScope · B8 SampleAsOf · B11–B14 thresholds · the stage table
(A22:C30) · the status map (E22:F62). If a Jira status is missing from the
map, tell me and propose the stage. Don't add it yourself.

## Reading the Dashboard

- B2 / F2: as-of date and the data warning banner.
- Row 5: open decisions, unconfirmed, open conflicts, Jira needing
  attention, done this week. Row 6 has the detail under each.
- Rows 10–19: **Needs you**, worst first. Column J is the command to run.
- Rows 23–32: **Jira needing attention**, worst first. Column K is the command.
- Rows 36–44: pipeline by stage.
- Rows 49–56: done this week.
