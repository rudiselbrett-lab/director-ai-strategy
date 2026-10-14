# Jira Portfolio Dashboard

A portfolio view and weekly status report built from Jira. It pulls your capabilities and epics, scores each one's health from its Jira status, dates and last update, and finds what's missing. Each run produces two things:

- **A dashboard:** one self-contained HTML page.
- **The week's report as Markdown,** ready to paste into Teams, Outlook or Confluence.

```
python3 jira_portfolio.py --sample --open      # see it on invented data first
```

## What's on the page

| View | What it answers |
|---|---|
| **Overview** | Where does the portfolio stand, and where are the gaps? A stat band (open capabilities, open epics, and counts on track, at risk, off track and not assessed), plus these charts: capability health, pipeline by Jira status, what's due in the next eight weeks (with a **No date** column), **what's missing** (each field filled against empty), open work by owner (with **No owner**), and **time in current status**. The **Trends** section has health week by week, **completeness week by week**, completions per month, and cycle time from created to done. Every chart has a one-line takeaway that says what it shows. |
| **Weekly report** | What happened this week, what didn't, and what does leadership need to do about it? An overall RAG and three rated elements (schedule, momentum, data quality), then six sections: what changed, **what didn't move**, what we need to know, what needs a decision, what's coming up (including **work with no date**), and **what's missing**. Earlier weeks are kept. You can copy it for email or Teams with links intact, download it as Markdown, or print it to PDF. |
| **Actions** | What needs fixing, and by whom? Grouped by check or by owner. From any group you can email the owner their list, copy it as a Teams message, open the set in Jira's issue navigator to bulk-edit, or mark items nudged. |
| **Capabilities** | Each capability's health, rolled up from its epics, worst first. Expand one to see its epics. Epics that aren't linked to any capability are listed separately. |
| **Issues** | Everything in a filterable, sortable table. Every key opens the ticket in Jira, and every row opens a detail panel. There's a CSV export with spreadsheet formula injection blocked. |
| **Method** | The scoring rules, written out, so anyone reading a red can see why it's red. |

Filters apply to every view except the report and the trends. They live in the URL, so a filtered view can be bookmarked or shared.

## Showing the white space

A board that only reports activity hides the work nobody has done. So absence is drawn the same way everywhere, as a hatched fill in charts and a dashed marker in tables ("No date", "No owner", "Not linked"). Each view pairs what was done with what wasn't:

| Done | Not done, shown alongside |
|---|---|
| Due in the next eight weeks | **No date**: work that can't be scheduled at all |
| Open work by owner | **No owner**: work nobody is accountable for |
| Capability health | **No epics**: capabilities with nothing under them |
| What changed this week | **What didn't move**: not started, blocked or on hold for `stuck_weeks`+ weeks, and anything with no update in `stale_days` |
| Coming up | **No date set, so it can't be scheduled** |
| Data quality score | **What's missing**: every open item without an owner, a capability, epics, a description or a required field, plus a completeness trend |

Long-running work that is actively in progress isn't flagged as stuck. An epic can reasonably be In Progress for months. What counts as not moving is work that hasn't started, or is held.

## The weekly report runs itself

A single Jira pull has no history, so each run saves a dated snapshot of the scored portfolio to `history_dir`. The report compares this week's snapshot with the one from about a week earlier. That's how it knows:

- what was completed or added
- what went off track or came back
- which statuses, due dates and owners moved

**Schedule it once and the report produces itself.** Run the script weekly, for example Monday at 7:45. Each run writes the dashboard, the week's `weekly-report-YYYY-MM-DD.md`, and the next snapshot.

- **Windows Task Scheduler:** action `python`, arguments `C:\path\jira_portfolio.py --out C:\path\portfolio.html`, start in the folder that holds your config.
- **macOS or Linux cron:** `45 7 * * 1 cd ~/ai-portfolio && python3 jira_portfolio.py`
- **Cowork scheduled task:** "Every Monday at 7:45, run `python3 jira_portfolio.py` in my ai-portfolio folder, then draft an email to my leadership team with the contents of this week's weekly-report file."

Keep `history_dir` somewhere permanent, like Documents. If it lives in a temp or sandbox folder that gets wiped, the report loses last week and falls back to its first-run mode.

**On the first run** there's nothing to compare against. "What changed" then comes from Jira's created and resolved dates, and the status, date and owner moves start appearing from the second weekly run.

The three elements are rated like this:

