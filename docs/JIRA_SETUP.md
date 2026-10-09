# Putting real Jira data on the board

The page never talks to Jira and never holds a credential. Something with
Jira access pulls the issues, the page maps them through `JIRA_MAP`, and the
**Data check** on the Jira tab says exactly what did not map. Three routes in,
one mapper:

| Route | Who runs it | Credential | Good for |
|---|---|---|---|
| `build_portfolio.py --jira` | you, a scheduled job | `JIRA_EMAIL` + `JIRA_API_TOKEN` (Cloud) or `JIRA_PAT` (Data Center), from the environment | A refreshed page on a schedule |
| An agent with the Jira MCP | Cowork, Claude, Copilot | The MCP's own OAuth | Ad hoc refresh, no token handling at all |
| **Load a Jira export** on the page | anyone | none (their Jira session) | Checking the mapping on day one |

## Why not paste an API key into the page

Two reasons, either one enough. Jira Cloud does not answer cross-origin calls
from a static page, so it would not work. And a token in a browser page is a
token in a file that gets forwarded, which no bank InfoSec review will pass.
The token lives in the environment of whatever does the pull; the page only
ever sees issues.

## Day one: check the mapping in ten minutes, no token

1. In a browser already signed in to Jira, open
   `https://<site>/rest/api/3/search/jql?jql=<your JQL, URL-encoded>&fields=*all&expand=names&maxResults=100`
   (Data Center: `/rest/api/2/search?...` with the same parameters).
2. Save the JSON. Open the dashboard, Jira tab, **Load a Jira export**.
3. Read the Data check. Every field it marks *Not found* or *Empty*, and every
   status it says is unmapped, is a line to change in `JIRA_MAP`.

The file is read in that tab only. Nothing is uploaded or stored. One browser
request returns at most 100 issues; past that, use one of the other routes.

## The field contract

The default `JIRA_MAP` needs **no custom fields and no admin change**. It reads
fields every Jira has, and a labels convention for the rest. Anyone who can
edit an issue can apply a label; a custom field is a change request.

### Standard fields

| Board field | Jira field | Notes |
|---|---|---|
| id, name, owner | Key, Summary, Assignee | |
| opened, lastUpdate | Created, Updated | Issues without Created are left off |
| stage | Status via `stages`, overridden by a `stage-*` label | See below |
| closed | Status category Done or `doneStatuses`, with Resolution | |
| func | Components (the first one) | Must match `TIER_FUNCS` spelling for credit, collections, payments, fraud |
| sponsor | Reporter | An approximation: the person who filed it. Map a real sponsor field when you have one |
| size | Story Points, or Story point estimate (team-managed) | The first that is filled in |
| target | Due date | Missing: last update + stage review window, flagged |
| live | Fix versions, latest release date | Ship through Jira releases and the roadmap fills itself |
| dependsOn | Linked issues, Blocks / Depends, "is blocked by" | |
| waitingOn | Flagged | Shows as "Flagged in Jira" |

### Labels convention

| Board field | Labels |
|---|---|
| stage | `stage-intake` `stage-triage` `stage-discovery` `stage-design` `stage-approval` `stage-delivery` `stage-scale` `stage-value` |
| impact | `impact-revenue` `impact-cost` `impact-cycle-time` `impact-risk` `impact-insight` |
| risk | `npi` `reg-report` `no-human-review` |
| dataReady | `data-ready` `data-partial` `data-unavailable` |
| techReady | `tech-ready` `tech-partial` `tech-not-ready` |
| metric, baseline | `metric-defined`, `baseline-set` |
| pattern | `pattern-<anything>`, e.g. `pattern-document-extraction` reads as "Document extraction" |

The stage label is what makes a stock **To Do / In Progress / Done** workflow
usable: the status says whether work is moving, the label says which gate it
is at. If your project already has a workflow status per stage, list them in
`stages` and drop the labels. Where both exist, the label wins.

Labels that are not in the map are ignored, so teams can keep their own.

### What has no standard home

WSJF, estimated annual value, realized value, a named sponsor, the waiting-on
text, the next step and a close reason. With the default map these are off,
and the Data check says what goes dark: no WSJF means no ranked backlog and no
capacity line; no estimate or realized value means an empty benefits panel.
That list is the change request, scoped and justified by what it unlocks.
[`jira_map.custom-fields.json`](jira_map.custom-fields.json) is the map once
those fields exist:

```
python3 build_portfolio.py --jira-map docs/jira_map.custom-fields.json --jira
```

## Editing JIRA_MAP

```
python3 build_portfolio.py --write-jira-map jira_map.json   # dump it
# edit: site, jql, stages, fields
python3 build_portfolio.py --jira-map jira_map.json --jira-file export.json
```

- **Fields** are named as Jira shows them, or by id. A list (`["Story Points",
  "Story point estimate"]`) takes the first one that is filled in. If two fields share a name (two
  "Story Points" is common) the Data check says so and uses the filled-in one;
  put the `customfield_NNNNN` id in to pin it.
- **values** maps Jira's option text or label to the board's keys; **prefix**
  takes any label starting with it. An option with no
  entry is ignored and reported. Labels with no entry are ignored silently,
  since labels carry everything a team ever tagged.
- **scale** converts units: if Estimated Annual Value is held in dollars, set
  `"scale": 0.001` to get the board's $K.
- **stages** maps every in-flight status to a lifecycle stage. A status not in
  it keeps its issues off the board, and the Data check and the build both name
  it. Use `--strict` in a scheduled job to fail instead.
- **TIER_FUNCS** (in the page, not the map) lists the functions that are high
  tier whatever their flags. The Data check lists every function it saw against
  it; if your credit function is spelled differently in Jira, fix it there.
- **includeText** is off by default. With it on, descriptions and the last
  three comments are copied into the page. Leave it off unless the page stays
  inside the same access boundary as the Jira project: a file does not inherit
  Jira's issue security.
- **includeChangelog** pulls status history so a closed issue is filed at the
  stage it stopped at. Only status moves are kept.

## The live pull

```
export JIRA_SITE=https://yourbank.atlassian.net
export JIRA_EMAIL=you@yourbank.com JIRA_API_TOKEN=...      # Cloud
# or: export JIRA_PAT=...                                  # Data Center / Server
python3 build_portfolio.py --jira --jira-map jira_map.json -o portfolio.html
```

Behind a TLS-inspecting proxy, set `SSL_CERT_FILE` to the bank's CA bundle.
Only the mapped fields are requested, and people are cut to display names
before anything is written, so account ids and emails never land in the file.

## What does not come from Jira

Realized value by quarter, decision counts and cycle-time history live in
`TRENDS`, maintained by whoever runs the Council. With real data and no
history, those panels say so and the Value rating shows *Not measured* rather
than green. Weekly reports issued from real data accumulate in
`STATUS_HISTORY`.
