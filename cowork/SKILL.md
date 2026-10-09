---
name: refresh-ai-portfolio
description: Refresh the Consumer Bank AI use case portfolio dashboard from Jira through the Jira MCP, check the mapping, and hand back the page with what did not map. Use when asked to refresh, update or rebuild the AI portfolio dashboard, or to put Jira data on it.
---

# Refresh the AI portfolio dashboard from Jira

You have: `ai-use-case-dashboard.html` (the page), `build_portfolio.py`
(optional, needs Python 3.8+), a `jira_map.json` if the user has one, and a
Jira MCP connector. You never need or ask for an API token: the MCP holds the
access.

## 1. Read the mapping

Use `jira_map.json` if present. Otherwise take `JIRA_MAP` from the page's data
block (between the `DATA BLOCK` markers). You need `jql`, `fields`,
`flagField`, `includeText` and `includeChangelog`.

## 2. Pull the issues through the MCP

- Use the MCP's JQL search tool (Atlassian's remote MCP calls it
  `searchJiraIssuesUsingJql`; find the site's `cloudId` first if it asks).
- Ask only for: `summary, status, assignee, created, updated, duedate,
  resolution, resolutiondate, labels`, the `flagField`, and every field named
  in `fields` (an entry may be a list of alternatives; ask for all of them).
  The default map uses only standard fields and labels, so expect no
  `customfield_` ids beyond Story Points and Flagged. Add `description, comment` only if `includeText` is true.
  Request `expand: changelog` if `includeChangelog` is true and the tool allows it.
- Page until the tool says there are no more results. Do not stop at the first page.
- Keep each issue exactly as returned (`key` and `fields`). Do not reshape,
  summarize or rename anything; the page's mapper expects Jira's own JSON.

## 3. Get field names

`JIRA_MAP` names fields as Jira shows them ("Business Sponsor"). The issues
carry ids (`customfield_10102`). Include a `names` object of id to display
name: from the search response if the tool returns one (`expand: names`), else
from the MCP's field-listing tool. If neither is possible, tell the user and
offer to rewrite the `fields` entries in `jira_map.json` as `customfield_` ids.

## 4. Write the file

Write `jira_issues.json`:

```json
{ "pulledAt": "<ISO timestamp now>", "site": "<https://...>", "jql": "<the JQL>",
  "names": { "customfield_10102": "Business Sponsor", ... },
  "issues": [ ...every issue, as returned... ] }
```

## 5. Build the page

- **Python available:** `python3 build_portfolio.py --jira-file jira_issues.json [--jira-map jira_map.json] -o ai-portfolio.html`.
  This trims people to display names, drops unmapped fields, and prints a
  pre-check. Report the pre-check lines to the user verbatim.
- **No Python:** give the user the dashboard and `jira_issues.json`, and tell
  them to open the Jira tab and use **Load a Jira export**. Do not paste the
  raw JSON into the page by hand: that skips the trimming of account ids and
  emails.

## 6. Report

Lead with the counts: issues returned, issues on the board, issues left off
and why. Then every problem the pre-check or the page's Data check lists, with
the `JIRA_MAP` change that fixes each. Do not describe the portfolio's health
from the data until the user has confirmed the mapping is right; a wrong
status map makes a healthy portfolio read red.

## Rules

- Never ask for, accept or store a Jira API token or password.
- Never set `includeText` to true without the user saying so. The file does
  not inherit Jira's issue-level security.
- Never invent values for empty fields. Empty is information; the Data check reports it.
