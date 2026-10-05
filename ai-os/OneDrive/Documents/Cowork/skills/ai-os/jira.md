# Jira protocol

Jira is the system of record for use cases. The Jira sheet is a read-only
snapshot of it, so the Dashboard can compute stage, staleness and health.
You never write to Jira.

## refresh dashboard

### Path A: Copilot connector (preferred)

1. Read Config: JiraProjects (B6) and JiraScope (B7).
2. Search the Jira connector for the issues JiraScope describes. For each
   issue you need: key, summary, status, issue type, priority, assignee,
   created, updated, due date, labels, and whether it is flagged.
3. **Check the pull before you write it.** The connector is a search index,
   not a live query, so it can miss issues or lag. Compare with the previous
   snapshot (Config B19 SnapshotCount and the keys on the Jira sheet):
   - Fewer issues than last time by more than 10%, or any previously open
     key missing without a reason: stop, list the missing keys, and ask
     whether to write anyway or use a CSV export instead.
   - Missing `updated` dates: don't write. Staleness would be wrong. Say so
     and suggest Path B.
4. Clear the Jira sheet's input columns A–L from row 2 down. Leave the
   header and the grey formula columns M–T untouched.
5. Write one row per issue, starting at row 2, columns A–L as described in
   `workbook.md`. Flagged = `Y` if Jira flags it, it's an impediment, or it
   carries a `blocked` label. Topic = the Topics slug whose Jira label
   (column E) matches the key or a label; else blank.
6. Write Config B17 SnapshotAt = now, B18 SnapshotSource, B19 SnapshotCount.
7. Read the Dashboard and reply: issue count, how many need attention, and
   any status that came back `Unmapped` (propose the stage for each; don't
   change Config yourself).

### Path B: CSV export (no connector, or the connector pull failed)

1. Find the newest `.csv` in `Documents/AI-OS/Jira-export/`. If there isn't
   one, tell me how to make it: in Jira, open the saved filter for the
   project, Export > Export CSV (current fields), save it to that folder.
2. Map columns: Issue key, Summary, Status, Issue Type, Priority, Assignee,
   Created, Updated, Due date, Labels (Jira repeats this column; join them),
   Flagged. Convert Jira's date format to real dates.
3. Then steps 4–7 above, with SnapshotSource = `CSV: <file name>`.
4. If the export is more than a day old, say so.

Replacing the Jira sheet is the one exception to append-only: it is a
snapshot of another system, and OneDrive version history keeps every
previous pull.

## what's stale in Jira

Read the Jira sheet. List every issue whose Health is `Warning` or
`Critical`, worst first (the Dashboard's order), as: key, summary, stage,
assignee, days idle vs the limit, and the Why column. If the snapshot is
older than Config B14 days, say that first and offer to refresh.

## draft Jira update for <KEY>

1. Read the issue's row on the Jira sheet, every Inventory row with that key
   in column J, and the Done rows with that key.
2. Write a short status comment: where it is (stage, what's done since the
   last update), what's blocking it, what's next and who owns it, and any
   open decision with its INV ID. No customer data.
3. Save it to `Drafts/Jira-<KEY>-<YYYY-MM-DD>.docx` and show it to me.
4. Do not post it. Say: "Draft saved. Post it in Jira yourself when it's right."

## Rules
- Never create, edit, transition, assign or comment on a Jira issue, even
  if a tool lets you. If I ask, draft it and tell me it's a draft.
- Never put Jira credentials or tokens anywhere.
