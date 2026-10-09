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

What the board needs from each issue. The **Minimum** column is what you need
for the board to be honest; the rest sharpens it.

| Board field | Jira source (default name) | Type | Minimum | If it is missing |
|---|---|---|---|---|
| id, name, owner | key, Summary, Assignee | system | yes | — |
| stage | Status, via `stages` | status | yes | Issue left off the board, named in the Data check |
| opened, lastUpdate | Created, Updated | system | yes | Issue left off |
| target | Stage Target Date, else Due date | date | yes | Derived as last update + stage review window, flagged |
| func | Consumer Bank function | select/text | yes | "Unassigned"; the tier cannot see where it lands |
| sponsor | Business Sponsor | user/text | yes | Intake grades it red |
| risk | Labels `npi`, `reg-report`, `no-human-review` | labels | yes | Tier reads low risk. **Check this one first.** |
| impact | Impact | multi-select | yes | Completeness drops; tier misses revenue |
| size, est, wsjf | Story Points, Estimated Annual Value ($K), WSJF | number | for ranking | Use case sits unranked, below the capacity line |
| dataReady | Data Readiness: Ready / Partial / Not available | select | from discovery | Discovery grades red |
| metric, baseline | Success Metric, Baseline Captured | text / checkbox | from triage | Triage grades red/amber |
| waitingOn | Waiting On, else the Flagged field | text | no | Flags still show as "Flagged in Jira" |
| next, closedReason | Next Step, Close Reason | text | no | Blank |
| closed | Status category Done or `doneStatuses`, with Resolution | system | — | — |

Risk flags ride on labels by default because adding a custom field to a bank's
Jira is a change request and a label is not. Jira labels cannot hold spaces,
which is why the map turns `reg-report` into "Reg report".

## Editing JIRA_MAP

```
python3 build_portfolio.py --write-jira-map jira_map.json   # dump it
# edit: site, jql, stages, fields
python3 build_portfolio.py --jira-map jira_map.json --jira-file export.json
```

- **Fields** are named as Jira shows them. If two fields share a name (two
  "Story Points" is common) the Data check says so and uses the filled-in one;
  put the `customfield_NNNNN` id in to pin it.
- **values** maps Jira's option text to the board's keys. An option with no
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
