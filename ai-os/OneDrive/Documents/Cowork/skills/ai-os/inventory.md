# Inventory protocol

Notes get captured, never applied silently. The Inventory sheet is an
append-only audit log. Each row is one piece of information, stamped with
date, person and channel, and sorted into one of three buckets:

- **What's New** (`New`): something happened.
- **What We Need to Know** (`Know`): a fact, constraint or risk that changes how we work.
- **Decision Needed** (`Decision`): someone has to choose, and it isn't me alone.

## log this: <note> / add note to <topic>: <note>

1. Classify it as New, Know or Decision. If it holds more than one item,
   split it into one row each.
2. Work out: topic (from the Topics sheet; for `add note to`, use the one I
   named), who it came from, the channel, and the date. If I didn't say who
   or how, ask in one line. Don't guess a source.
3. Confidence: `Confirmed` if I saw or heard it first-hand or it's from the
   owner of the fact. `Unconfirmed` if it's second-hand ("I heard", "apparently",
   forwarded from someone else).
4. **Check for conflict.** Search the Inventory for rows on the same topic
   that say something different. If this note contradicts an existing row,
   do not log it as New/Know. Log it as `Conflict`, Ref = the row it
   contradicts, Summary = what the two say and that the Inventory stands
   until settled.
5. **Privacy check.** If it came from a 1:1 or is about someone's
   performance or career, it goes to `Private/` instead. Tell me.
6. Append the row(s). Then, for `add note to`, append one dated line to that
   topic's notes doc (Topics sheet column G) that cites the INV ID.
7. Reply in one line: "Logged INV-0019 (Decision, fraud-alerts)."

## confirm <INV-id>

Check that the ID exists and its State is `Unconfirmed`. Append a row:
Type `Confirmed`, same Topic, Ref = the ID, From = who confirmed it,
Confidence `Confirmed`, Summary = what was confirmed and any correction.
If the confirmation changes the facts, say so in the Summary; don't edit
the original row.

## decide <INV-id>: <outcome>

Check the ID exists and is an open `Decision` or `Conflict`. Ask who made
the decision if I didn't say. Append a row: Type `Resolved`, Ref = the ID,
From = the decider, Channel where it was decided, Confidence `Confirmed`,
Summary = the outcome in one sentence ("Approved: ...", "Declined: ...",
"Deferred to <date>: ..."). Then offer: "Log this as done too?" if I drove it.

## what's open on <topic>

Read the Inventory and Jira sheets. Reply with:

1. Open decisions and conflicts on that topic, oldest first, with age.
2. Unconfirmed items, oldest first.
3. Jira issues tagged to that topic with Health not `On track` or `Closed`.
4. The last three Resolved rows on the topic, so I have the context.

Use the IDs. Keep it to one screen.

## Rules
- Never edit or delete an Inventory row. Never resolve a conflict by picking
  the newer version yourself.
- One fact per row.
- If I say "update INV-0007 to say ...", explain that the log is
  append-only and offer the right row type instead.
