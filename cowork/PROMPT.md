# Rebuild the command center in Cowork

Attach `command-center.html` and paste this. It is one small file (no build step), so a refresh costs one Jira query and one file write. The weekly status and the by-function report compute from the same data; the page does not keep past weeks, so save each week's copied status where your team keeps records.

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
4. Then give me the weekly status exactly as the page's "Copy for email /
   Teams" button would produce it (overall and the three ratings, updated
   this week, going live in 30 days, risks and blockers, decisions needed,
   asks of owners), followed by any issues not placed (no stage).
Do not ask me for an API token. Do not invent values for empty fields.
```

## Or: a Refresh button on your laptop

With an API token, run the helper and open the page it serves. It pulls on
open, and **Refresh from Jira** pulls again. The token stays in your
environment; the page never sees it.

```
export JIRA_SITE=https://yourbank.atlassian.net
export JIRA_EMAIL=you@yourbank.com JIRA_API_TOKEN=...    # Cloud
# or: export JIRA_PAT=...                                # Data Center
export JIRA_JQL='project = <KEY> ORDER BY key'
python3 cowork/serve.py                                   # open http://127.0.0.1:8765
```

Needs Python 3.8+ and `build_portfolio.py` one folder up; nothing to install.
It listens on your machine only. Don't run it on a shared server: anyone who
can reach it would read Jira as you.

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
