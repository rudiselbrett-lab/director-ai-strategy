# start my day

The morning pass. Aim for one screen of output.

1. **Freshness.** Read Config B15 (snapshot age) against B14. If the Jira
   snapshot is stale or missing, run `refresh dashboard` (see `jira.md`)
   first. If the refresh fails its checks, carry on with the old snapshot
   and say so at the top.
2. **Needs you.** Read Dashboard rows 10–19 and 23–32. List the critical
   and warning items, worst first, each with its ID and the command from the
   "Say this" column. Skip `On track` items unless there are fewer than three
   others.
3. **Today.** Read today's calendar. For each meeting that matches a topic
   (by name, attendee or forum on the Topics sheet), list the open
   Inventory items for that topic and offer `prep for <meeting>`.
4. **Sweep.** Look through my email and Teams since the last working day for:
   - decisions someone made or asked for,
   - new facts about a topic on the Topics sheet,
   - things I finished (sent a deliverable, got a sign-off).

   Don't log any of it yet. List each as a proposed row: type, topic,
   summary, from, channel, confidence. Ask "Log these?" and accept "yes",
   "no", or a list of numbers. Skip anything from a 1:1 or anything
   personal.
5. **Nudge.** If nothing has gone on the Done sheet in the last three
   working days, say so in one line.

## Output format

```
Jira snapshot: <time> (<source>)

NEEDS YOU
1. [Critical] INV-0007 complaint-triage: decision open 11 days → decide INV-0007: <outcome>
2. ...

JIRA
1. [Critical] AIUC-103 Fraud alert prioritization: flagged → draft Jira update for AIUC-103

TODAY
- 10:00 AI Council: 3 open items on council, fraud-alerts → prep for AI Council?

PROPOSED LOG ENTRIES
1. Decision · vendor-copilot · ... · S. Ruiz · Email · Confirmed
Log these?
```

## When this runs on a schedule

If this runs as a scheduled prompt and I'm not there to answer, do steps 1–3
and 5, and list the step 4 proposals. Don't log anything until I reply.
