# start my day

The morning pass. Aim for one screen of output.

1. **Freshness.** Read Config B23 (snapshot age) against B15. If the Jira
   snapshot is stale or missing, run `refresh dashboard` (see `jira.md`)
   first. If the refresh fails its checks, carry on with the old snapshot
   and say so at the top.
2. **Needs you.** Read Home › Needs you and Home › Use cases needing
   attention. List the critical and warning items, worst first, each with
   its ID and the command from the "Say this" column. Skip `On track` items
   unless there are fewer than three others. Add one line from the Weekly
   Status tiles: Overall, Flow, Value, Risk and controls.
3. **Today.** Read today's calendar. For each meeting that matches a topic
   (by name, attendee or forum on the Topics sheet), list the open
   Inventory items for that topic and offer `prep for <meeting>`. If it is
   one of the three sittings (Weekly Intake, Tactical Standup, Portfolio
   Council), point at that block of the Weekly Status tab.
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
1. [Critical] INV-0007 council: find a sponsor for AI-010, open 11 days → decide INV-0007: <outcome>
2. ...

Weekly status: Amber (Flow Amber · Value Green · Risk Amber)

USE CASES
1. [Critical] AI-003 Fraud alert prioritization: 3 days past its Design target, flagged → draft Jira update for AI-003

TODAY
- 10:00 Portfolio Council: 4 open decisions → prep for Portfolio Council?

PROPOSED LOG ENTRIES
1. Decision · vendor-copilot · ... · S. Ruiz · Email · Confirmed
Log these?
```

## When this runs on a schedule

If this runs as a scheduled prompt and I'm not there to answer, do steps 1–3
and 5, and list the step 4 proposals. Don't log anything until I reply.
