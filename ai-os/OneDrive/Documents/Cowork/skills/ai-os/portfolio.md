# Portfolio questions

The Portfolio, Gates and Use Case tabs answer these. Read them; don't
recompute. If a number on a tab looks wrong, say so and point at the input
row that drives it rather than overriding it.

## show <KEY>

1. Write the key into `Use Case!E5` (the only dashboard cell you may write).
2. Read the tab and reply with:
   - **One line:** stage, health (days to target), freshness, tier and its
     clock, capacity position.
   - **Gate:** the eight-gate strip in words ("Intake, Triage, Discovery
     passed; Design Critical: awaiting MRM model designation; gate owner
     Model Risk & Monitoring").
   - **Open items:** Inventory rows on it that are still Open or Unconfirmed.
   - **Next:** the next forum and the one thing that would move it.
3. Offer the matching command: `draft Jira update for <KEY>`.

## what fits this quarter

Read Portfolio › What starts next. Reply with:

- Committed and open points (from the line above the list).
- The ranked candidates that **Fit**, in order, with WSJF and size.
- The first one **Below line**, and what it would take to fit it: how many
  points would have to come free, or which committed item would have to
  finish. Don't suggest skipping it for a smaller one below; the cut is
  strict by design.

## How the tabs compute (so you can explain them)

- **Health:** against the target date of the current stage. Overdue once it
  passes; At risk inside the stage's at-risk window (Config stages, column C).
- **Freshness:** Aging past one stage cadence without an update, Stale past
  two (Config stages, column B).
- **Tier:** High if it carries `Reg report` or `No human review`, or sits in
  a high-tier function; Medium if it has any risk flag or revenue impact;
  else Low. Never typed, so it can't be negotiated.
- **Tier clock:** opened-to-today against the tier's promise, only while the
  use case is short of Approval.
- **Gate:** graded only at the stage the use case is in. Earlier gates read
  Passed; later ones Pending.
- **Capacity:** Delivery and Value consume points. Scored candidates are
  ranked by WSJF; the running total decides Fits vs Below line.
- **Weekly Status RAG:** Flow by overdue count (0 Green, 1–2 Amber, 3+
  Red); Value by realized/projected over closed quarters (90%+ Green, 75%+
  Amber); Risk and controls Amber if anything is held at the Design gate.
