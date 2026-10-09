# Rebuild the command center in Cowork

Attach `command-center.html` and paste this. It is one small file (no build step), so a refresh costs one Jira query and one file write.

```
Refresh my AI portfolio command center from Jira.

1. Run this JQL through the Jira connector, all pages:
   project = <KEY> ORDER BY key
   Fields: summary, status, assignee, reporter, components, labels, duedate,
   created, updated, fixVersions, issuelinks, Story Points, Flagged.
   Keep each issue exactly as returned (key + fields). If Story Points or
   Flagged come back under customfield ids other than customfield_10016 /
   customfield_10021, tell me the ids.
2. Cut every person object down to {displayName}. Drop accountId, email, avatars.
3. In command-center.html, replace `const JIRA = null;` with
   `const JIRA = {"issues": [...]};` and give me the file back.
4. Then summarize in under 10 lines: issues not placed (no stage),
   the NOW items from "Ask this week", and the owner with the longest chase list.
Do not ask me for an API token. Do not invent values for empty fields.
```

## The Jira conventions it reads (no custom fields, no admin)

| Need | Put it in Jira as |
|---|---|
| Stage | label `stage-intake` … `stage-value` (or a status named for the stage) |
| Sponsor | Reporter |
| Function | Component |
| Gate due date | Due date |
| Go-live | Fix version with a release date |
| Dependency | Link "is blocked by" |
| Blocked | Flag the issue |
| Impact | `impact-revenue` `impact-cost` `impact-cycle-time` `impact-risk` `impact-insight` |
| Data / tech readiness | `data-ready` `data-partial` `data-unavailable` / `tech-ready` `tech-partial` `tech-not-ready` |
| Metric, baseline | `metric-defined`, `baseline-set` |
| Risk | `npi` `reg-report` `no-human-review` |

What each stage requires, the questions it asks, and the review windows are in the `RULES` block at the top of the script. Edit them there.
