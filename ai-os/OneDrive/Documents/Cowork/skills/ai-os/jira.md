# Jira protocol

Jira is the system of record for use cases. The Use Cases sheet is a
read-only snapshot of it; every dashboard tab computes from that snapshot.
You never write to Jira.

## refresh dashboard

### Path A: Copilot connector (preferred)

1. Read Config: JiraProjects (B6), JiraScope (B7), and the **field map**
   (J27:L49), which names the Jira field behind each Use Cases column.
2. Search the Jira connector for the issues JiraScope describes. For each,
   collect every field in the field map.
3. **Check the pull before you write it.** The connector is a search index,
   not a live query, so it can miss issues, lag, or leave out custom fields.
   - Fewer issues than last time (Config B22) by more than 10%, or a
     previously open key missing without a reason: stop, list the missing
     keys, and ask whether to write anyway or use a CSV export.
   - `Updated` or `Target` missing for most issues: don't write; health and
     freshness would be wrong. Say which fields came back empty and suggest
     Path B. Custom fields are the usual gap.
4. Clear the Use Cases input columns **A–W** from row 2 down. Leave the
   header and the grey formula columns untouched.
5. Write one row per issue from row 2, columns A–W as in `workbook.md`:
   - Multi-value fields (Risk flags, Impact) pipe-separated, using the exact
     words `NPI`, `Reg report`, `No human review` and `revenue`, `cost`,
     `cycle`, `risk`, `insight`.
   - Yes/no fields as `Y` or blank. Data ready as `ready`, `partial`, `none`
     or blank.
   - Outcome only for `Declined` / `Transferred` resolutions.
   - Topic = the Topics slug whose Use cases column names the key or a label.
6. Write Config B20 SnapshotAt = now, B21 SnapshotSource, B22 SnapshotCount.
7. Read Home and reply in four lines: use case count; overdue / at risk /
   stale; gates critical; any status that came back `Unmapped` (propose a
   stage for each; don't change Config yourself).

### Path B: CSV export (no connector, missing custom fields, or a short pull)

1. Find the newest `.csv` in `Documents/AI-OS/Jira-export/`. If there isn't
   one, tell me how to make it: in Jira, open the saved filter for the
   project, Export > Export CSV (all fields), save it to that folder.
2. Map columns using the field map. Jira repeats multi-value columns
   (Labels, multi-selects); join them with ` | `. Convert Jira's dates to
   real dates.
3. Then steps 4–7 above, with SnapshotSource = `CSV: <file name>`.
4. If the export is more than a day old, say so.

Replacing the Use Cases sheet is the one exception to append-only: it is a
snapshot of another system, and OneDrive version history keeps every pull.

## what's stale in Jira

From the Use Cases sheet: every use case whose Freshness is `Stale` or
`Aging`, worst first, as key, use case, stage, owner, days since update vs
the stage's cadence. If the snapshot is older than Config B15 days, say
that first and offer to refresh.

## draft Jira update for <KEY>

1. Read the use case's row (or set the Use Case tab to it), every Inventory
   row with that key in column J, and its Done rows.
2. Write a short status comment: stage and health, what the gate needs
   (the "What the gate needs" column), what's done since the last update,
   what's blocking it and who owns the unblock, any open decision with its
   INV ID. No customer data.
3. Save it to `Drafts/Jira-<KEY>-<YYYY-MM-DD>.docx` and show it to me.
4. Do not post it. Say: "Draft saved. Post it in Jira yourself when it's right."

## Rules
- Never create, edit, transition, assign or comment on a Jira issue, even
  if a tool lets you. If I ask, draft it and tell me it's a draft.
- Never put Jira credentials or tokens anywhere.
