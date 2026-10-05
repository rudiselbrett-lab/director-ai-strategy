# Integrity under change

## move <file> to <folder>

1. Show me the move: from, to. Wait for yes.
2. Before moving, find every reference to the old path: Topics column G,
   People, Answers column F, Changes, other topic docs in `Topics/`, and any
   draft in `Drafts/`.
3. Move the file. Update each reference you found (showing me the
   before/after for anything outside the logs). Log rows are never edited:
   if a log row points at the old path, leave it, because the Changes row
   is the forwarding address.
4. Append to Changes: Date, What changed, From, To, References updated,
   Approved by (me).

## check integrity

Read the workbook and report problems in this order. Don't fix anything
yourself. Propose the correcting row for each.

1. **Possible customer data or secrets**: anything resembling an account,
   card or SSN number (long digit strings), a customer's name, an email
   address outside the company, or a token or password. Highest priority.
2. **Privacy leaks**: rows that read like 1:1 or performance content
   ("1:1", "performance", "comp", "feedback on <person>").
3. **Broken references**: `Confirmed` / `Resolved` / `Conflict` rows with
   no Ref, or a Ref to an ID that doesn't exist; `Reuse` rows whose Ref isn't
   a Q ID.
4. **Duplicate IDs** on Inventory or Answers.
5. **Bad values**: Type, Channel, Confidence or Kind not on the allowed
   list; dates stored as text; dates in the future.
6. **Unmapped Jira statuses**: Jira rows whose Stage is `Unmapped`, with a
   proposed stage for each.
7. **Unknown topics**: Topic values not on the Topics sheet.
8. **Stale snapshot**: Jira snapshot older than the Config limit.
9. **Formula damage**: any grey (computed) cell that holds a typed value
   instead of a formula, or an error value.

Finish with a one-line verdict: "Clean" or "N issues, M need you."