| Element | Red | Amber | Green |
|---|---|---|---|
| Schedule | any capability off track | any capability at risk | otherwise |
| Momentum | 25%+ of open work stale | anything stale, or nothing completed | otherwise (the text also counts what didn't move) |
| Data quality | under 75% of open items complete | 75–89% | 90%+ |

Overall takes the worst of the three, and the headline names which element is the constraint.

## Health rules

| State | When |
|---|---|
| Off track | Status is in `red_statuses`, or the issue is flagged, or it's past its due date |
| At risk | Status is in `amber_statuses`, or it's due within `at_risk_days` and still in a To Do status, or there's been no update in `stale_days` |
| Not assessed | None of the above applies, but there's no due date. It isn't shown as green, because there's nothing to judge its schedule against |
| On track | Everything else |
| Done | Jira status category is Done |

A capability is as healthy as its worst open epic. If owners set a RAG field, the worse of the reported and computed health wins, and anything reported greener than its dates becomes an action.

## Design choices

- **The token never touches the page.** The script holds it in memory for the pull, and only then. The page has a Content-Security-Policy that blocks every network call, so it can't send its data anywhere.
- **Jira stays the system of record.** The page is a snapshot stamped with the time of the pull, and it warns when it's more than a day old. The dashboard never writes to Jira. Every action opens Jira or your mail client, so changes are made by a person and the audit trail stays in Jira.
- **Trends only use what's real.** The charts read your Jira fields and saved snapshots. The interview mock's value-realized and WSJF capacity charts are left out on purpose. They need fields most Jira instances don't carry, and a chart built on guessed numbers is worse than no chart. If your capabilities do carry value or WSJF fields, they're a small addition.

## Setup

Python 3.8 or newer, nothing to install.

1. **Config.** `python3 jira_portfolio.py --init-config` writes `jira_portfolio.config.json`, or you can copy `config.example.json`. Set `base_url`, `deployment`, `jql` and `history_dir`.
   - Include recently resolved work in the JQL, e.g. `AND (statusCategory != Done OR resolved >= -180d)`. The completions and cycle-time charts need it.
2. **Credentials, as environment variables only:**

   | | Cloud (`*.atlassian.net`) | Data Center (self-hosted) |
   |---|---|---|
   | Variables | `JIRA_EMAIL`, `JIRA_API_TOKEN` | `JIRA_PAT` |
   | Get one | id.atlassian.com → Security → API tokens | Profile → Personal Access Tokens |

   Behind a TLS-inspecting proxy, also set `JIRA_CA_BUNDLE` to your corporate CA file.
3. **Map your fields.** `python3 jira_portfolio.py --discover` lists your issue types, statuses and custom fields, and flags the likely owner, RAG and parent-link fields. Put the ids in the config:
   - `capability_types` / `epic_types`: your issue type names.
   - `parent_field`: `parent` on Cloud. On Data Center with Advanced Roadmaps, it's the "Parent Link" custom field.
   - `owner_field`: `assignee`, or a map by type, e.g. `{"Capability": "customfield_10300", "default": "assignee"}`.
   - `rag_field`, `flagged_field`, `required_fields`, `display_fields`: all optional.
   - `red_statuses` / `amber_statuses`: your workflow's status names.
4. **Build.** `python3 jira_portfolio.py --open`

Other flags:

| Flag | What it does |
|---|---|
| `--from-json FILE` | build from a saved pull |
| `--save-raw FILE` | save the pull |
| `--out FILE` | dashboard path |
| `--report FILE` | report path |
| `--no-history` | don't read or write snapshots |
| `--today YYYY-MM-DD` | score as of another date |

Cloud uses `/rest/api/3/search/jql` with token pagination. Data Center uses `/rest/api/2/search`. Both retry when rate-limited.

## Running it from Cowork

Put this folder somewhere Cowork can see it, and **don't paste the token into the chat.** Anything typed into a conversation lives in its history. Set the variables in the environment Cowork runs commands in, or keep them in a local file outside any synced folder.

> In my ai-portfolio folder, run `python3 jira_portfolio.py --discover` and help me fill in jira_portfolio.config.json for our Capability and Epic types. Then run `python3 jira_portfolio.py --open`, summarize this week's report, and draft a nudge to each owner with open actions.

If Cowork can't reach your Jira host (sandbox network rules or VPN), there are two ways around it:

- **Run the script on your own machine.**
- **Use the Atlassian connector,** if your org has enabled it. Have Cowork fetch the issues with the same JQL and fields, save them as `issues.json` in Jira's REST shape (`{"issues": [...]}`), then run `--from-json issues.json`. A token-less, admin-approved connector is usually an easier conversation with InfoSec than a personal API token.

## Before you use it with real data

- **Ask InfoSec about personal API tokens.** Many banks disable them on Jira Cloud or require a read-only service account. A service account only needs browse permission on the projects in your JQL.
- **The page, the report and the snapshots contain whatever your JQL returns:** ticket titles, owner names and emails. Share them like internal documents (SharePoint or Teams with the right audience), never by public link, and don't commit them. The repo's `.gitignore` already excludes the output, your config, raw pulls, reports and history.
- **"Mark nudged" is per browser** (localStorage). It's a personal follow-up tracker, not a shared record. If the team needs a shared record, log the nudge as a Jira comment.

## Tests

```
python3 -m unittest -v test_jira_portfolio     # scoring, history, weekly report, trends, pagination, escaping, CLI
node browser_check.js                          # drives every view in headless Chromium (needs playwright)
```

The browser check builds two pages:

- **The sample,** with its eight-week history.
- **A page from a saved pull,** run a week apart so the history is real, with a ticket whose summary tries to inject script.

It then exercises every chart, filter, sort, report week, action, drawer, export and deep link. It also checks every view at phone width in light and dark mode, both for horizontal scroll and for leaked `null` or `[object]` text.
