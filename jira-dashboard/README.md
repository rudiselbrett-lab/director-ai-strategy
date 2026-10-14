# Jira Portfolio Dashboard

A portfolio view built from Jira. It pulls your capabilities and epics, scores each one's health from its Jira status, dates and last update, and finds what's missing. The output is one self-contained HTML page with:

- **Command center**: every open action, grouped by check or by owner. From each group you can email the owner their list, copy it as a Teams/Slack message, open the whole set in Jira's issue navigator to bulk-edit, or mark items as nudged so you can track follow-up.
- **Capabilities**: each capability's health rolled up from its epics, worst first, with epics that aren't linked to any capability listed separately.
- **All issues**: a filterable, sortable table. Every key opens the ticket in Jira, and every row opens a detail panel.
- **How it's scored**: the rules, written out, so anyone reading a red can see why it's red.

Filters apply to every tab and live in the URL, so a filtered view can be bookmarked or sent to someone ("Copy view link"). It also has CSV export (with spreadsheet formula injection blocked), print styles for a steering pack, and dark mode.

```
python3 jira_portfolio.py --sample --open      # see it on invented data first
```

## Design choices

- **The token never touches the page.** A browser page can't call Jira Cloud with an API token anyway (CORS blocks it), and a credential in an HTML file is a credential on every laptop that file reaches. The script holds the token in memory for the pull and nothing else. The page has a Content-Security-Policy that blocks all network calls, so it can't send its data anywhere.
- **Jira stays the system of record.** The page is a snapshot stamped with the time of the pull, and it warns when it's more than a day old. The dashboard never writes to Jira. Every action opens Jira (or your mail client) and a person makes the change there, so the audit trail stays in Jira under their name.
- **No date means not assessed, not green.** An epic with no due date has nothing to judge its schedule against, so it gets its own grey state.
- **A capability is as healthy as its worst open epic.** If the owner sets a RAG field, the worse of the reported and computed health wins. Anything reported greener than its dates shows up in the command center.

## Health rules

| State | When |
|---|---|
| Off track | Status is in `red_statuses`, or the issue is flagged, or it's past its due date |
| At risk | Status is in `amber_statuses`, or it's due within `at_risk_days` and still in a To Do status, or there's been no update in `stale_days` |
| Not assessed | None of the above applies, but there's no due date |
| On track | Everything else |
| Done | Jira status category is Done |

## Command center checks

Delivery risk: past due, blocked or flagged, reported health that disagrees with the data, no recent update, a capability marked done while its epics are still open.

Data hygiene: no owner, no due date, an epic not linked to a capability, a capability with no epics, no description, and any `required_fields` you configure (for example a business value or a model risk ID).

You can switch any check off with `disabled_checks`.

## Setup

Python 3.8 or newer, nothing to install.

1. **Config.** `python3 jira_portfolio.py --init-config` writes `jira_portfolio.config.json` (or copy `config.example.json`). Set `base_url`, `deployment` and `jql`.
2. **Credentials, as environment variables only:**

   | | Cloud (`*.atlassian.net`) | Data Center (self-hosted) |
   |---|---|---|
   | Variables | `JIRA_EMAIL`, `JIRA_API_TOKEN` | `JIRA_PAT` |
   | Get one | id.atlassian.com → Security → API tokens | Profile → Personal Access Tokens |

   Behind a TLS-inspecting proxy, also set `JIRA_CA_BUNDLE` to your corporate CA file.
3. **Map your fields.** `python3 jira_portfolio.py --discover` lists your issue types (with hierarchy level), statuses and custom fields, and flags the likely owner, RAG and parent-link fields. Put the ids in the config:
   - `capability_types` / `epic_types`: your issue type names.
   - `parent_field`: `parent` on Cloud. On Data Center with Advanced Roadmaps, it's the "Parent Link" custom field.
   - `owner_field`: `assignee`, or a map by type when capabilities have a named owner field, e.g. `{"Capability": "customfield_10300", "default": "assignee"}`.
   - `rag_field`, `flagged_field`, `required_fields`, `display_fields`: all optional.
   - `red_statuses` / `amber_statuses`: your workflow's status names.
4. **Build.** `python3 jira_portfolio.py --open`

Other flags: `--from-json FILE` builds from a saved pull, `--save-raw FILE` saves one, `--out FILE` sets the output path, and `--today YYYY-MM-DD` scores as of another date.

Cloud uses the current `/rest/api/3/search/jql` endpoint with token pagination. Data Center uses `/rest/api/2/search`. Both retry when rate-limited (HTTP 429).

## Running it from Cowork

Put this folder (or just `jira_portfolio.py` and your config) somewhere Cowork can see it, and **don't paste the token into the chat.** Anything typed into a conversation lives in that conversation's history. Set the variables in the environment Cowork runs commands in, or have Cowork read them from a local file outside any shared or synced folder.

A prompt that works:

> In the jira-dashboard folder, run `python3 jira_portfolio.py --discover` and help me fill in jira_portfolio.config.json for our Capability and Epic types. Then run `python3 jira_portfolio.py --open`, tell me which capabilities are off track and why, and draft a nudge to each owner with open actions.

If Cowork can't reach your Jira host (sandbox network rules or VPN), there are two ways around it:

- **Run the script on your own machine.** It's one file with no dependencies.
- **Pull with the Atlassian connector instead of a token,** if your org has enabled it. Ask Cowork to fetch the issues with the same JQL and fields, save them as `issues.json` in Jira's REST shape (`{"issues": [...]}`), then run `--from-json issues.json`. A token-less, admin-approved connector is usually an easier conversation with InfoSec than a personal API token.

## Before you use it with real data

- **Ask InfoSec about personal API tokens.** Many banks disable them on Jira Cloud or require a service account with read-only scope. If a service account is the answer, it only needs browse permission on the projects in your JQL.
- **The page contains whatever your JQL returns:** ticket titles, owner names and emails. Share it like an internal document (SharePoint or Teams with the right audience), not by public link. Don't commit it. The repo's `.gitignore` already excludes the output, your config and raw pulls.
- **"Mark nudged" is per browser** (localStorage). It's a personal follow-up tracker, not a shared record. If the team needs a shared record, log the nudge as a Jira comment instead.

## Tests

```
python3 -m unittest -v test_jira_portfolio     # scoring, parsing, pagination, escaping, CLI
node browser_check.js                          # drives the page in headless Chromium (needs playwright)
```

The browser check builds a page with a ticket whose summary tries to inject script. It then exercises every filter, sort, drawer, nudge, export and deep link, and checks that the page still has no horizontal scroll at phone width.
