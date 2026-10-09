#!/usr/bin/env python3
"""
Build the AI Use Case Portfolio dashboard.

One file, no dependencies, Python 3.8 or newer. Copy it to any machine and run
it — the page template and the sample portfolio are both embedded, so nothing
needs downloading and nothing needs installing.

    python3 build_portfolio.py
        Writes ai-use-case-portfolio.html next to this script.

    python3 build_portfolio.py --open
        Builds it and opens it in your browser.

Editing the data
----------------
    python3 build_portfolio.py --write-data portfolio.json
        Dumps the portfolio as JSON you can edit in any editor.

    python3 build_portfolio.py --data portfolio.json
        Rebuilds the page from that file.

    python3 build_portfolio.py --write-csv use_cases.csv
        Dumps just the use cases as a spreadsheet.

    python3 build_portfolio.py --csv use_cases.csv
        Rebuilds using that spreadsheet, keeping the embedded trends and
        weekly status. This is the path a Jira CSV export would take.

Real Jira data
--------------
    python3 build_portfolio.py --jira
        Pulls live. Credentials from JIRA_EMAIL + JIRA_API_TOKEN (Cloud) or
        JIRA_PAT (Data Center), never a flag. Site from JIRA_SITE.

    python3 build_portfolio.py --jira-file jira_issues.json
        Builds from a saved search response, e.g. what an agent pulled
        through the Jira MCP.

    --jira-map FILE / --write-jira-map FILE
        Swap or dump JIRA_MAP. docs/JIRA_SETUP.md covers it.

What is computed and what is stored
-----------------------------------
This script only supplies data. Health, staleness, completeness, WSJF rank,
the capacity line, suggested actions, the weekly ratings, upcoming forum
sittings and the portfolio risks are all computed in the page itself, against
the date it is opened. That is deliberate: a stored status is a status someone
has to remember to update.
"""

import argparse
import base64
import csv
import json
import os
import pathlib
import sys
import webbrowser
import zlib

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "ai-use-case-portfolio.html"

START = "/* ===== DATA BLOCK START"
END = "/* ===== DATA BLOCK END ===================================================== */"

# Order matters only for readability of the generated file.
CONSTS = ["ANCHOR", "CAPACITY", "TRENDS", "IMPACTS", "RISK_FLAGS",
          "STATUS_HISTORY", "USE_CASES", "JIRA_MAP", "JIRA_SNAPSHOT"]
# Older portfolio JSON predates the Jira constants; they default from the sample.
OPTIONAL = {"JIRA_MAP", "JIRA_SNAPSHOT"}

NOTES = {
    "ANCHOR": "The date this sample was authored. Every date below shifts by\n   (today - ANCHOR) when the page loads, so the demo keeps its shape whenever\n   it is opened. Set it to null for real data, where dates mean what they say.",
    "CAPACITY": "Delivery points available per increment. Work in delivery or\n   realization consumes it; what is left decides how far down the ranked\n   backlog we get.",
    "TRENDS": "Portfolio history for the trend panels. Value figures are $K of annual\n   run-rate.",
    "IMPACTS": "Impact categories, mirroring the intake form's Impact question.",
    "RISK_FLAGS": "Risk flags, mirroring the intake form's routing question.",
    "STATUS_HISTORY": "Previously issued weekly reports, kept as they were issued, each\n   carrying its three sittings' output. These are never recomputed —\n   re-deriving last week from this week's data would rewrite history.",
    "USE_CASES": "The portfolio. One entry per use case; one Jira issue per entry.",
    "JIRA_MAP": "How this portfolio reads out of Jira: the JQL, status to stage, and\n   which Jira field feeds each use case field. See docs/JIRA_SETUP.md.",
    "JIRA_SNAPSHOT": "Raw issues as Jira returned them, trimmed to the mapped fields. When\n   present the page builds USE_CASES from it. null = the sample.",
}

# Columns for the spreadsheet round-trip. List fields are pipe-separated.
CSV_FIELDS = ["id", "name", "func", "stage", "owner", "sponsor", "wsjf", "est",
              "size", "impact", "metric", "dataReady", "baseline", "risk",
              "waitingOn", "opened", "lastUpdate", "target", "next",
              "pattern", "techReady", "live", "realized", "dependsOn",
              "closedOutcome", "closedReason", "closedDate"]
CSV_LISTS = {"impact", "risk", "dependsOn"}
CSV_BOOLS = {"metric", "baseline"}
CSV_NUMBERS = {"wsjf", "est", "size", "realized"}


# --------------------------------------------------------------------------
# embedded assets
# --------------------------------------------------------------------------

def _unpack(blob):
    return zlib.decompress(base64.b64decode(blob)).decode("utf-8")


def load_template(path=None):
    """The page. An external file wins, so you can iterate on the design."""
    if path:
        return pathlib.Path(path).read_text(encoding="utf-8")
    sibling = HERE / "ai-use-case-dashboard.html"
    if sibling.exists():
        return sibling.read_text(encoding="utf-8")
    return _unpack(TEMPLATE_B64)


def builtin_data():
    return json.loads(_unpack(DATA_B64))


# --------------------------------------------------------------------------
# data in, page out
# --------------------------------------------------------------------------

def load_data(args):
    data = builtin_data()
    if args.data:
        loaded = json.loads(pathlib.Path(args.data).read_text(encoding="utf-8"))
        missing = [k for k in CONSTS if k not in loaded and k not in OPTIONAL]
        if missing:
            sys.exit("error: %s is missing %s" % (args.data, ", ".join(missing)))
        data = dict(builtin_data(), **loaded)
    if args.jira_map:
        data["JIRA_MAP"] = json.loads(pathlib.Path(args.jira_map).read_text(encoding="utf-8"))
    if args.jira or args.jira_file:
        jmap = data["JIRA_MAP"]
        if args.jira_file:
            issues, names, extras = read_jira_file(args.jira_file)
            snap = snapshot_from(issues, names, jmap, jql=extras.get("jql"),
                                 site=extras.get("site"), pulled_at=extras.get("pulledAt"))
        else:
            print("pulling from Jira")
            try:
                snap = fetch_jira(jmap, jql=args.jql)
            except JiraError as e:
                sys.exit("error: %s" % e)
        lines, errors = precheck(snap, jmap)
        print("jira check: " + "\n".join(lines))
        if errors and args.strict:
            sys.exit("error: --strict and %d issues would be left off the board" % errors)
        data["JIRA_SNAPSHOT"] = snap
        data["USE_CASES"] = []          # built from the snapshot in the page
        data["ANCHOR"] = None           # real dates mean what they say
        if not args.data:
            # The sample's history and issued reports describe invented work.
            data["TRENDS"] = {"value": [], "decisions": [], "cycle": []}
            data["STATUS_HISTORY"] = []
    if args.csv:
        data["USE_CASES"] = read_csv(args.csv)
        # real dates mean what they say — do not slide them
        data["ANCHOR"] = None
    return data


def read_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for n, raw in enumerate(csv.DictReader(fh), start=2):
            row = {}
            for field in CSV_FIELDS:
                value = (raw.get(field) or "").strip()
                if field in CSV_LISTS:
                    row[field] = [v.strip() for v in value.split("|") if v.strip()]
                elif field in CSV_BOOLS:
                    row[field] = value.lower() in ("true", "yes", "y", "1")
                elif field in CSV_NUMBERS:
                    if value == "":
                        row[field] = None
                    else:
                        try:
                            row[field] = float(value) if "." in value else int(value)
                        except ValueError:
                            sys.exit("error: %s line %d: %s is not a number (%r)"
                                     % (path, n, field, value))
                else:
                    row[field] = value or None
            if not row["id"]:
                sys.exit("error: %s line %d: id is required" % (path, n))
            outcome = row.pop("closedOutcome", None)
            reason = row.pop("closedReason", None)
            date = row.pop("closedDate", None)
            if outcome:
                row["closed"] = {"outcome": outcome, "reason": reason or "", "date": date or ""}
            rows.append(row)
    if not rows:
        sys.exit("error: %s has no rows" % path)
    return rows


def write_csv(path, use_cases):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for uc in use_cases:
            row = {}
            shut = uc.get("closed") or {}
            for field in CSV_FIELDS:
                if field.startswith("closed"):
                    key = field[len("closed"):].lower()
                    row[field] = shut.get(key, "") if isinstance(shut, dict) else ""
                    continue
                value = uc.get(field)
                if field in CSV_LISTS:
                    row[field] = "|".join(value or [])
                elif field in CSV_BOOLS:
                    row[field] = "true" if value else "false"
                elif value is None:
                    row[field] = ""
                else:
                    row[field] = value
            writer.writerow(row)


def to_js(data):
    """Emit the const declarations the page expects."""
    out = []
    for name in CONSTS:
        payload = json.dumps(data[name], indent=2, ensure_ascii=False)
        # a literal </script> inside a string would close the tag early
        payload = payload.replace("</", "<\\/")
        out.append("/* %s */\nconst %s = %s;" % (NOTES[name], name, payload))
    return "\n\n".join(out)


def build(template, data):
    try:
        head = template.index(START)
        tail = template.index(END)
    except ValueError:
        sys.exit("error: the template has no DATA BLOCK markers — is it the "
                 "right file?")
    return template[:head] + to_js(data) + "\n\n" + template[tail:]


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Jira: pull the issues, keep only what JIRA_MAP uses, embed them
# --------------------------------------------------------------------------
#
# The mapping from Jira fields to use cases runs in the page (JiraMapper), so
# the build, an agent with the Jira MCP and a file loaded on the page all go
# through one set of rules. This side only fetches, trims and pre-checks.
#
# Credentials come from the environment and nowhere else, never a flag, so
# they stay out of shell history and out of the page:
#
#   Jira Cloud          JIRA_EMAIL + JIRA_API_TOKEN   (REST v3, /search/jql)
#   Data Center/Server  JIRA_PAT                      (REST v2, /search)
#   both                JIRA_SITE, or "site" in JIRA_MAP
#
# Behind a corporate TLS proxy, point SSL_CERT_FILE at the bank's CA bundle;
# HTTPS_PROXY is honoured as usual.

# Fields every use case reads, whatever the mapping says.
JIRA_SYSTEM_FIELDS = ["summary", "status", "assignee", "created", "updated",
                      "duedate", "resolution", "resolutiondate", "labels"]
JIRA_TEXT_FIELDS = ["description", "comment"]
JIRA_PAGE = 100


def _field_groups(jmap):
    """Each mapped field as its list of alternatives, e.g. ["Story Points",
    "Story point estimate"]. A group is missing only if none resolves."""
    groups = []
    for spec in (jmap.get("fields") or {}).values():
        if isinstance(spec, dict):
            spec = spec.get("field")
        alts = [r for r in (spec if isinstance(spec, list) else [spec]) if r]
        if alts:
            groups.append(alts)
    if jmap.get("flagField"):
        groups.append([jmap["flagField"]])
    return groups


def _missing(jmap, names):
    """Mapped fields with no alternative in this Jira, as display text."""
    out = []
    for alts in _field_groups(jmap):
        _, unresolved = _resolve(alts, names)
        if len(unresolved) == len(alts):
            out.append(" or ".join(repr(a) for a in alts))
    return out


def _field_refs(jmap):
    """Every field name or id JIRA_MAP points at."""
    refs = []
    for spec in (jmap.get("fields") or {}).values():
        if isinstance(spec, dict):
            spec = spec.get("field")
        # a field may list alternatives, e.g. ["Story Points", "Story point estimate"]
        for ref in (spec if isinstance(spec, list) else [spec]):
            if ref and ref not in refs:
                refs.append(ref)
    if jmap.get("flagField"):
        refs.append(jmap["flagField"])
    return refs


def _resolve(refs, names):
    """Names or ids -> the ids in this Jira. A name two fields share keeps
    both; the page picks the one that is filled in and says so."""
    by_name = {}
    for fid, name in names.items():
        by_name.setdefault(str(name).strip().lower(), []).append(fid)
    ids, unresolved = [], []
    for ref in refs:
        if ref in names or ref in JIRA_SYSTEM_FIELDS:
            hits = [ref]
        else:
            hits = by_name.get(str(ref).strip().lower(), [])
        if not hits:
            unresolved.append(ref)
        for h in hits:
            if h not in ids:
                ids.append(h)
    return ids, unresolved


def _slim_user(v):
    """People keep their display name. Account ids, emails and avatars are
    not needed to draw the board and do not belong in a file that travels."""
    if isinstance(v, dict) and "displayName" in v:
        return {"displayName": v.get("displayName")}
    if isinstance(v, list):
        return [_slim_user(x) for x in v]
    return v


def _slim_issue(issue, keep, include_text):
    fields = issue.get("fields") or {}
    out = {}
    for fid in keep:
        if fid not in fields:
            continue
        v = fields[fid]
        if fid == "status" and isinstance(v, dict):
            cat = v.get("statusCategory") or {}
            v = {"name": v.get("name"), "statusCategory": {"key": cat.get("key")}}
        elif fid == "resolution" and isinstance(v, dict):
            v = {"name": v.get("name")}
        elif fid == "fixVersions" and isinstance(v, list):
            v = [{"name": x.get("name"), "releaseDate": x.get("releaseDate"),
                  "released": x.get("released")} for x in v if isinstance(x, dict)]
        elif fid == "components" and isinstance(v, list):
            v = [{"name": x.get("name")} for x in v if isinstance(x, dict)]
        elif fid == "issuelinks" and isinstance(v, list):
            v = [{"type": {"name": (l.get("type") or {}).get("name")},
                  **{side: {"key": (l.get(side) or {}).get("key")}
                     for side in ("inwardIssue", "outwardIssue") if l.get(side)}}
                 for l in v]
        elif fid == "comment" and isinstance(v, dict):
            v = {"comments": [{"author": _slim_user(c.get("author")),
                               "created": c.get("created"), "body": c.get("body")}
                              for c in (v.get("comments") or [])[-3:]]}
        else:
            v = _slim_user(v)
        out[fid] = v
    if not include_text:
        for fid in JIRA_TEXT_FIELDS:
            out.pop(fid, None)
    slim = {"key": issue.get("key"), "fields": out}
    hist = (issue.get("changelog") or {}).get("histories") or []
    status_moves = []
    for h in hist:
        items = [{"field": "status", "fromString": i.get("fromString"), "toString": i.get("toString")}
                 for i in (h.get("items") or []) if i.get("field") == "status"]
        if items:
            status_moves.append({"created": h.get("created"), "items": items})
    if status_moves:
        slim["changelog"] = {"histories": status_moves}
    return slim


def snapshot_from(issues, names, jmap, jql=None, site=None, pulled_at=None):
    """Trim raw issues to what the mapping uses and wrap them for the page."""
    # Resolve against what the issues carry as well as the names map: an MCP
    # response may come without names, and system fields go by their ids.
    present = {k: k for i in issues for k in (i.get("fields") or {})}
    ids, _ = _resolve(_field_refs(jmap), dict(present, **names))
    keep = JIRA_SYSTEM_FIELDS + ids + (JIRA_TEXT_FIELDS if jmap.get("includeText") else [])
    slim = [_slim_issue(i, keep, jmap.get("includeText")) for i in issues if i.get("key")]
    used = {k for i in slim for k in i["fields"]}
    return {
        "pulledAt": pulled_at,
        "site": site or jmap.get("site"),
        "jql": jql or jmap.get("jql"),
        "names": {k: v for k, v in names.items() if k in used},
        "issues": slim,
    }


def read_jira_file(path):
    """A search response, several pages of them, a bare list of issues, or a
    snapshot this script wrote. Returns (issues, names, extras)."""
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        if data and isinstance(data[0], dict) and isinstance(data[0].get("issues"), list):
            issues, names = [], {}
            for page in data:
                issues += page["issues"]
                names.update(page.get("names") or {})
            return issues, names, {}
        return data, {}, {}
    if isinstance(data, dict) and isinstance(data.get("issues"), list):
        extras = {k: data.get(k) for k in ("pulledAt", "site", "jql") if data.get(k)}
        return data["issues"], data.get("names") or {}, extras
    sys.exit("error: %s has no issues array — expected a Jira search response" % path)


class JiraError(Exception):
    pass


def _jira_get(url, headers, attempts=4):
    import time
    import urllib.error
    import urllib.request
    for n in range(attempts):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (429, 502, 503, 504) and n < attempts - 1:
                wait = e.headers.get("Retry-After")
                time.sleep(min(60, int(wait)) if wait and wait.isdigit() else 2 ** (n + 1))
                continue
            try:
                detail = "; ".join(json.loads(body).get("errorMessages") or []) or body[:300]
            except ValueError:
                detail = body[:300]
            hint = {401: " — check the credentials in JIRA_EMAIL/JIRA_API_TOKEN or JIRA_PAT",
                    403: " — the account cannot see this; check project permissions",
                    404: " — check JIRA_SITE; Data Center needs JIRA_PAT, Cloud needs JIRA_EMAIL + JIRA_API_TOKEN",
                    400: " — usually the JQL"}.get(e.code, "")
            raise JiraError("Jira returned %d%s: %s" % (e.code, hint, detail))
        except urllib.error.URLError as e:
            if n < attempts - 1:
                time.sleep(2 ** (n + 1))
                continue
            raise JiraError("could not reach Jira: %s (behind a proxy? set HTTPS_PROXY "
                            "and SSL_CERT_FILE)" % e.reason)


def fetch_jira(jmap, jql=None, env=None, log=print):
    """Pull every issue the JQL returns, with only the mapped fields."""
    import base64 as b64
    import datetime
    import urllib.parse
    env = os.environ if env is None else env
    site = (env.get("JIRA_SITE") or jmap.get("site") or "").rstrip("/")
    if not site or "your-company" in site:
        raise JiraError("set JIRA_SITE (or \"site\" in JIRA_MAP) to your Jira's address")
    if not site.startswith("https://") and not env.get("JIRA_ALLOW_HTTP"):
        raise JiraError("JIRA_SITE must be https:// — the token would otherwise travel in the clear")
    if env.get("JIRA_PAT"):
        api, headers = "2", {"Authorization": "Bearer " + env["JIRA_PAT"]}
    elif env.get("JIRA_EMAIL") and env.get("JIRA_API_TOKEN"):
        cred = b64.b64encode(("%s:%s" % (env["JIRA_EMAIL"], env["JIRA_API_TOKEN"])).encode()).decode()
        api, headers = "3", {"Authorization": "Basic " + cred}
    else:
        raise JiraError("no credentials: set JIRA_EMAIL and JIRA_API_TOKEN (Cloud) "
                        "or JIRA_PAT (Data Center) in the environment")
    headers["Accept"] = "application/json"
    jql = jql or jmap.get("jql")
    if not jql:
        raise JiraError("no JQL: set \"jql\" in JIRA_MAP or pass --jql")

    fields = _jira_get("%s/rest/api/%s/field" % (site, api), headers)
    names = {f["id"]: f.get("name", f["id"]) for f in fields}
    ids, _ = _resolve(_field_refs(jmap), names)
    for ref in _missing(jmap, names):
        log("  warning: no field called %s in this Jira" % ref)
    want = JIRA_SYSTEM_FIELDS + ids + (JIRA_TEXT_FIELDS if jmap.get("includeText") else [])
    expand = "changelog" if jmap.get("includeChangelog") else ""

    issues, token, start = [], None, 0
    while True:
        q = {"jql": jql, "fields": ",".join(want), "maxResults": JIRA_PAGE}
        if expand:
            q["expand"] = expand
        if api == "3":
            if token:
                q["nextPageToken"] = token
            page = _jira_get("%s/rest/api/3/search/jql?%s" % (site, urllib.parse.urlencode(q)), headers)
        else:
            q["startAt"] = start
            page = _jira_get("%s/rest/api/2/search?%s" % (site, urllib.parse.urlencode(q)), headers)
        batch = page.get("issues") or []
        issues += batch
        log("  fetched %d issues" % len(issues))
        if api == "3":
            token = page.get("nextPageToken")
            if page.get("isLast", not token) or not token:
                break
        else:
            start += len(batch)
            if not batch or start >= page.get("total", 0):
                break
    stamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    return snapshot_from(issues, names, jmap, jql=jql, site=site, pulled_at=stamp)


def precheck(snap, jmap):
    """What will not map, said before anyone opens the page. The page's data
    check is the full account; this catches the common misses at the prompt."""
    lines, errors = [], 0
    names = snap.get("names") or {}
    present = {k for i in snap["issues"] for k in (i.get("fields") or {})}
    lines.append("%d issues" % len(snap["issues"]))
    unresolved = _missing(jmap, {**{k: k for k in present}, **names})
    for ref in unresolved:
        lines.append("  field not found: %s" % ref)
    stages = {k.lower() for k in (jmap.get("stages") or {})}
    done = {k.lower() for k in (jmap.get("doneStatuses") or [])}
    counts = {}
    for i in snap["issues"]:
        st = (i.get("fields") or {}).get("status") or {}
        name = st.get("name") if isinstance(st, dict) else st
        cat = ((st.get("statusCategory") or {}).get("key") if isinstance(st, dict) else None)
        if str(name).lower() not in stages and str(name).lower() not in done and cat != "done":
            counts[name] = counts.get(name, 0) + 1
    for name, n in sorted(counts.items(), key=lambda x: -x[1]):
        errors += n
        lines.append("  status not mapped to a stage: %r (%d issues, left off the board)" % (name, n))
    if not snap["issues"]:
        errors += 1
    if not unresolved and not counts and snap["issues"]:
        lines.append("  every mapped field resolved and every status maps to a stage")
    return lines, errors



# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build the AI Use Case Portfolio dashboard as a single "
                    "self-contained HTML file.")
    ap.add_argument("-o", "--out", default=str(DEFAULT_OUT),
                    help="output path (default: %(default)s)")
    ap.add_argument("--data", metavar="FILE",
                    help="portfolio JSON to build from")
    ap.add_argument("--csv", metavar="FILE",
                    help="use cases CSV to build from, e.g. a Jira export")
    ap.add_argument("--template", metavar="FILE",
                    help="page template to use instead of the embedded one")
    ap.add_argument("--write-data", metavar="FILE",
                    help="write the current portfolio out as JSON and exit")
    ap.add_argument("--write-csv", metavar="FILE",
                    help="write the current use cases out as CSV and exit")
    ap.add_argument("--jira", action="store_true",
                    help="pull live from Jira; credentials from JIRA_EMAIL + "
                         "JIRA_API_TOKEN (Cloud) or JIRA_PAT (Data Center)")
    ap.add_argument("--jira-file", metavar="FILE",
                    help="build from a saved Jira search response, e.g. what an "
                         "agent pulled through the Jira MCP")
    ap.add_argument("--jira-map", metavar="FILE",
                    help="JIRA_MAP as JSON, replacing the one in the template")
    ap.add_argument("--write-jira-map", metavar="FILE",
                    help="write the current JIRA_MAP out as JSON and exit")
    ap.add_argument("--jql", metavar="JQL",
                    help="override the JQL in JIRA_MAP for this pull")
    ap.add_argument("--write-snapshot", metavar="FILE",
                    help="with --jira, also save the trimmed issues as JSON")
    ap.add_argument("--strict", action="store_true",
                    help="fail if any issue would be left off the board")
    ap.add_argument("--open", action="store_true",
                    help="open the result in a browser")
    args = ap.parse_args(argv)

    data = load_data(args)

    if args.write_jira_map:
        pathlib.Path(args.write_jira_map).write_text(
            json.dumps(data["JIRA_MAP"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote %s" % args.write_jira_map)
        return 0

    if args.write_snapshot and data.get("JIRA_SNAPSHOT"):
        pathlib.Path(args.write_snapshot).write_text(
            json.dumps(data["JIRA_SNAPSHOT"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote %s" % args.write_snapshot)

    if args.write_data:
        pathlib.Path(args.write_data).write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote %s — %d use cases" % (args.write_data, len(data["USE_CASES"])))
        return 0

    if args.write_csv:
        write_csv(args.write_csv, data["USE_CASES"])
        print("wrote %s — %d use cases" % (args.write_csv, len(data["USE_CASES"])))
        return 0

    page = build(load_template(args.template), data)
    out = pathlib.Path(args.out)
    out.write_text(page, encoding="utf-8")
    n = (len(data["JIRA_SNAPSHOT"]["issues"]) if data.get("JIRA_SNAPSHOT")
         else len(data["USE_CASES"]))
    print("wrote %s — %d %s, %d KB" % (out, n, "Jira issues" if data.get("JIRA_SNAPSHOT")
                                        else "use cases", len(page) // 1024))
    print("open it in a browser; it needs no server and no network.")

    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


# --------------------------------------------------------------------------
# Embedded assets: the page template and the sample portfolio, both
# zlib-compressed and base64-encoded so this stays one portable file.
# --------------------------------------------------------------------------

TEMPLATE_B64 = (
    "eNrUveuS20a6IPhfT4EuT9uqNkkVWRdJJbl6ypJs6xzL0qjkdnR4vccgkSShAgEaAKvEVivi/NoH"
    "2NndiImY95j9tT9236SfZL9bJjKBBEhWlXtmfE7bRVwSefnu16d/eP762bu/vnkRzMtFcnbvKf4n"
    "SMJ09tWeSvfwggoj+M9ClWEwmYd5ocqv9lbltP9oT19Ow4X6au8qVtfLLC/3gkmWliqFx67jqJx/"
    "FamreKL69KMXxGlcxmHSLyZhor4a4iBlXCbq7DxJ1sGzLC1WC5UHX4fpZfCPf/8/gvOXwY+FCp6F"
    "8K83MPw0S+Ls6QN+597Tolzjf4PgwZ+Cr27xD4wA/zx/cfHy2x+Ci79evHvxii+9Wy/VaZClKihU"
    "Hk+DaZYHKorLLIdVBFcZLK3Ht8O0oLsxrD6fhhM14BEucKWnweOgKNWy6AVpFmTTKW9AUMR/U4V+"
    "cAkvnQZHyw/BGJY7CN6GUbwqToMRXFFXKl9fz1UO199dZ8EkzKNgGUZRnM70AHh9tVyqfIK7VeYq"
    "LBdwEAXMD/YWdxMOS63KHGb+fThWSRCmEVwbqzxfBy/Wapxn1zLWbTYz+NMDGOQ0z7Iy+EjDTbIk"
    "y2HJc7WAFSbxbF4+uUd34NxiOOrPg2JFm8bvBkG/vwxn8Cz989mU/nli7qQqOZU7x9OT6UN9B4aS"
    "V4LPhifDR8PIutMfyTtH4fHw5MC+cyh3To5OJg9DfWcexnkSpziLz9RIHalH+k6+SszcJo8nUXT0"
    "hNdSlPlqUq5wh78MIjXJ8rCMr1SAwxTV2qaxSiL55qPw8TA8eKL3AoAnnNA7iEd5lgTjLI9UXtAB"
    "Hp4OAzjg4Kdn598Gw8HRYDisRr0Oi7nMKp+Nw/ujUW901Bs97h0MDg73qw0f53juhF2AdIPgfLnM"
    "sw/xIixVFEzzbBGUcxUsV+MkngRxBCAUl+snQXEdLunONFvl92Sbr8JkBStDwCRowvvX8wxAG88P"
    "Hk2S7LoYVJOkj+tDgh0fjyaPh7L65Spf4sYuwqJEwtMLljlMK1/3YGNxuMk8Xha1sfSxwk4eHh08"
    "nspYSTyF5fQIJecZYA9gQTCNkwTWKDvbGElvIO3e8OBh7+ioNzw6xv17tK/PPpxMYEcMmIWPhurh"
    "RD5KmHQaKEYlRDwGdg3d1hd5GPgw3j/9bHo4fhwpGYbv4dt8ELgrZlOqIRIL3GEmB9Pjk/DYLD+9"
    "LHDX1sEYTohOO4qLMk4nJZ8xQwH+D54qVzQ1DSFyBV+axh9wG1MkQDidhbJmwM/1Z1mmoflgEh4e"
    "TJ6496/DPAU6hXg0Dcej4ePa/UkOTAHo4WnwWXRwOD4c1+4j6c2QEgIeTh4dHocVLJdAn635II0+"
    "Db5VWT6Lw16w9y5ewKb/oK6Dt9kiTPd6TMbN+EC0T4O971RypXAG8ORKwUPmQi84R0LfI/Led96d"
    "Fv00TDNa9+PlB+vyIp7kdH14MDh27kzCZRln6WkwHNbuFIswIZo2HNXujLNoTR8ZHtbuJAANfMe9"
    "PhdyFgwfutc1poyG7vWhvl57XvEygsMDvK63nPgUUI00eASMyaJ4+XxdzhcItqHhYj2CsDQr5wAA"
    "yPiCuES40vQDuOHh8kMvOMZ/ncBLgK4wC3hLc7uLMo8BZuFbfeJjgKSIwAUQplwRAOuxcvVeTQDp"
    "TwFO4yKA/w8JPvqI80iOkPmWcHGSLZbAswHFkhjQAOkLc8IhTFuPJjgwS9bLObDbFF8FrgucMuSV"
    "xykIQ4NgSLONiEsDml8h6aaJhoUeSlNwfCxbEqjz24VGLFhTAdsKe2SRymJI0sAT+hvO7pH+G853"
    "OMIf8PcR/H1SHVtxDPLCgdw7gb+P5O+Hp8GhfucRjOsc6SsVwtRZtOC9oBWU13D+IdKNZQKEZMFP"
    "EUnF3VEsXcA6YFUq1avVZIs2nPcVRBEUVJwRSKJhsCjnYYnHBWwI5Z6L2BxCFE+ncMxwUovwA8uQ"
    "dLB8jsUS2GoPIQrPOkW6SezK2kP5ogD4w5PJXJNqQCv+IJG5MlsCdNLEATpgfmU4BqILNHKmGqMJ"
    "5h1Vo+ktsraFdlDTVBAZSI6rRJiojyLcKTDQ/D4e2371l/1QSexB3zvar/7ST8Hdg8HwqAhgbgov"
    "fsJP/in4CEv80AcBkygvgyAQE4CAT3CfBP2PQQGUKkn6YzUPr+IM5lgsQGqb8zO0RSzAAROexUC3"
    "RGoah5PLWZ6tUrMAPG2ZEgl7+jqwIbk8zVKzECFr+w+ADOoVAYHd5+mD7DjNJkD3r+IixlP4GGSr"
    "kiUxwjLQASJ5LaEP6Pt9IDAAjrzVvIZVWWYp6h3LVYnUPwES0QtK9aEMASphaJ5XnAK1icsnevbm"
    "Nw7yH4HpxWFwf5krgMaiD3RnNVFRf5ExNeff+7JXuPVhiuIU3OxHqzzkp0CKGC6K4A/xAvWkMIXB"
    "QRQHQrb5uU80cNuZhasy42fo6JErzpXBYL9KEDOSFmvQShYM4IMEdYJeMCDdYj6Cv2C9BATzQ/ix"
    "HFd/52Gc4F/42gJ0uoBFE9TwBjhr+3cM2LQIEjVTKQgSA9QZ8ayQ4KWyZXwGJwcHFXwQE0UAGdUB"
    "JICxShCT+0IxCf7V4gkdap+2FL94Wi3cD5f9EQCOA9i4hQMR3mCml/HkUuXwB6izQOMGwKvs6T68"
    "xXSPdp0vi4T7T6xD7pt/KtnQusZnCnRtHOYANcuMAQ1QHBjQJcjzcAvXHfwNNiNSH5AnPPFgNsmJ"
    "+wxfMhy8kALT0qRBCDNKNY+I9ZhNFdAUPRUv1Iic0M3TYJooeBEAY5b2YwDJAueZqxIp7CxcGgp4"
    "AjPBZ/vXOV7Ff5uTY4n2Y+egKJMg9LmjgnZUTbKitbAf13N4kY4OiE+a0ffsrw1A0mxAxRBkggdD"
    "BxB8QPBoeyBgfe74uKf/dzB4ONqvrXwQxVew/PZXRo/23cmXhv4d4bRP7GmjrLtv6CGq4L5FHBDm"
    "fWKIxN0pgGcCLKKuAOiNitcUNEAS/lJQ75HoEJ2BgVfA1mekJxEHRpktTIqMeT/qHYUIkvMsj/8G"
    "0wSxSQ/IMoP6ACoNCoFlsJyjFUYkBIH9cFw0waEOPQ4gDOnQP5m3mX04B3xsoz1xsSbGtx/BCR6B"
    "jWRphsDI7Fn/mqzyAt9fZmQP4DGbSERQa9A6VwnZGmyucsozkRfKCmCsxZ2Sdtxzrv0cgtbTZ2ap"
    "oq/2QMZXe79UsMXQUB/J/9bpaQiaeG4sQWQcBKVrz548DJIlq1IhiE1LBy9zRwLCK+MMvrYwwshc"
    "8ROHSHqa9MtRtKsdCAsQ9z5uOK1jpDYwYxSjlCW8iB4np83krs8zZ4rnJRtMiGB/QEXFOfHJCu48"
    "zzPAnbECKsBYYmj6dbZKIoJVkM8RfTKQSQG/wjFjEkjDSrHlJc+yRY/xh5V7UKeWgIdwOwLBFEXz"
    "GEXT65QsUiSXF6h8AMe7VKmDurkqlqhmXSkRp7UU5BD8AyD4IPjo/ayQjSH5k+FWb9B+A2I7jPZS"
    "plDiNwtWykgYYY1rGRKZYYPlYgzzIesSyN6paFR7OQsXQDCmcV6Ue1qN2gNCkMfF5R7vFJrpSGeL"
    "gZTgF8YIGKDvwT5PwlWheDiyacVJAgeENCQW2X04ODg5HQbhLARdrTQ6jezGANciANTv44/+GC0c"
    "hBuP1PCJfYdl18/Gh49AxnHusAnns+Pw6PCgVbiW0fcrOjGsicHmKwKSIu4jSOqzYvTg67lYlvnl"
    "fL9GYQyuWdqGYerVzYMaD5/lcfSE/t0HZgvXYE6AW6sFGlkQL4LhNG8wXhqjhUdboMYviAJm0NgD"
    "k8cnGiT5hNom1JjLcJ/hVZ/tgDcV0Gyz1HeykdmPgE/SMO0M35X4NHjs+6mJpmM01SUss5JkvSSL"
    "DEw4NVSTNMkE9eu4/bOEugP8Gg2/vZhnZLWmdqslkJ9Bh1HAIsIxWfOBTcCH7/88jyNQ4H/Zt1Uo"
    "YNxhpFZL2MXRsai5fPiXaj3NQ7TwyRMf2bQJ+iLufLmm3bD2mv5EMPjrfZAr9m369CzPCtTsyNyA"
    "gkoGM8iYHIZjpifArYQ8qADWvkJVCnTKDE1KSRgvYEcioSmgX+FTAHMTJEEp83IUVJCOIO1mAeYK"
    "DRZoGI611WLwAXVagblNkkIlFDSlhppm29QpRHc2pgHmqhVpod1ahmh+cYUKeaNFtqD5s1RBRghr"
    "9L7v+/oEJgnoJWR1QRTh/UG7EkqBSGDGWXapNVV4c30XW0TISMSntlEWChlTAF27FtRpMxjY5Nfe"
    "0gj+VppcI2Pa7xLUehv2mDbA7PHGU23f90GcTrNxqUVcQ8vjlAgFk3SCYk2dK8klCBzaTFxCUxbr"
    "Uo3nHB/80d6kJi8j55hXSvbKxR6yjHZ5VypvKv+a88AOkkFWQwGaxnc/mJ412+ZpyR7XccJ3KN6j"
    "9Ovk5K7ic2wYBECcQZkblKumSYDvbaMZOVxZzt1hmZUFxcC6dfCf7K9py5u5QBa5n9E+/9VeocJ8"
    "MkcNo9VU2H2c+03RiXWUjUC2i0A02rcXvj1FdPfAKFxdO9EJKwK/7uD+/QwWcDaCpqMDYtt4zMi0"
    "h8Ho+EDbSc0wpFIMJvPLForgsam0QEa70a1LPmnfc5TPPBTAmT1NnHYCJQjW/JwpONYs8xboOqr0"
    "Ax/PawMxGXngbxvFvhvCWFzcrMy7y/BzBaYkxO50WAKOCDNVOcvaHrMiKmSwptRjV8RbdOfjDjpA"
    "rpYqLO+f9FD43u/mAjr4okb/GKtbaU67WvBY1AL6qDX9DXM9lLmKCb56kf46Tct5fzKPk+j+0X6F"
    "rGwJEA14G01l6+mMzHT46OmEPnqJ1dF+Hfqc2bXvdwsk26ISDvGkOvRxkk0uawSxgx3SzpHiznvX"
    "vnFsV5JVNrGn9khFMzcxTJnEQCJtxFU2D6Ps+pQ9s0Af+6AxG2Obtr9vPTb8m+2cH/00sMtI3cZq"
    "7cEp8MaYb0+OLfFnPkSVdHjcrZP2DwYHqJRqZCJ3QMvHitXYt47DTeYxZ2zxyd2zI0zIu64J25dB"
    "PEFfHdty+BqbZJjmRCaebAem9H5VlPF03TeGR4/8OiQnuVGKj7osJcI+CUbrmoIrgNYUBpBQ69q3"
    "wQhY2QCDaEh19MGvFWiz/ySwGKtlicVBJNKmcxB5BsfxsAgzlA7K6RpKP1P3E5hBJHKncz7yzKb5"
    "6MhF71AaGs0//umANhm1bo/FcZwxXLz1sEmyYBRNHgnS98iWsjt5IyLsNG9apY42itgezvLIcBaZ"
    "Q5cNTFgJPHm49Wzr3PHWM35sz/hwuxmTn/rjDkK/dcI1bqnjMTTA0dD0bzLB34mqtP3+0IcH02RV"
    "zNFz2yojHuvn2bnenGbdx+nxVDRWYg84uFRre9SddYAN7KETw4AfY4AXRp2XqMmeiuPw7yhoTC7h"
    "v8QDJWC536e7/WtkdBQNhFb7EE1512hjI7vbbIU8kMKPxIvCHhRteluy41/8/wtUn73y7cala+tC"
    "CxSLes8TBhw6eoTAD7AtMVr1Ix/uWwEKCO9JNoNzMUMAqD80IS+DJUbk4zLkvwvXht2meXkPw5b6"
    "co7bJsbp829p3+xpwGZcebu6rJIkXhZxUS0FZ2jMeXWzWSUHDsIPcUEeq4/dUqwY1ngbyqzE0M3B"
    "uACFhzbiithZ1ybQvSt0ZMJ/U8xFiCenaK9dJWGOF4pWqA1avuQIAF4Ox/C+jJfk9tCwqH8OGNw/"
    "en29WpYYVZp89SJHfvhowsgWeLzvFkrHNRhx5eDgj5UKG6lpuEpKf+iVo9k1zbDhErhHjrhZU020"
    "tHXgKhNizWooEs5sB0lYlBV8mKGM6Fb9ceBb7S4CmOft3SQvzwA7ylu1Ef6m8mwXEd3rDtKAwPCo"
    "6cyXwSLGYN5cx1WMCSARyreBTBanGT1gEHyN4NKFrSO/8941Znef6c5AV9df66DdsL+0wSEuaIBj"
    "Cu8YAFEG1kHr9R6nTaacFzTltq8RTWk7W9bS1MwYFfFvJ3qyp3fePEI/ms8s7GcW/mdgDvZT8rMe"
    "rcn7BPtKHCNVRXEfxFsj3YzFMXtLfdKSazTI5lkYLZC+YYpK8NsKJAfi8TCFHiY6wXFwfksWhWt0"
    "8c0yALErZQT2MCKe3y6kGxl9C8l702C28L3Ah1owidg8YOfhicGknGWTLaV1I27sez3wfnEGDceG"
    "MNhfJmniLiSJ20oRekJdVGgndeZIqzNm3SNr3fSZAQFTDan5dSA0FIIBcsIMKRXs4/3HB5Ga9WxP"
    "KhAvIOCT+6PjPwZ9lF/2e3XtpP5AAH/um2mQQmKtWs+VxflWZ26T8OSL34z96IZRDQcUwujFYyG9"
    "fSeea1h9ux6VWkWAEXIfOxaZ0S7coTLVNGSV6tsDgIAU46K2Pcnh4TEd5WeTSI2mYzjGI0xZ+Uyd"
    "TA+mEwpTfEQhBW3KZ2LZM3gK0ySc1WyPB/R/GOTeJTjkCx/VbY2R3xAiD8NFatJ1GIT92lZ24JyM"
    "FQgiR90/9h+W9rxY4Rh5hukS949wZ/etySxbJiOhgDRzmhjFNPkoEYNwC2g2DQZWbOWhjfHEJjo2"
    "5sAORpTQRUJei+J+aUVMfRncRyka8Np6oF89sB/8SX4A1j9AiVv0SPNPQ/uJwmJu4gr0HouFvK+u"
    "MNjf0aS0Zl9cwwKRfvhtoAc3w7i6pUAkK8+X7wABD20ERGP9ydYIWJsLw79m4fZGPLopMDc1GpZ9"
    "VKqmGIM5+K1TODhGJEaDQJXcYb/LPLjm3mm4bDpDX3yRBrVcmG5ZjOb0GwZODoo55nxsrfl45KaT"
    "A9s9Z8QhEX2OjfxBN0VK1qSiHnOqH0P21uBZzqoeW8PuejK+F1nrpxf5eSBWDTEnBymp8gsac84A"
    "vlSuUfQGbcv8QA9VlhZyoU1o9pgIDcDp4cctTpzRlkI3UHbLGuVK343vjP3+56Y9xAR/hRyxx3HJ"
    "XKugnOcKICuJesDBk3iscjiIZF3LYya7HkILyfAwFEbqTVYlj1TElOyE2aJBKLbEbIoZWw8otvjB"
    "LFcqJe2WIvniMijDSw4XZsrLqRLzlXKioymamOomSLI2T9nKhjWxxotVUWKM8z1JUgXxLeQYwgUq"
    "duIJK0AwDhNtiJwws96QzNIdkuNAQ8Ozp78wmCRWjGtLpOl/l5QnobEaT+wJU2D3R3HFDQ2xJZ5c"
    "J/tVxIfkxuVI+cVnI4kidGmABx9eh2s3LWB3TKmrp3ZIoHeKTb9E3Rtr8jZyYVsW4/YIZC1s2HJd"
    "1oZDy/f7ui+FGW07Q7WViWokAHC/Dcvmv7/tor4eHTm8sA7tXpTwWtDl2+0K7AbPxLYqLH9GFDQO"
    "zthoIPPt/NYBMluaxyqO3SXU9ofs/2a5ln+JaD+8vZVOJtFuid9wBtsY6NsPZYJVP7qJKjnEAJib"
    "ZhJzYEPbSeOg6nB/JxUcpiPh9YaU+RyNUZyriQkBA6TYNtahWotrxK+nPVhBggfV1K5aTqhVudr2"
    "fD5VpkSbjuHMLJFwdCOt34I1Vs82xYIb40CXpddMGWgHCArosVILWOm82Ox0bYMTe0hKhnbH5fTo"
    "CjBs4qMPfGfVVwePq2WCwTTu3ruWpLp13H2VQvTJ0pv4IKCWzK1x2rUnGdkvA4qvMMm6KIKFwo1H"
    "aaqATQM2D5JXj9OzqLAI1dNROVXTQklO57Pl4WKphSce4+PNY6wm2rgm+3N0YvPYkzZ6vVXQkMfA"
    "yd8Uuuxi6u4qOA+2nJR34OlkJxPqdgOQcml6LbRVEoCVukzWVkEhzB+Ca8uYdnPX8zj0JHtvCp0w"
    "n9PRd9vXFti9rkCHK9jMg4O+bxHZ3rRXbZc+0QYgm2KO3ekP4qJYkZnmBu4atqOFs0UYp550na2j"
    "dWzh+dDLT70hsMf73aHCQRfpPt5vLR3QVoBAVup4ks3M3Th0jz9Zv217krvfrpuFZQDbk9w9QN2f"
    "rI9qkLvYc2Rjz3zkoI7UCbgJbte+KW5Bw/Hs1IUT0mu2VskIsaoP7KJt3Hlom+US1DPZxiMYzm4T"
    "37YZY3wFL3zFiJzp3By06e3bgDYNcCvQ5qC+nGKObiYcNO1XWwCffBaEEuCwdxix7dp3LHdOtdIW"
    "P/umHBwTgbeazRQX2GAzZC9QH0AsjeAKWj3Dck6GsFWBOa4F1S3A3HqMrUPvOgsA8G42Q0muFkon"
    "cqXHZjLcokaGJcqztaYrtZPyFdoqDfmFU4953JSOkAWZfIPutBqMIRE7LmL/WVBGHl6o41BTlWzW"
    "IWvJGu2J+8dm1s4cVohASVwABGABXb2nVgq5rSnV6aZHYnZGT+LNSlFT5Qa8zUvPaAMxhPrYwo65"
    "7r7Ro8wbp9d88Hq+bsMl38MqrybNu+sp/2EwDSt4FEFYotoOY2hFZh4vOwI3uy0lNzQetWRAWi7p"
    "UUtFgnZw9het4gp7zYpVeFlYnw2FLWpT9bgdrr0NbztsMvMDK/6a4yzmmLV/c9mXZ0eVjj76oq93"
    "jtfjUbkEHPr8ZVP6H+wycPRV1tvsBNIkXBaKTEj015Oa5aVCq+HBIysklMu5mcJukSZ4Ti5Yu1Jh"
    "BD0ZyM78qgat5YN5o0eO6yNhxGdjoOqiNY5bRKg+EFeTaTP7H7ZX4NjarL+VTdDPx4C55lJUqcb7"
    "GmFw+npNNt0hldTZkK5MUs/2DcKcpduOjCgHBey8Xl+tO/sjVHqwjJpB4h2bXk/th+3yjJnbEOP7"
    "guUvcd5DPNiQ8ej7WnuSop1CyEYXEVV3Fzur16vaDrsUymgiuLf2gi/FeEsg05PrLGKxSbCSrc0H"
    "kyQrFIVbVovuMM7wDO4kq3HoEspBulroE9veuHYdxhjzchv3vJNj6d2ZMuoMIm7Zys59HIfRTN19"
    "gpBmdl4po40Y8VwG5YeyjjHHWqCTiDtvCql2ke7o77itlOUp6ze0PPiW2DVkj8YGxcETo3nIlac+"
    "VdERZYy1QeJIFSACiA6HZdMC3J9CF0eTusow7fjKagyw6GHONdyUQkdcWW2GWEy6/RTEYLcGJNZU"
    "k/K7FGCRcNU5IJRWbTYejY9sEFwg5JGXP+TxacoollE0m7Yw44ms8h5Xj6OGGlj3O73UYRT4liVE"
    "3+DMHUA68WXwbIQCMbfcriTbltDRWpl5A2CYnRqUfazw7+ZZdVQfsd6bwyZteG+/HX0pvqnPOsGW"
    "UU7H/nTcMsuSEs68qVkYQKh839TewKqBe3Lg+iBJEN7RcN1iX3NEYoEYO/IXq99jBo60nzjB5h1H"
    "B70DypyQafvCOmvhbx0EtTrsJfyr9EoWfvPmsDpvfDXvVvBH7aZza5CrVsVbHkg6eQ8+Q3aMmjVM"
    "Y4JXhTjalHRqAQ0sEHnhKlfN3O5IlWGcFFggu1LsbHFc24PtB8+CYrXAdiZa0/AVbHOJTbuct9nw"
    "s6PfyGJWTcvQlqU9vKvdTuL1v3oK2zG+jFEIpNt9uHrp+nYr8bxlCKmp+tGqPfuP/+v/Dva6tA5r"
    "qJ+xBt0vGwf8f3BAtr9K0fSPu9rpm2G8tej0CsI7DPWmZHsTNY59gYD6heVNLMUeS7SpBh2mYbIu"
    "uBGHtjlEwXitIy5QGkDGHalFFmD7MGpXg9X+8Iru1ZErEkzFlKyHtDZ5JzdGcwBdb2CDW9n/4qj5"
    "oo5pZRsM1cbf3gaz0fIDcFHGnIBk2WseH1TmGvME3KiqEw33e/atyLllxYEc/7FzmFH7MCNrmMd/"
    "7IrB8g992D704Q4zPG4f5tge5rA5jJgYapao1uBt3fegp//a3TDmok27ucLpsNAmHW0XdtZuIrI/"
    "dRNrSzundsasbe+mIHHigu2wZA+9tSGnwemBwueUdBIsskglTclxERcFmuU/dvpVTfZNsw5ug+zC"
    "BLB9jFafqM2LKkrTIYeqnxYlhgRhBDw/hWICOd8wMp7rPYOmNatNcmCa0LT47xUHvxzWXfi+Cs+t"
    "JZipB0670/vhSDu9W6dVJ3RzqwCz5yVl7CoimcTYR2TypO2F/o75DrIeywfWXn3aUabxLIJ0hdkE"
    "wLxyrBLOSQbUTAjrAmteVnAUJ1uxpBGWcME1678F6tycrUA14GVVpKiyrg7KL+vF1FYrmHNnpR7i"
    "CIPTNUAODzbDQiiosYMKXmZS5hyQDzvIKJUO6nDjckJbmj3er28zCMXIwjue5h26UJLAghszmYdL"
    "rFRoVWfXPQOBjgThGATFQIWwDq6wrGgx8IlLpZtCwANVT6hLUNoK3GkRxExyRaiDB6kJoW2MwBHu"
    "6f5ek0vAJThh3Ci9GwUFa/mWddISy3m8/2RbN8An/QV/VaEtO5VUdbcPGvqZGXw+2iV6x4J6M8yO"
    "+NMiEtrJQhyP1YFUUoobW33AygGduOFajhZgMRmRXFVgWzjTaQsBRTchs7uPVX3mdIOxqjslAh93"
    "J2MrF3p36b08TifxMlG1YQG9kgpwSsWTMcID4y3mLJHYpw0O1DfIdWNussJ/0niD3Wapza1019RW"
    "OZhlwcgBVCLUO2FPhzry0vx5wsLeshR79FlbSd0hqW8t91+p9oj6H+AhM5Jae+oujZQMH5AdEoPp"
    "5i/etCQe90a6SNPb70C1rjuILHUlmogwVaAvWBNq8QX2k1DAbVUp/aoKU+5ULcmyb5cNHLlVdEZV"
    "cd2mJudKCHZ1Ol99KV/BbV8Kljd0xe9tn2fXCOrXWX5pmzOkc7DUpNegLeiB3cN0RptAfMgoMTWg"
    "PwhemEZ+PBhBa65gjwsDNl/YHT+eVDCWotYHXEHQrdRsAc+y6mPC9mnpjVhxXmQS9DTdR+lJmC4u"
    "hbo/Yp9I9duKCvpnU0AVl0rwF4hUJPGly3IrwcM0J+Img4h1lXKK2FSbFgsEQtZsmsPCJY1SXANK"
    "Uqn7TIzd1Mg0tEzhS93t+ouCC/EC5GIZEyAzZAd32FpIZXo1ckZosYf//HNqhOqv3ZBf1ND26Lg1"
    "JIwL1lM3IbRQuT0vWs19n9yXKDjpDmlLM+O2+tZ4WwWneu/mpXE2TvFQDKO8jXBa3aKOpiHP43CW"
    "hwtA9NeYT8tF+a6yCfsy11UvzyDKQ2n0ZTUAJWE90mwYqMZs7qcKDjwvsZQ1EGYSl8OyzOPxqlSc"
    "oltJy5KoLuNx1yB2K1G3VgDMqSQJw0OZ1P5h+RI/BaQL/hamThE1JlVYZ5WMsw/YsyPl0AbuLibu"
    "JkRa7ZwSmUTkaUJzx0Dz0CqxlksArHX7kXWbxFL39kl1W3o7Mt0xtBFI8SRbKENCbbqNrWZRTmBT"
    "G59QwY3T5FAyErBpa0FTnlP+M+c3m8xnJIHSqLbuesODyq90U2jM/ozWxVJNmqr+Lnq9M4wT0dPi"
    "imp6gWABintvY+twrP9UCOGsc79vsFhUOMEGMBrA5FWtT+CGLsMCONopqyRzrCaWmn5d10Kz4RQW"
    "cclypfMc4TbDG03C6UrFDIM4aEFimPDR8Ira0IyxceeK/gQd9UrpXlkz6VyL3lfgVT1mWTRf5PI2"
    "PgkrRZYIhxjFE9NshsbhYgu7F3I/sgu5t/SFqGlKVg3wmY7yu437vNXfyV+ZsKK1sdekX9kabewD"
    "cbjfHfYY7BTJa895UKSZvzzTFvHKTpeDasCFPx1quywk0Qs/IGncIXjYfg1578ajsIOBb3AYWyni"
    "W4TU1sWSVsf/J1cg5Y5PnnZ2IPeR2kHds4FaS0f0Go6CqtaHx/oUTg/nliADYJWvAG0NpfhpmLOk"
    "yuJkiRHFOHpRYm7GatmreqJTt00udcM2J1Msg1XEKm5CyB4SOuGeY+yEnU5xzoZYRHbSqKdOjoul"
    "Q60Q9Yt5To3uDlyyUFWGxJEHcT/CHdy2/qa8s8yznapuymtsUtuh1iZf1pWWucpFAwl26TU6arT8"
    "rglsR64nuzXcvSMO/NDtumDm7wvR360FgRlKQ4V9sAetLDnKJtQ2DUQ/+HZMEpbHvz6AyzflShgH"
    "3Z8iGwYZahF+uD86PMBKUciqPLzq0M+rqmYigwilwI+djc+34GE2N9iclFn/PFpadmh35c9k3an/"
    "IFN9j61x1Jja4IpLarSHCdGDyw0ZyTWSe/JkU8tuHjtb0vm0RWFssOLL68vgS6uLojeUQ54EwTrz"
    "hmp21jeqoYExM/a0DqERQ1reNRDCvHG3kMjq8lGLJ2un7lgnrULf5j6e1vJ2hJKHx1uCif2FzWdd"
    "Pb3xvP1+pK1BgaV/Y0n2dJGgO1IQrSMX66iVkDme7v8OxMyS+3MyaTu0bJMs6olcPLoRMTNzmITU"
    "dNMvDW9s+JW4lNFjza5ym5Gb3g3Vs8b7shq4yy7Hz2xNripDlComdw4kTGfqHvOGhLYTwTnayLlh"
    "JQJvWwTydqeS++ODzGbjl9SH8nfgcA2iwa5XD6XgDOM7E5uGx7cTm3TC8z9dcPKVyjGT2mwT36gJ"
    "t1rJ+QtSOuFW0hoVVt6VwvVbzmRonYmusdCeorXtqCOvkszG5cp8N5j5cpi2tv4NZtl1SqXm7Wuo"
    "mnWJm75O9QcHVrM9bfLardteewu/LYc19R2aOI3ZFxhL37ROnnPuAyj47HNiowCZJinwg3Mqokzx"
    "AzNVeqwPpxIRgnEfUvgSzfgghqXBHrkGC/ZxzTIYdK8nvj4M6e/T560Uf3ITy3j4NNospmpSJuvg"
    "GmsEXWerJLLqXGLQiZIG2jpHg82f5INlmKicfXAp1G49apcdT8g9gO18YEw7teOmpO6wzW65mahR"
    "vgOZLXfM/PEzQCvxcycK10ZO69O8UToHv+dJ59D+CMvW05bmwaO5jYf+WWqrbfWwm5T6SP5oK5Lv"
    "rWnaVo5juO/VlWVH9Yw6DLYluQ4+7uiQbJUaO6PzKjTakmi9JbpDldpC4O8fTjnMDUBxEidfFDTK"
    "wNTi7XbIaC+JFOll11wzNgH1I5mOdrzjV07hv4YsIekC1EH3R0l2WHGJEHHk1i9CszKQ/MmLTo40"
    "tKdmueVS4XAg7BxGnQLjlClXBiSNFxxgc2FyePJ4ZgrhLEQaFcAByUJnJlBokVXRCVhIrQCyl6tg"
    "j9yUK7XXk/Q3CuJbhBL+N1XXTAQXWBkCCfYcSU+ZAUkVb79fp5Q6bBw736P9YHvnEivnxSXFutY3"
    "+kIC4mw/LMU08WZXcUdE2mUDiQqwOVopHLbQzit0fGk+Ul5nAlA6nn+hiyzTaJjbN88yHB/IHWUk"
    "sqc41GmB6pJ3Yg6fpsgRWNPA1ZBl5G69Ps93Cr3b0oBrDX89V6m/1sMutuHhfmuxlFouVZ6n7XrH"
    "NrVUm/pfjgpysPuQldqbF2pyB4R/p3LRJn+n5fhbiibsUMXB2A9weeLczqZ9itz52NaayPnsgS/h"
    "R8aUkJZ2x5ptaPA52fIqwKW15nBrlIxfwN/YM7DOhtqNcZsMgGb2VX6VnLHOsdp74q1Z3KglQWt4"
    "pNM2dQVP21nla/B77K+2aQQ0meQ0y8ob25p9fQ8MJ/aTjoNahtAnW8PaNVioHqLL9oXKfzldAevi"
    "FFzggRw2CsyRk+EGwcsSRsVcBCqSrgMlPgCqU/YWpXULvdZZ5RKzRiZv3avOsP1a0aOBXQAIP2Qn"
    "TPosdWRprZeUdQZw6++07lMtetVnAfQVLhl5PtisQeQ3GTXY9vnL4BsKzgfRCna3zpy/z2AkJIIB"
    "gBAcShzygQAUgwwjUbtuGgsIYxJwT+pUIdHOhQkKTvtVkGMJAFXSXy77x0xjHBG7McQge1zFxSpM"
    "gmJdoHHRCrBuBnRSHKgOScKzYjgoV7nIBZwfkWGovhi1qj6sahEXqj04bZNTRw8wuETt0ckXdcvO"
    "tdnz9ABt3gix8nuJXdPK5/GiHTWmukyqWJXWwP2jWkz1di67I9vRoj+HB9FS86iuttY7Smlea5tl"
    "W3lKlRlpRSa/w0ADW6YnN4iWMsdZhMFR+SoNChS1EeLQjgeiuw5DJnDUUVckWbLdoWD7B/b4y3Tc"
    "HgjMJLNOsgWgEGLrWkNaGLc4VrYzDLn+Fzd80q95PdL03nx5i2Kg8qwddd9wtzceG6RZ8GXz4Tqk"
    "y0sTIBl2rblpuIgT2I69i2+CV1ma7fWCVypNsh6mZwAshHBuC7hO9rsNcQktFmDJ/jaCzNAuZ9Hp"
    "C/hkMS3iKaQ5wvGxoQxWu4qpBOV1mBuLkU5ZshCMU8hcPCPMfoCyzEZUazo42hClFUl8cR/HIuFt"
    "EJqsLaCFU+ToIDgPiiUnBtrh4RFH8Z6Ku5He4GDDYLzCyMpMApCq8NgehYuSDvjs4kJU6VxhubmC"
    "a7Ev51zbhQxzqN5yFK3JBMBQ2mtM6SadFLgaTOXiL98yploRiJNLRJMtZF87gf1o35WBN7EE3qTb"
    "dIkcPdKdn+pu1xZWf+x821+ZrlZ6UAJ86Qj1AYxVea0UF9LhPEPDPkn3433kbwApvW99aP9m0vTw"
    "sGqxd2B3A6k1d+7swq05Dm/8IGnmzzgRZPzrf4z8Gb/yZIrEDGtru1kaFNKKZgIUj7h0kxtuna9w"
    "/MQ9C0xMaWX97bSRh/cQx9tSwsOu5klOmYoz2ZtuZLef3iELoyGV/0uch8DmJpdNa9kEJOhIchdO"
    "2XlCcb+cebSMKWkKiWKYcpBnuFzChlJKgzZMYo6UeHlKQNoiDtMvdGg9ti2erer5q3BD0menOTrW"
    "JOE3KMmoaJKHxKhG9Zgpjhx3G182iZEodM3ZwskZD5xLUdBD7DzS6VFknOlJxrGEra5K9y34Upyb"
    "FIj3klrSnn963J0b+NAtaU3jbWNxMRT3/Y2zV1sByyNXG4vXe4QTRqh+/32fgl2D4LPhw9H4KHpi"
    "X++PgG4dq5PJo6PqOvdtDT6LpmqoTqrr4xkOA3TuaHo8fWhfx2GCz9RYTaYH1vVkReMcHByPJhP3"
    "ev/69LNIqbEmmXgd673h80BHQ/3dNpcWz9LbPrVRmtfX60LTWlRijjscLu8t2WpLvjzULRmFWHjk"
    "7sfG/ctHtaW3A9uiISgjsGO3IgFvHGLwPg2vvAHEeD6W/CpEuG07PTWcDp5suQw9h3oxJAsoB++X"
    "fov3bm3UDppVS1zgh+/gVBz+7nTN4V8Of3cF/EN/uyeG3n3H4stgtxvTx854D4bNTFlrAa2hCj4A"
    "rfPY0XFtO4RKNd9tJUISgfHJhbGNhmGfMbj2emUUbq0ldehFRJprC2O3uprXt7L67iBLW0OANGFq"
    "fpmP3HMSrW5nC0w08lJbETEOOIgrlaPcQvI+PKxv5yQH8ftGZ+pDJHdsO1CtZuisyZG2RbImRh62"
    "fsoLws73M2nItjFDp7WUa7MtTrCJgtTgplBhPsGSSuZ30gU9M28AmQ2XPiKzARFG7YjQUga8uQIX"
    "uiiS7kntsQThKczboamtVrYDkFuWlt8KRttbe5lZd9ed58d0DU/Hb9FRAc16U9dgb5bR2oYm92+a"
    "r8eQtNETWElA3Tl9+rnWjrpdh9AS7dztCrW20Nf9wJsit2n2jXpkC5DtEve8Ntc0FyQV0wapU1xk"
    "OGRDPKhQ1GDMUXJm8RVpJmWVbqwzXcmcG6fai2EXEeaRg1myXs4rB4O8T+lv3LEGE/HSCXxnVmW2"
    "OcuhMtFws9dyvXO5+EwNSS/VuonlrRyuPSxSIyFVGPfSc7tj1rBBc7g0uaeJ7e16qsroi1XZbBPX"
    "TTqd93Hj4klmFW4HKe/R2KpJ6zZxGFZgFQaTVVFimj+BEgpeVkEscj5iidVTU8aDg4jGq1lAjR5V"
    "TbBnyc1bMrpD1NT0zpF6hyceX/Oht6bwyXg0eTx0jVuW/Ppok/h6Pc9umNS38Wwakr3Tc5p/dUj2"
    "5Fu/pc1u4/LDq0Eyq9iOV/moyK7GDgYgY30JkuxvCgiDIThxXjfH9LizO9l+GKDIEkNGmapA1Kow"
    "FWhK4JloREfipw0/Fc2Cv1TpkKEBzKEF+rY8U4/35NDqWFwrHL6BT90ofP1wB5aF6x2UGTVi8jOQ"
    "viWSfXY0Oh6dOGyIBqA04I9bKRmfHTw8ehieNIag7ONavz11OJ2oqfXqwcnJ0VH9VSPKZbgH5Rr3"
    "4GGNuB8dVCb+cwnfxjBKDswLC67OhC7MMZMwjLErdYlckLxisp9whSoL2sZEwUpjiySXu/HM6YIp"
    "Vmk8AMkraTMVBjwu5nxra19eKImyxNr/uvVGFdKJtkfudBVEYTEfZ+Ri4yjNWUi19HrsRYK3gX8w"
    "J+dyKlk+C9P4b8ZBlGRA8gknQm2yNIHsZb42jlsuziF+Xe1LknhMXQrmCuBXV6MiMYHwrwipdwG3"
    "c6awFGwhfMURq6URK2gVXBWlMGVRMA6DjasZTEvc1BlVmsKKa9dSME0iIX9bqZWqtimsdodngsE1"
    "zJzZBisUQWyxdUuTFCKJTdAqFm/JloXO0tfhlGwFpjpmxPswEocKDUhNKk0dKV5oQ9B6Xb71h6w7"
    "9pitTTgzr6WrM3b6qEHi83k9QuIGpOlER5R3q13eHkrOZKQv3W4p/63BnA5trpkdcsDsO/bNs7ZR"
    "DelkqtZOdeTwjpqX3hI5jymuriP5Si8nilsl2JaQVP0mhoy1y5jWo3k462PAdNBsoKrGqkq8+2w8"
    "HdU/g+9Sjoyn+Wpov/v44dH0YNJ4l7JsbsBI8N00DIJgK0bYXDwTnooONI1e3My5PTbtqKa5AJ0v"
    "NluOGyC/i9XY35/Ka0j3ijJbmm98sN7aYaHDHlIDZZg9pop3CB41b7Xztj6N7dwcw2kejB4SMrbE"
    "H3isi539iGvT2CIQSet61M+7ZkC1H+B6ELei0Vtn/Hjx/z2KTG1ExuMd7+ZDdmiGWy8UuH4hrXF1"
    "TpuR2nhfsRxXHmOQq4uPv23vaWgJLW8s9wyHrVVd88WJaey2ggzYinywjZ04HBeb+7tua2Ty1xdp"
    "fhCgI3Uq6brP727sbG59B7y1gah3moMsbTX32B1/4hRjFQ+Cvm3BN086Vt6taQTquc0QpdF2MDRh"
    "C0I3C55IlPrt3FoTccG0F600AOm6GFOVdFSMq0uwnSyjyqzhnrxWA2L3e5qc7RhCrO1aVFF4eyp/"
    "0HKEW8iQ9ZIn7gyi8tbHpkeKOsKT3nfUUqh1xzWYs6EpX4cwtNG9UxdXDb1pCA7D/aBbHqhZIPx1"
    "lnH+4wzk9UUWhc1WEsCMQekdmKccsxrw0/snJ1R14fHo6np/U4uxmoPtSa2h2AjL+pwceTqKjY5a"
    "2kN9ak7x9BQfROWzJuVYg44ew6BVRPu4pQvzsRUh7WQzb91k5CaFAw9r8xrMdaUO3VHcubtjxsCw"
    "NvoN6+572N9yjI31ihuomPp17OS5QecnjN73laX3Nnztitxsr53ij8Kq7MWN7sSeFmO91m6yvM7N"
    "XcZauxiPWzpJjTzgqqtZ6bWfjK7mVQBUf+24Q2VkXyuuo33viXNnqeX4txWldu0eVqkZp2XhPWqa"
    "WY50eN2WsfBHW8XC22twOvNtLM8tL+1Wm9spzHPqUvGmXFH7zm6luZdjyftrKlonzSZj8vRglmGp"
    "qF1Zmy/GudYjwouaW5ayagfyo/2t+/zVltiBe7Satg6Loko1a92FMyUs5C76LfkJd3Vc+mvzYQvp"
    "Hm4Tsnpo9777gWo1R/1lmGPexXLOFU0wJe5UqqWTERi/+0Xh2PfFYznA5E6nLID2GWljOvoIMN3j"
    "12oFy1/5O+xHoIS8nEzxHORrNUOh1FH0kePJ5VzyfFDVkQq3NG5u4V5ssGEz/GBRqEanD+lTxmEn"
    "DCA7ZWgdo5XEl6PhTNWS9TujLJ0JbBEyOogpR9N0EdmuuPXGjo9tPQ278gp5Jrpe7Y38wk1qN+rg"
    "o9Ob9y5ojWXjgdGbs4uVrKE9OUMdbq9N41iD464RO4ur4Nd61Ue3sK8R4LR2o6yWgY+5+US+NpRm"
    "QClJ1hBpuyLhm6xwgwBsf2qQLcv+RnhouEZlDOoW/jPSt6/2UFbf+6XnuxXBNlq38MkQyJ2rU1WN"
    "NU93rHi+ndy8bdUmT/fnBto73NcEzFlCb8/S8JpMub4NZJ+dG8cOCum5ktOW2K7mtp9Os8mqaGwq"
    "X0YP96rkbAUn0sNXINNVRg8coZTFAtP+F+cwyZBReaNPO11oltpnJVM2cl13Ow+njv+2NQp363Kj"
    "T43W/TMnTvzib2wsezNoFtoemhgveWSSt3fV1o+U7X21ucxxubnY7KgqikxPw+BJMeokckLoNhHN"
    "7QfUVJNIDr63GXoON0HPFux6MyQ1GnvfDNXb5W+z4kry9uChXZPHeiMs7jOmT+YKAzD3W143RaBb"
    "hHqreXd1AjQyDMh6qX9AG4AbTdPc4QbZpkJofo3NHiG6WXEk0yZpEZc1AWRLEerI5xtt7W3FRaex"
    "2kmXS/QOtUMPE2zvJ3+yi3JolrGlYujs8wDTLW8uSkp5nDBOnFzvAtjd5Vpymk8oUKGDunVId5Vu"
    "4PlGWFJDWslBxfsD6XFT21n42aeevyZhFR92DEU+kyA9tZtphV4hw0oXFnWWIe6yrBwd176zW7bt"
    "oFThgvTU1iIVOypQLufeqTm8mcugzO6gQatPUG6QA/+HKyN0ey1w+6XboIszFFkPPnZmQYiC7msu"
    "V4c9M64lkzZZIcsmWK08pyoQt6/EMtr39CRoCXXplEWsWW2hvElZ4m3YxPsVEKTpum/qMVCUSV8q"
    "PbQorzT+YJLswhGPD6oeTDN7ck5E8S7eAevQcEitWvoKJjTkoNpbX5q3O8tJ6FmYt7WQ4StgUUXg"
    "PmEPO3soW2cigQV1zbg7T/IG4sQm5lnbG5+YJlPdUihoMWX7vkC6Xf8qLuIx4Lat5NXdDaLayf1+"
    "Np3SDverVP1cTbBZ7k3cVt2IWo28O8iZV+8KcsyAfCau2qFN+7si1Ra5azvz8G1lNndzbwR9XTrE"
    "NpDZOoUaeMpEdoXRkUn4QNeFylvqn2xlrazKyg+xnpe3itPDfXIF+lKLfVLIo5uUIpWVcO2uu6/b"
    "5Y1vyAEPggfBm+ffNBw3wkv5Ee28JNcqHPf4Mi77dItBpB9GyAVPA/UhnJRPgo5bn2gokHOWlKDs"
    "E7nlCcBmMl1huD/8xfvTkwqWBZaFoQpJgzANk3URF/t+g0tg3tAPOrUot33DlKH5WFPR6un6WIat"
    "yKZN/mwwh4ItRsfHPf2/g8FDLbgGXboI30ctpMeN23pSH66HppZlz/gq4PdvaK+WAbPrUY/+gzrJ"
    "GGS3yz47kYBkXmUomOk9byQFnwaCq/oZygge6OrMTtDoZukUFUp8s8S0cP6rO8d1VL1YxrDARsiN"
    "e37BH+IFDhumAmkeoI/CMgRMXOUYCVyEC+wLleWS0WXqmVIV7HC5xIyXKZHZhmezyCcMwrd2rA0b"
    "Vif9zw2Ek80mLf3PbRseVOX5rTFb1bcNnlvezQHl83R0OEjsBqb8SgmfGyedb7W1geQTbFFz7UcG"
    "Xd5N7Ik34UzeXQNnbliiiD/XNe9ospOnVdoEHbAGZv8cHDZUsuNtLCpmAlsoW9FkmWfjneuiyGtu"
    "/8tuh+KjtpBaD9YcuJC9S//f3WU7d0GuO7D2WcuXIC8MLtW68Cg+N/beWvbca/h4n3jGqbAOvGK+"
    "78LYzb/L0QRxGgNHGKRooW1PZAbop6S9TabgFtlUXh8Q+zApPOHD8CBEiDT3F3FB5YxrSOahJdU7"
    "qxSZhoq6G2hOksxnkdqdcXT2uKn+8XadsYg/ZjeqLe0EPPlBh6tCuww3uxr0TtQqJO6MPBL8Cf83"
    "elRVSpDBByrPN59hK6yQAf9uArLa+K0oVvc62ahX+2o6p9pc2NVqtrfj0+OD2TyjmlVNeGjveuOU"
    "2sDN9yrebt0RRzPs0glNWkWH5cKt9YH10VnSvEnORqirflBSSZVG7VBi60mzwY3nqXCJ1e9DYuaB"
    "TZW+mNWj/e7sqDJXcFz67Rt3DrA5Hgz89AEx4DP4A+3X8F/cxrN7955ifboJFlf4ao/Vt70zmMbT"
    "KK5dhq+nim+6twlG5DrcIeVfbmX5bO/sPEnWpNpi2ZLg6zC9hMnAQ943YNy9AOuc9NnfDl/PV2rv"
    "7O8d75TwjZfBj4UKnmGXnzegKkwBsjL7lacPYOTm3FEd3QtAO1L0N0oq8nkycXy19xfM1q4WN14B"
    "t+bAPlg4/bBe3wviiP4ADOtjGc5LbNXG4xUqUZNSRbIgvii1J3gi1Rtnr02fgFfYJ+DpA/7UTabB"
    "8XGNSUzDpPDPQl44e8mhn99k+eI231/q09hhCtU7Z+Ywg+c6Wf82s2EWscNU5IWzn7hf0wX9vM0M"
    "kDrs8H16/AzV2Nt8NIwp5XCH7+o3znTXC/fzNjrZqIg2Ev4y/XVWoaC88fQB0BskO1z6j99CuWgP"
    "L1qYySoaj6X/5sXpI5ER7z39AyjvX9X/CV6/efH2/N3LH74NXr1+/uL74N35182ndAMzDOkNxzqy"
    "t9amw3T+7gVIm6nNF5a7pVofWa7/HujBdKMyNOlgaxXszih/SyMs5FjSJwE7kElBNiwLwvXEp3m2"
    "kCLG786/fXHRC969fPH2gl745vXbH19d6OYupim5rqaFtS90H7MChEwsHJJm0r0R62VE8XSqcuoo"
    "goWCiyfSHm65ljoZC70NeuwvKJp5EPT7cH564QJdFpkzoEe2AZuMJioar5uE8exejdGQbA5Q3KTT"
    "7G21CeOCCWMFhksDObplyt6Zw3WwgYvFG5at7/WL1Xjv7Hmcw1LheGEz4c2LEj6sZus6cAyC11jK"
    "H+WBaBC8sNrn6ZIrunH4IHgeF9ixHH5gCcQYHhpU87BWi85iP0PFO7inenqwW2FCYeQ1/rg8exkp"
    "bFxP9VkmWBZFd+ZjmIYbIDAtywGXukkaQI9lYqjzQFk1C1qqDA1rmIVKNatx9FWKdXE+X6C68SR4"
    "GxeXPaAYaUhN/N6pyTwFEWa2lhZDeRatYDbUM7Ywb3HfGwmK58JvDIxhycVw8kJq3PwASyiyheIi"
    "1yRa8MSxV10WhWtdX4YreiNSI41EBCdswC6EKqUXIkIzUyQmUlM6GMwAsI7FLzeY5vN71o4/5U7e"
    "ZxeLLOMqdtOwYMykP3AOdGsQPMOyOyDg6eLg3GxvjK8ts4KE5QGKbDSemQx9hYgVHxH1hSiCiQwW"
    "StdDpilAIOgXGlCBBsArdGBwrLDCQSDsnd6dYtLC9VxxEXTEbRXS1ABb5oH6sAQZFLYbAJqA1nkJ"
    "m0OuJhOsk5Rk2SX8O75UDOoZTab5BQEEWCORGoQ+eEEVoBZ7nr7m6XMPjJi3c4ZDE9xhP9tB8PU6"
    "OF/CkFdh0hMQfPOK7b4CikRcse9joRQ1HkHyiIV5pAz8oL7JuK55iKR+UjurS6Woyg8ST9xVNibn"
    "3MjkJ8y9lnsCyNGKKixVOwI0RVZ7X6j2GlAMpPdedWIwTao3JUZrmmoZYxEzXB7iD9NoGajqpTmV"
    "zaFF5+q3FdAJJGoAe/N4CiwM9hM0khwPLC4NQATShIK3mcItdSvPaUnwMkVMjMh5oZdGgylsGYwA"
    "B8vKFfcipipWRorjcXIF4HSJaF3ESSYl8h8eBBG2H0E2Sq2Mqc0yPYh9TBRWNyHqZC8qnmU5H67Z"
    "rsuUW2zBdq2WgNZp6UFhLTC4qIwMzcNx8DJqSiBnzEdnTNcvhK4jxX/LFB/UqdFZC5Ew/aZFijE/"
    "nRdWic2AVgXng5hXqivw1iq55ToE67+F8zoFWIXt+hbJ/Mu0ax0grPC0NX5Y9yK4iUMfnj1LVJgH"
    "bxivYbjDM8Cji6WaADpPpPwjgAYyVOY0xLqWIfZvfUX2cfJBEYX/PIl+W2VPrrGOWEolvbBe1vnL"
    "wec53QguYCw8d8KDmA/bmn3bHIGPh4w352lxrXI9zZ/mQEBe/hm0VGRAxC3GSEETLE1G3A+IC9K4"
    "Hjdq6+Eyihi9TDm2sUqKPyOCrLmTXlh+nhc4TalsGSLFh09ToBUVZ4irJya4bRiANVdc7DNIEKq3"
    "XVG1c8HrVTmBbdFr+i67JqqCOIrogaSBVobYBfN9C59JVwqzdguUbBHxgNytWJYNXsGB4Sb8toIT"
    "gCOsDicslrE+v22n+Rr5ffB5uFg+Cd4BGUMZSE/0fEKV3mgNb14h86EPYunX70jIQPo4QwqySq/D"
    "9Z9pEmRxAlEXkJFEiXm8rM/lLvBeGB7jy3OSEIK/hMlK3Rpf9IUrkua+Wy9RYCniogLJsCTy+mGp"
    "SHyThr0D0kG5izLPblDxOCCJxB4WeHghVrmyQa3EsngsWWxzaO4Mv5ZYSge8sKcweba07HWhSmwP"
    "LxPSsphpwCxPR6YTM3M42lGWmm80twsRQJ5JMKCe44sP2M8FvsE9mYShzYH+ABE/R+k3JuEQAGmO"
    "bTNRvyOkACFm6sEJ2Xmbw+w81TJbojGMGalz2KARzGYoFWNvmiuYKDFUYsW+Q39DcyX+SPwSWHLB"
    "fSAjDFCNtH7we6DFszWQLUJkPG0CuXcxkdNWpNBtzMUuoX+d3QmWkp711uhZYqx5O1+X80Unixbd"
    "rJqYfaHtJZB46HA9pw63qEvA3tkLFovokG0QWdqPYubc2XmKOcAo24I8rKUp0twq49cz7t6OcrVo"
    "pREw1kgVaH4m/1xPC1/EmzC5Y1lKZdIEMfNrquWds+bFBAJQcYoFSBkPCmJ0UioTR0dVHK6lUXZ9"
    "t8IUUtOKbBPVsjC3HYI4jKXad2YZxnaQxlSKdF0AwTQP4WNk8H5a5vC/OX386QP4A3/QJMyv53rR"
    "1WzwzgN88wGPYo1KbggCmeqj8Bib1eWhBzTFu9s55vYI4kh+f1LBvyJjf1n+49//SxH8BFQAtbSu"
    "PQTFOY8nFbhbv+8EE4mQkYYKUwWQel2JemiiaJ8YkksARAevKo2aKIypCp6EWB2edJ5KScZWuz6t"
    "aBB8W6kOzEILreyssxUrPI6m81xhuAqwLSx0mwr3rLBF14uehcuipjXq6doWIfybxXiUnhBJgW6j"
    "U8Ga+rnFIWGyuAagQzNQvS1zEoiPE63+uTODMRVovitEK9h+2R62a5RCKIh18LZU8kJjGJ0wUTFl"
    "PQo61Srm41+2kBiub2y0P63qC/cFCU9fsHagopZwzNWUQnw8LBCsA4AksQ9iW2Uj1IQVSRRKiA8X"
    "Wj8wOileRT6JQiUDgZC70RFIBNizzb8o0GAU9aVVBduLlkCr4wkgdpzE5dpaw18BmkjQXmMx8lKk"
    "XCMtBKNhpesm8BhJFwtCE7k1AH34S6ML2w9Q3+9KByZQAoBcwiOq6KDOMDuWAtrt5C9/eHf+ry/Q"
    "rPzKbyP32321X2lbq69+nt16DeqiC2R02H5fVmUdbSIyH559A9IaFnQFHrAqlbZbBIUon8KF4cEb"
    "WVpfAUz1V8uGgZVa/GEFh5DsLCCpAWOdxtjlD3Xad9iigCpNhtTlmMLf0fBPhauVNN3GayHpogEl"
    "/5KZrbYe45agRB0yfKIRB81A2LtwTf5qMoXwzQjpILYLJ/MagO5yZaydWEPkB2kRyBl96IZYX29l"
    "9dR1QdwdO3sX5jP01A+P9Yxlr5wNxVIiXtfu//vfPL7ds+89O3MHw74l4otaPcmIdzAilQiXE5Km"
    "63AsTP69Hmg/e63qmGgUINjSd/EHs2z5M0VjZ4wFFmgofkMChS0xhW1H7gIxhh80or2zocwv+JZM"
    "4tgDAQcXfJFXq7Gs2VLBDEvIqt3FeYBAwGkgMORXe6tJH3u37Z39qDkd/oSP4CNnTznrw6onQUvV"
    "L3HnCVTRFAylBrMBxspjGCCGsbMnhcRIlt5ne65att30iiVG3wOd+XpVcN1/FpUfBHJn82T1EO58"
    "bfvGlPLHkbGSsIEdR8lqfaMZT4HP131ceE2Ob8Nk6W3vzmpT3TPg442J1X/WgGJHmGASVCJ5v5A/"
    "I1Apt9jq6sUb7BzVJTl7TqqA50t0W3+Jn91hF7xfFJlnjyVk7f1AQemaDY0AtjpQfY2BkX82MzOp"
    "mTIhMxSoF3Lr7CbzQZOJzIdaOohbxrhyyJPDhh0rhJ4t/0Xn9Hjk20yP9RKZHf8QB12h3U3WnGJx"
    "ZcBM2+clQ7oQXzllyFRarnJxFgrjNgarSjKGj2IHNWR5g/ZFPn1QEeObkueRJs+GIo2BTk/jcgNt"
    "5h21EYK35OViiZ5gN0JLqgDtnd3nsBBykpEjBbshr/c1h5RtbUEzXZGESoI439Zft57cc7GN8tdQ"
    "8SOWAAyOprnHdBLVazLJ7bmblMEoYsEGCj0DylPO26d660mgjdwzg2cYRPlAe7XjK3ITLpCkk8/t"
    "95wQWuB8MyLLHCofleHyd5wGqii+k0HN5UHVWumfsiWY/ATqsmc6xrDzIJCH/klToiAEz4Re4/UO"
    "zLpTlutZ0Bkr9xsoAegV+52b0yQAta9t3kCMac707tGumc1DHVj2rrmD38FNPTd7GjCDVyEZ7xJU"
    "/heVe+w/BHw4vJtd67rVrBcqap30KxXFq0XLtF9MQVWNVTqhAAEkOJzGh/r+7zznBIGoZc7fZ9ct"
    "E/4+BgkMWKPtIeQRN0+3KbNtIcT5APliEib/4wEyWrOq7aUUDzLVtO7yC/NIG1CvkhLjjYyAX9w5"
    "TLiT1t9pnfIFSKzWfMxEfqf5YKWS1rm8Q1vHgyCNgR5vMZFN0HfnktyhluS+AXoUs+XwhkLcc0x0"
    "rXrT3QryN8P9TgeGObjkDLFkN/zVdmpv8W4LvNMyudsbRwcW5NPi0Lgt6Mvt5r0M8zImrdw/8zd8"
    "n4v3tq7h23BZEC1PVJiulgG2xlLR7z55gIDuff+BorGsed+FIOJX7ykhG3TBN1xwzE7Tbodd9keG"
    "SR1yO6wB+jubZ9jEqBcUYQGMTE2nmLy+GaWoIyDpjYXRmKk5L867R7Eps1x+UISfiYIF5XXJGfIS"
    "d/fPw05e3S15/kUJ6wnzKP4b7JeJiSI8pahKDIXqBWPRV/toQUOlMJ3Gs1VuecPvDPxrq7qx9IUB"
    "ZRvPEoO+OCa0UPlVPCFjBJ3n77uqm0vC6Yrl4DiFQyjglDDu35xbqq71kVFEQYS+EkSEdAbnRz6z"
    "TQv7vTnnkeacpFJSY3IP4zRBFVPGVQ4FmbHHBJGVS3/A0iSkh5rvaW/wEmTtPsZZAZGC/ZFIcwzL"
    "oHblaFTmeAwOvc2DV29faRcyhx2rJxi0k2dlRo2pF+EayxkmCW81dRyrOg0ntMNXcZ6l+Dnb77gZ"
    "6XdVSHG9uIqKOyxjj0L6YwErtGM00wwGHWO7CdiWgkI1LedAcP+HNy+7SNdtZ5mrmU9tXpU4xhR2"
    "tCCv22yVhGXGIdVTcmqj3pcrRsnfbXZpNl8twtRn+FiJYxlgJqCHNLBJSk5GS/hd55aK7Rpv9emn"
    "TwRA5zhPKRwDALfNaCNC26EgukKoHX3jZKnxE3tWFoWUIdXmfxMIUc92q3lndQVS9s4SigOKaTuc"
    "zviYgJRTUg9vcdJhtz+JcLIzRp+FS8udb3v47LA5hH5Z99MQ6+yYIDIgLd5oMEz6svdifkhhk1UU"
    "LsX/VfdXNVCIz56O685tmOH4LPg+S2cql+CAa/VFrnSYxJQoOVI79Cxglk76RRmoMEdOvFZIbmDc"
    "5mfOkbRxgLLkHFRObcy/CCVgGj6Ou52TMZ4yzzg2gv1ZdSra8rHnapLEKU6Xg5+p/fIsyyLEDxyP"
    "V3kejMPIZKMA6IdLRVHJRHrZ862TYOL6ynS0fBOKu0/oJ3SF8xnNMrX5iDjElSCbolNgerIjAPxn"
    "FeDRilAa1F1CyMj+8rnJHfHt1U+UMlFgCNB0ikE86OQk8qYd+qZDdTyFPfiC3Di56vHfAusmFsf7"
    "DT4MhYlRpYsqIBvQ0LCOSD/kxvagPI8Lu7O9hy3RbDkFCb+2+5mhjARulK7tAS+OUop0hM/RI47w"
    "4RMosehaFK5NBJFEi0p4iU5JI66PgWEYWMGtwyMQCiiuUicFhCxOcMoL+YWQKEeUe0SRR+9ZsTD5"
    "c0CPgJdyRpoJEWvBEQwvoZELzNCgmKIJhjdpAiABRBh5cA34tu5TB3IMMELPlcmGWpDUi0AGj0zj"
    "KwANCi4qKHqYOOcCsAljqggNCwwRc3LjqFEq4mCZrQAHJbxmMs8KJfoNxtGFFATOKVrUeH6NmlIr"
    "ATB+txw5ZnmdBdSSFeN4MTJDyBzuwZtXgY50YB/l3MTK9wIsgiChF5NsKd65AoQZlGcs+YBNv5SD"
    "mFKzV8JPmGCfmvxI4bhTokIs/vRnWU8Ola0tMxO0jp9jboTg3yfv/ld7GGwIGiiF7Gmhla51HbDE"
    "9epoXty5d3MAVYoGYxrIAmZELe51ZKJAXxF/6C9AqJxLmC6H/uaTeYwvhAV2OMpTjgl10TNLfNIz"
    "IRWzVWHHMAbIMGs6fwQOOmryC2s8IRChXNEpFsKITJrcFEOLJiGX7GRi99sqzCnE8lxwA8llWOou"
    "U2jzxmNBAHhCerbL0/k+wooM5Mbs6QRz4s3tgTa65LEn0oxrO/vjwWpRaDgKCSue3FunNkXG+0nh"
    "KoqiG5h7EQGQbHAMCNN2AcR6DmjRMdiDLepYYFZSa7y6rpHMYqH51fa4aygRIwmmuy0Wik4YCXOA"
    "GlpNWnQmJKVCbQLvseI4Wq+8Y0RZJmLGaC6Y0Cqp7jo86Wt68LfhMo4we41VuDv7SKQJnf7QKzx8"
    "Q/7ubjGAEKnxNZKBEoOXmFCkkgwNMHt3C2OBQH9QhAj/8L7sk80wZ6yIOoIcFXv9Z/0L9WgP6x0r"
    "ROPGQbJvXr99983r71++Dp6fX3z39evzt893CZa1iqBsGy9rvXLzkNk3lqBmqqc4obMs7So3TatA"
    "K19x44hZZouY6AgaH5XibAui3fg68juzAd9oebcRiiurwOY51SJizGC+ZokSJOgkxhJuVtQQMSgS"
    "q4RJYWQsZXUYAYED96kkgGF4SKFpJ0kuKGxJzpYK3OU3xQWYJ06zQEfaB1TwtMwQpyiYYZqZrITS"
    "0kwUL0AVnxYVbHPiV9v2bYePm2/S4ioNw5mCkYMylvJ8E+rKF0IU4wLAgA3Xpyy6FTIKp+r1MM4s"
    "L8V8Tp5l7DwCWIKJrCVhWZ2CUEVh5nH6h65Qw5Z7utOnbAq3yNM3PJnxmlMtqGwNveJ7H1AuKedt"
    "A8hdA5uSYyhEk4phyTMghC2Z6HgfRW147+x1ivXBJ5cbHr5mMQ+GL0kr2PC4rpAH48OeR6ib2s93"
    "rX6KuZJti6ebKQX/da3fPLZhmvwtQHv4z4ZHwxkvf0Ym685H4YgRIy9K4iKdjwJJkjnQwGT/b75W"
    "2y6bgxYKpXGByf5vteDDC7pL/LXHwcY9HWvcC14+d3dZHjYIqmHbsRdO5pet9kKeA3ViBsAKLuaA"
    "SfzL4aXaYGfkOFA/9cvyw6k4BZIhXLTNdTVMRxoajEOqtVxHWryHt/gDl8vYKutUT9S8HlXoLPpA"
    "ZUcIlvGS4jPdTXsjVy3UbjFEOII/ssbRWeNlyl/zWup1hQZbyXOUB7WuGWGxURyj+D/+63/W1LfC"
    "dpu/bTmaoQF/0MMZYnCD0SoS8Y//+n+a+Wlq4Q5YsxHXzT14tOZ43EzkSu5qPVgsUJlkM/dc34bp"
    "pTL3xKrGTHyXEyZzE9c6YaUGjV0/XfzLN3UsQNcHWqlpLdfF+2kfr9QwIaDM36/2KDUTBwG+ZtLO"
    "ALBjgyQ2ILWax8ZYhYo+KMvkslT+/ZVHAEuKvfac9DEJb86YLM75D6VNg0ZcBHYcRpWp33t0+Mgi"
    "XNaOji+SnRpFJ9r3KYphWqnf5QT1aFo4a452l0hbXAf54tJUtTO2GXQTsx16Z1zjIZEvpCn5rmVo"
    "jNFYq1IMeerGA0eclixpPpghqs0KN8BifaBbQZg83Alh7bBDVVB1vHvhgtDXcpUqA1Ekgm2Z0zsW"
    "qKKMF2G5E803QxszsP7EVTGwDuNuYUpxApA4uuWLNzlxmN77JnianbjBkZsT2I6qyNM7kBXuyVGJ"
    "G1MW90FrNYqtWGdJdqwUFNfMhu+QcmPqXurfVfCCHqdpPeMmIB5FugEmzlfnMY5/IXkTleqJtA2B"
    "iBe3TRnaztIGS4oFITYKf9Etb30DegR/EF3eWLeg5DVvVbOgVuUCixP3eSI0FF2Q36J0/pBZZwXA"
    "N2EPyGSVU+1J0dAGLYVJGCpaQUR3cKlDyDukGhwwWPmoFvGHrc9eZFamPqSc4qT3OMFopkqKKhkr"
    "SjwL0K//xPrQPC7Q2cD+EV6g0lJvs/CIkz/ZTgNr5Ygpbr8iSrCFK4pBE08TiKrC+FqzAjyUT1M/"
    "Hp3duxbZM8O7dG8L2ne39O8mNPBNNffmcFtGoROyUFVuDpvvzjhE90B4Ha6FEF01aWGDHu4GA+9c"
    "90CBEToBuYG2OHOrqJVngHqFDs9IWSI2Ft4RM8jexvcSqrXteZUXVuy2r9Gd76uVOsWp8uLpycxO"
    "bbm/1kAcmFIfp2Obq+3RGV5de4IqFR2cs7H05o02dbLlprqyAFJMrowZA9XMphZJpLz4mJuBWkEL"
    "SFQ5lKjy/SVc7fHm5BLovHugku+I17c7uOqFDSfE7mQauHN7LdGIX9m4vzsusYqKRBVkmnAC3FaL"
    "9b26YdloTdhp0RKCdqdLPn+JFRXRUb37mi84ele/v2G58thOK5Z3dsej7aWfutCD9gY2KZPgQxZK"
    "yg3BkAxttN9KArpnxanxgEi/bOVK6Vj5CfuzYwr1KJUdp9Osy9Vejes7MYVLBa63q0RtLLrlnAKN"
    "UwseHofRTG1hb3M1CCzFVjPAmf/gF+B/XOiEFhxQidB1JlXXyT74BWx5KRVsddk0fBPXctM5N6x6"
    "zUm7Zr4Nc+YOgawoO3MN7oMUwM4RqyIie1z272AhPoOi5wAcC2PXWtCnt8RQn8jE28JY6oNUvJLA"
    "icas27QdC/QvDAIh9GPiP3ndsHlXsFpGVGlZm4RBvwFlZ+LC//LMKugVo6bKFaJC9k7oelFLHDCj"
    "UmEUIUxs216M/hhitR5D/A/OGOV15gTCNPFPFxMGjG3VHgkBL9jOLeh47kBIdZmcIRQsZK7RptWu"
    "mVo7WNBjE1JvWzpP08YtnPY/vXjxr9//FVsovPvxYhd3ve4Ssq2vXj9/c0e9xCAW0l7EdtFbhaD7"
    "GBllHq6kLP3a/zT+eumRkUZcy4qWwxLiqRUlrwPUOSywiEn7Lno6qpWaYnF1YF0a9wVGAOioKh6w"
    "0CXsqJ4PFxGh2qvYDIPUeo4wQze7WyqrcuxLTQxq5gDn2OHnv+DOo5TmJkX8YDbbuemfNb5eheIW"
    "2H0X0ClbFRwfibZIrLedcZl3Xin1ZBhjsDi9JCNR/XT8aLtzfqsyX835LWudlm5TRgvrJFL5PtJG"
    "5bDvYNyXvBNOua9t6nHhC0vATtfPSiFJFjJKLx30gnLOie1JtRznvlfqbnZrjXx8dg34vlxqdtS5"
    "Zwvo4ayPcWVhYleUcoS9EJ1Ee+ZpjBtrOl2tSrh9AS7nmaUj+QZ5jm2c9yQUnsvkYFJJs/ycAzUY"
    "TxqXEm2EHSncBA5VMLrpku24eSZom1CDQxJLCpul4B/apJ7ujcMz19E8QAFUMq2mwU0GQulIgR0m"
    "qDEEihSLccK2NLgcMWvdht/8y8u357uwGW4FtS2T4advzmKYEDvBX++8Jev+5+Ii1MOjsjekEq5E"
    "0cOUxIDkxEhjdhAXPkLxGBU44IcLq7WE1UWGUlR0JhdWUWzlAee6p4iuQ0lFHidZmvL5S61GnY5U"
    "mIiv7djEeVCk4RLEc8MfmUMwx/hP38M5Yhkr9EoS9uhasgid//bq/A033iAORcEhzAeJSUZxRFNe"
    "hMtb8goxu57KLiHEI/z2xZTsNuyr0q+C++dWWuHd0H5y0p9aH7mDgU3KDNCuNZExOoJN7GU+0t97"
    "T9WUaV/wJOggpOgB/a0t7RWlfU/e/5+kKQ4CuaGFcv4LUEU4+6LMrChFNLDhSVzPY6CQYnW7xohG"
    "6oDeCzAQiOrLkigV5qJxhKmUE8XG2wBq0wGa5qU7BjWHo14WlB5TaojCGs3KlAs3vMSssa99Tq17"
    "Qlgt0Qltu2AQvyuysWiLbAwLW7DqVdk5SAKmGGAoYZ+6pRpnAccRZxQHZbYccI1rnerQSSsacaPc"
    "CWvGmYnyCUcGJnEzN3uNz6RSslUlhXJ2V+8LMQeDZpwY1bXLrzV97NpjAZaSSwRWZLLgHB9De5w1"
    "mpSongYLhkoQ0JWsvSpfAiIt6c9MlISfB1Xx2mtJxuMdojLnVS3dqiizYfn+poiysA/Yw1gYDRyT"
    "6SSoA3deU0NZGMVp9rh35hyOCeLxyRUmX4rSQ8KEqmwEAMmFI2nQsyH2DUT7kQnN3uJgabut1oeb"
    "hRLs3/jy7cW7XQQT0y5yW9nEvHBz8QTmOeU+kw0RBW5Vff8uSF65eTXnn3IsGwqiZqwmqiFSoC31"
    "JfW0W6xJXyR4JwrBvYPidJqHAJ8r4vDOqeKBUowm1ni2MYJIFWXQhUWtR6O0petRscWYs7zky5Eq"
    "LrEKAWz6TLpPIm8uKg1z664MoDouqPpUreMhDIRn8gprjUlrP+6zxA282M9trQqmg63VOBW4x9Gj"
    "DO7huBfQr6oMtTU7aVqHcg6qqSg94bliriEK/2WtED2psVh7c0HedCAeJJdp2yXKbVXjQLxKx0Ge"
    "zGmcaKWh1IbZnPaaaTRmBlIpD2yVVsKaslJqfRIHxAoNGEHWQNa/qTwbeHpGLlHUQuDtM0e0i9dX"
    "TaxwU59lyzhhcTArTR8rq5C9PO4rI42UcEElsFEdCyO0jPUM76i2kfgOTaRP85NOW1T/g7YuNl/W"
    "pOaGrR58mXEHupx01ZIlCdfUdgfEcrLWNDpALO2xie+QCSelCg9aSBddEqCGIJWLo6DslS31MfPu"
    "U2pHhh1apYouM01UQVHUsQvlZ3bXtcllhPlwJvsoNv5VnP9eSw2ChAqUmFX748Gc2BJtYX5pl9m2"
    "E5wJV16Rt5gMXLMwjf9GzxkwwQ4DQHxnposfAgMmriIsA3z/tkJ+yjw7y2NSjx0o6ZGdHGcwoRo+"
    "8VU4WcPbKyzss+5xv82U0anU/Q7JThbmQAp0/yhnzma5OUpe1vLokApRrau+nZhFim0JMdWDTk3n"
    "zLuPwFryda0+ihuyVmW17nhqo91P7XzScmAv0kkmPpX3q2hW0er3K3GbTUECx5ZTyQIBOOUsIylc"
    "QEyApmyoGj0O4gNpqGydxPIxcBjjDIbm28uEI3/KbJIl1WOpQfpNx9RFgnnmwObpHLifJaWIm0rR"
    "yBh7lGpuOqcWUhyqp8lNwU2rZiu4iEUyit/nLA9vcJarMmtFwGcYq7Ik6xOGq+kQbl7scg78X2Ff"
    "l4l75CSuinCBHRi0qLtUITtkyNTGVAvpG/fqohoxm06KqkBwc8uCZQQuD5pSXQPJmDbp0wUaE1Cm"
    "3mazq1Twdk+z5WumiHkytTHEUlm+ckWl8Ej/zKY1T3N3tN0Geoh9WMZn5yDzX8WzUJLAU3TRlpwd"
    "Txop8DzKqDE08u2L8+evXjBTGGAahLB9lgb4YOAY+thpMdFPk9GHjIgLrJlALXRXYx65EueuM+rP"
    "iCWzIqCLWCzJdHXEsuCg+zDzQnb1dUYp8b2qZwzybapjUjscWWedGvOhwyZrel11sIvQFs2b8EZX"
    "aFroyrdlxkOVykhRunCZbmNNoQJUNk+8FRkrLfp5XAmtapVSi8pBMDwd4tdVITUx4Ooly070IqBg"
    "A+ZoWc+2YSiwjFdhfomIo8/te9DWHEkMe5ST5Cb0EeVvRb3MkZPhxkQrbPiHRGcAu0ICLTVV5wVm"
    "p+RVTZGFppR2xYULqHQXSY7c7jqkKCYcOKqtp4UL8DqRnr6kpWLFiTdCmXltP9C+ofN6EqLMWFUW"
    "0YJ/Ad9Py2Q9wLBtjOIiuApXEYq/2UxaAwMglDn5CRdLXViEncRcpotTYeaYTJDgVlHIFZ3RT3Zb"
    "0h/UdY/bv/6k4AfTFOwlxlLlcxMZ+AOVrMS+jqiq9udUitNi72gKSsIZFlt5ikzw7OcfUyr3lwMO"
    "/fL0AV2DLS/jRBO7QO4jiuhsXEXlfKhK3QLpIrXCi+KCWlgWlYUm1tvbc3+KD8GIxPgJAARCHdg8"
    "nJ4NSEBUubXreA3MCWgDNYbygC4eKXuxKXeCz/K1cdlbJAfwGyaCuKe5IBwVrj5iXcrmA7nqc9QS"
    "CLQvnr3QzWOkGha16URbGzsvqF0ElTSRZOYpEulK+tdNjgBrPlhpMFfkRGOQwg6RaKswfLttqRdS"
    "hOLbFXBvXYJJeqoEY+Dgqa48oguLYKOI5SB4RoZkEjO5Yw9mZREaP9FXCJypRhGF2HBBvUrcQyfl"
    "EzahXccFl8ZQzHEnYZqlGDpC50YUC8ucSK0dC+6LcB1QT5hECGcpRrpQL0Is8rqale5PinUQZZoG"
    "YLSKyKVNQqqDhQvEYjl4HR5EZuzbyu8QzPtx2ofn+7hBCGcR916jTX2eh9heNMqs7nKA8rCPVLDM"
    "vYP+PDo+KknIu0Wru6ZmxdJk3JTgJBWWbGgoeNO2zLE3dliVzYp0pzvubZYhQpSgKlzBFuPdCKfH"
    "/UhAFwdIpn7ytMn29wEGrkQYJFFWMmRhoWWerQsdDu8hoS3CF+8e5pPmVxxitghZayNA1L81w+YA"
    "JZcOYPApCWjCaqSnqkFKimnXdt6iZ0wFjoAw0Lr4eURshWN342Ky4odgZ+OJ1uAJvBZYnbuP9THY"
    "AmE6XJPuiVqaJsNYgYmBtP8inSVxMcfpRNwcsFinZUj9wQi/2tA0nFD0HbzL3s9pgv27lLAaAySw"
    "FyDA4MonSsfrcX0eipZA0rRKJYTC5GWgJMnWGdckbRdOEounlSLFpIjYFGAR7IJaAJWiJP5SsjOB"
    "FMEBUGrMtRFnOW5DUdk30hhCfRI8B/44UZ9VHqmUwoRRNEeVchKuxPyEGEvitBhczbBEemlgBfx8"
    "QoagKGMIbieFL6nmK7qjeH8YxURIof6MWBovtsUPidVCaTjPCg2ihRSQEgsaNf4DoaYIxEGD5bKS"
    "bCLVZa0qYfqi0KJB8GOJriusGkctU3X9J1WulsDBcIFTLtrZp1rDRC1hd/ICRB6DbSigoqRG5fyw"
    "+7GlpYbRIs6Vp56S/KnDru7YZDSyTEbYhF1T7JlKV6BTJtiWvS924Y2mo2+4RloYLwoJBcIgQeyc"
    "nWGLT0o45eF5yYirZJcgc5tlHLIWEMatrbyBzCr0sjgGaDYIUc1c6s6+oOpjdbux9gxPgdzDT90G"
    "+hnhBJNNfAlozjIruPP6OVMWMQ0SAAiQuSYbyn3CtD9u8YmjcAOMHguTJILoBCn+wSC7AGFFNPTW"
    "VL+2JY+qJTNH1dyUu6wUVaZvVnUQl2gRkBQMSSKhV0vGKFIhaUCWQqSLaYLsABDB1WLFrZJrsp0q"
    "RT7Shj8SKcVsAbCAzreFutlKD6uVvstXJYMY4RMZ49y1ESyaeo+68DmyVfKKMXFgAQYLCBcr/BsF"
    "bukRB3O+VBpNtRxQYqDby7Sqf+uWEzYqI7eXnKi0IP7FLEkKW16j15r8jDfbhSNrF7AiH8n16Asv"
    "nO7R/UV4SUZf2hPX3kTFc3osayAjzrhzJ3mJDRQD9FOrdiPlLQWeTPU5MbjE2uedGUcRlkSTWoXk"
    "wYYHqMJoTPIR4kprZ3SbusCpAnO3fM7aHdPhzKFKjIr69F6np2IfY9c8Hr+ogAHX12swqMq6hrsA"
    "kC+qH6kh4yqk3wF7DRk1u77lIHz6AHgyOQoxWEtRTDQFHGjnCjtQSWP78eLFvz07v3hxoTU49Lmu"
    "tbEdLVh6wUiUvoB1T/J4yfUTEG3Jt8LhU1wIc0YNJtkTLN5P8sGrD0iGBjAVzgToVekLPaesg5PM"
    "4FYggs9HIqBahYiIVsRVy1gR1DDAkGRctGOSP00KHeoeqPew0C/vzz23f/1St65faseo+I8rd6zU"
    "O5mRiLceYxM9IKvAi8nNGoF6CNTOON/4CckbMb8aPtbluC895etuvXGLT3XOjeU7yhjyN8d9zYhr"
    "jtD5SD8gX3YqVjhTmIA8Upjx+FcbUnU552EkdCBWI/EvJ0GPLnH+QKPcTH1eZGbUgzlRJ/UnKXZR"
    "P8mBjKaWJB8ZHi1D+Nk9jDBBK1oM8s6Te/ce/KnpVL/JP7hBz8/fnVcoxPREPPP3AYu6cWh/QEOw"
    "EAq48lf4p//qVf/580HwKwdf/KrZApbtqoI3rkNdKTuir+OgXxQ42jO5SnEgnAvECUa5OJUov4uK"
    "1HJp2uBXboxovqTzhXC0WsqQJnXPfnz79sUP7xhvYATMs/iRpOlfgTsQbTI0AW4Dtf0VR9MfkNIG"
    "GK9EzQ6Ec6bBf/hXkomxCItdTA2G4KpHvwaLML+kdUo4F9GqdznILiDV58oUoy4GlB7yzg5uIcFK"
    "JfGYjgQtdWO0u5+KacCNev0VX/u1F/yKzZJo9riPv3JK4K8cuxIavxCK5yTrhaYif38KRBCV+5xA"
    "g0Q1qu+aXeNoOCG00ang3csXby/YYUrwcCewGfzpAQH6C6sbPVNnZHRkHFiyjj3jQJ618VMAuyKT"
    "OfXxQQDit3FqHElE1V97Rk9ahgThVYAQSM0LRY/O8jCySD8OxiFtWAS9pG2AL1FAZyEKO5kPcTdW"
    "ZRWIQUXNucOD0GoMWsuujRtrvKbBTOIBe7+0wnql9LpyqpDNZhA89vu/YvZR8et+r4oDws3B0biV"
    "MMHMhAPJ7v8aFpf0MK59TmXhwyp3CZ8lxTqbTq1MBBzr/q+0Fb/uD0gDePnDi4sLXRkPP5BT9V+J"
    "c0Z7Fmw+WbNCPiuAL7KV5/GUts1ERMtulDQYLTkb4Nlj65AS02i+fXERfBX8DC99BHp5GkjT6r0e"
    "Unc0x8Gll9YlwtvnIBWeBg/hAmLBT5RKdBqMesQSaF/grapQ5ffI0nqyXDMes/AHRJv2+FXa7NPg"
    "572XGFkTZROSyhS+zGmxXJZb6lnj1Tev5BzIcrj3C4+DxwDfeYYmF92Yd4AxMEJhtKnwVdVKUBep"
    "x9rUCDw43ECmRWdzGqyCr86CB7jPdPfv/yvA64MBmnbvrwZS5C34+9+Dvb19/M8fzMVavYM/wwJN"
    "6hys4QcSQXWZODIF2b2lccJcpOCX2kC4U5QACSLxKkl+CT717lUHySWHnYN8Z13a4SBfBa/xT/sI"
    "iUvpOl61wzOtbSk8m7QBPqxvUd9hHZbJHXVWefn8H//+X+j+17oh7+e6IbD0CUamWdYO1/1KAYAG"
    "AuJ3po44HTUcDWvaZmTivyUQVhR40f8RlxVmJr4Dh2OUZsXNk8NoQjZXufOtLPnOZzwHCKObNsQ4"
    "us4NhRPZu1BMcMwD9IPL8XBv47GquhkLEd0RSKpaxj0NJM+tSxaQDA96DpAcbwaSqiK8uI/rkGId"
    "l64Hz7her/KuC8DT3VcEO8S2pf1OoQl9DUZ84xsHW4gOmfp3xC/61hkcaAPJEi3ggWNR37tuND+n"
    "JbDjsmKG3P2hNg3PIdqfQf5t+tk1wOaZCeFjpyh9cBaCDL/FqNJ2jmdvg40HquzFPdeR4mgDuwrj"
    "BPEO7cjFPFyScwfme7lXhz5yoDgk6rl1yYa+Ixf6HrrQxyBBp/Y59oIgxx3tRwWMNDBMY3JJNNCF"
    "xHcKpA4qs18qDgMVJ1yDclXSywINXHT7nFy6JcbDwPcX5vviIWrA5bn9ISRJaNEaBN6viDN5YC2L"
    "ZQIcmaibC5X3Vz1KId5H6PwoxxZPg/sPFvni70R3/447+fdEzcLk7+x2CNMHseZk12GMxpbXqfCy"
    "fXP0nIVSB2t5PtgLvoSFTMvvM+Ct9jj7vzyxpsFzM0PZMGY/Zr/v//B3qMCITMa7wbIQSpFbzMWM"
    "WeGO/5hTKdvHx20KgaEosiejfXLBWnfqQCgWsD63Lm0P1s9jAF+M9XwQVNKU9JewYRskG13Hr5MX"
    "Yz8tKsQkotPnjDJjIJIBbSBIpnjrmbbQoAZIbq5O5kteO5KciHwI+ZS/zVhhQi4QBGWzrjE8dEl7"
    "WeCpwwhID+l1Lev7iO5qgAY6oFcINh62DEsUOY/0R+GZXvqHlT/NSA0OPBHPMPuNJ5RRGORcqVRr"
    "LaZK6Y6cVxp/WEDy3LrUASTw24ESol11Gfs/ccmwhNznaRMsYkCez0lC0uG0aI+vEzNKc/u8xpwz"
    "OEjQvnDcyisqcFUHE/yMHhwkcGtoqqAKoGKPhlFRH9RkVW6ia1QjYSOLsmlZA0h4bnNtBemgGJ5j"
    "tWjGSykT2jOEQmfn4ebWOR43QCbupk/9wrp0pxzv7SpF82MB1GNhPeBCAo9jsSxKTNT6FvVDJRMB"
    "CwZw/d08ziPKMV7rKhfFZK6iVdI4fpdj4cBADrRQRc2FjIDuGRX5oh74d4YF0z2XAlio/fitYMJa"
    "OGsCjcVpWJHOTEh3a5DCKp8DKX+xLlmQcnTcTR8srvY5o6ANJaY8qslZahALrX8ArlOYGAcfSEQY"
    "kQyKF3Xua70Eb/8FLb540dLoXUh5Y72J5QmNyqOHsQAHUXYQeMb0cwpHvdpBov0eSZ+p3FLpWZU2"
    "llGcMPt8tPKFZ/gL25B/MnluudA4jmjraS9T5ddibVivhGOsMSaDKmeIPYfiuTMyOOWrNKVYHqO9"
    "cekiHdWsW2IYA1DBSIITzWk88pKU6DpbLamDoEl+NA0yxJRLUxNvJRbptFqKIIrI/LDOEFzvszjA"
    "daYkm9CkUBaOERXnt0pzlbBE4Jqk/k3qu3xFAixbpJBlYuPLnvRSqn6bXYBLIGUxiWOJEK5QAYq9"
    "nmmfZl3SLNi6RMhv/SYsrH7f+8Rni3ZjgYii2ibaPzItkfGmzOioJWJeVzhxDx03T5/7gCpEh2ze"
    "5kRf2HLT7YSKgIxZ9pCt59Ajbq+BCcBkg+W6rBlpfxiHKQ5Fa44cLoM4/z4bW3v/9sXFj9+/q+yB"
    "evGj4f+yGh0MDx8ewI6Q4waFFfQMvzR1EC0BF8OrkLCs7bxRK1x6D5HEHv9AaBr8o0f/HvasT5WL"
    "gq9JCM0LTQt5dGJPcSrt38byTAAnMsX0f+pB2fjQ49Ef9af0h7g+KhcoJUHGzEU+hOSoak+HCse5"
    "acRnaEGBZb3LQOxr9c8eetaHB2fy10H8rX/2J7RSWGwZ26ahHbwx+HBkXtWDv3lVBD8W+NbXTM8N"
    "kZPBAayGRxjlT0UIKpLVN/9UR1dYVxG+EEZrvYUiDu8rKoP8zLAcSndUIABma6W0z2MJisyETPIJ"
    "CChAgthXcI3xV6B4rSLtDoHfSHnMuGOl44vD5FJivhZa4NImfnqSevbpjGxrhILiI+Eg0TwfEj4F"
    "VGAYZlGgvZ3JFo5VLLhGELkKOOoSdRj9CGx3PqNsNsuZVHV35PDfDJM0IyFh/TLrazKky8lJj0bH"
    "uaQXIpmCGtnzqroj/jTbr0PkTFCKznEHPZGtm+QTSCjQEuCIigFbcQZohaW46et5RlE6U2qrjaHc"
    "OiIvlIVlCwXrJc/fPMNADmYZ9s0gVbOsjKlLYkVa2ImlCculQpqL7eor5ed7/hVQv8vTYDTsUYcR"
    "Ij90Tbg70kP2ISCEJbrZuQExjrGfcDd0rJS2oChjY2FD1yrS7YHBJJ4NizJ6NtxYHnmEEbFkNkfH"
    "ntm8xc6b6KOUnpSxnp3py27NQERACTiM6hOhzvDGGvsd/9Lb8vDATOThwZeemTxz3Ys97V80lXm5"
    "JFZCwlNfCzzO/GbEkjVdqM4Pju/1GEt9DBBIX6QYX1zcp5MdLMLl/RIFrp/LASwDyPIv+/t1OQjI"
    "mVob8DRfRDRHz534BLTLLEKP5DKP0ffHPpQFxQmZlubYnJIAkJqfEgxSvAeCMOrscVlUdcVm3H2q"
    "BpL/9s2PPzwjuNwD+bJY4bDfK4ouIzsIV7ClWshoMQnXFJ2Lf39DZOq1Vn8LNAXdMxiHk3k9vb/a"
    "ZwGG7FmIvoM4nSQrWNl9tHFLLCy7ixoP/JA53cbpKZFZq6lXz68G+PV9YyxjOHrifj5R6Qz4Cn2O"
    "YdX6YM5AvGeNgUiBQ+jfiLJP7n2ic32jw2F0eDrSlaUAd6SWGPkjZd5YBkXMbEh6z1+8O3/5fV3U"
    "Y7slRZ6gXP6TjlumjUAllEISQNU51j20tULx24pZ3MupKdIM/0K3OnXX5vRvt/12b8du24JwEseB"
    "E5Rj+RjMEWO5nRl3iOlR3ov1TIC8H1jTNTMogJXlKseYONo+hnsjtVHDZxgIjkyH40sl+hVm57GJ"
    "eo15aTInGr/RvZryHUzz46zUrY/tlza27+ZYkd26dzdmxVHsVTdtqzF1VxvtwBTnEWhF8vQLk80g"
    "kJPHMGyAHCMFmdIfdsTYP/63/x01iHBcebp5GPqX1iy84NcLDg8MtAEMYs4Q1/dchB/q4PfClZAk"
    "r0JivDUtprRtaRLGEhAa2W4NX1JfQwqv4bdBniIkoKwAkGF6eiacbzPW1tw2FzTJms5pnqfrSh6R"
    "SE9UA9hqlAev3r7SUCEtS5zXjVGY7EKLWMcpUdaOSEhsIiI8sayt7BMRicfUirbBQe/TO60fVfXs"
    "fbsl06PPmxBdYprkwcIMFS5cWMUtgmLlrKbWaJYFtuuMqzpSbCh1qcQYk9W6qo9jD+G2kKUREJV0"
    "LKwOcOE4VII653XdG5YiaEKAcwzTzKbTJ1zQgwokWVFQHszX+J2iGSbRSG8ARZRYbnbeQD76u1Kw"
    "6+hz8S/fEMuMx1kKoBUHw3/8+38eHdRxhhpsoXG9oAIhVTinWAEtX4LurU11rsKcgnIlOhphhJJA"
    "b41HNJ+vgmcZBwM/V8Dwgv/vv6HSTE3KBwEKZ0j/SGMHaqmkipazv69RIK1KVcmGVsk7lRFHfJME"
    "9xLjxgF6JiROB/o0vRBeqHKn/lWF6AzoX3JDAy0E4sZ+yVgNn5aajQ9AO0I6wAYKdDWkWZLNqJ5N"
    "UW2FByI+NXTKqkaWq1K+boSc9dyYJ4lTspUWPGi9/P+fu3fpbuPK1gTn+hUhdN40cA0GST1tMmUv"
    "SqLSTOtlkk5fN812BoEAGRYIwIgAJaaktXJU8+qq6rWq161p/4Wa9aB+Sv6S3t9+nEdEAKRk5a26"
    "7YFFRJxz4jz32c9vg3k8FTBs1qfgNvHwsOICpYhbSpS2WEko4fpejnJZy3VSxcNR1Y6FaGEmoirG"
    "lmQFriHNQnyFuMgAL8PI+a+aE8da9s1HUPAy6UusUAsMjYVefBm3ABe4ADxDREy5VljB2Q7EaVlr"
    "nytOCvPeqtbjDTWd0S0PT7lA62MOZw90opmbL8HNd3GUWSwp02JoQkmZSn5LfNXeqLK5TO0+Y8Vu"
    "meLfvqlky5T/oL3BwgG2h1s5cwZk+W06CSEcMe8258uc2jA7f4GW8y8CfhhVdqhdHDSgGQJPnQZT"
    "JA9itToC3Y0p5OXCT1GHgm+iN2vCggJHejHOdY3MBw+uIzmbpNXXQPwhbrCxeQ0xBvJ2nBGjfsbu"
    "ewxOIMtpJE3ty4jGey27QSHRze9QUhRn9RCZNdUKh6F/hv3O4QwTjk3jADksvpNVnC+KiSvK7Lt9"
    "wdth6N0JIE9wwy+A/3O0SPnHcfKHJHg6ZCHx2IkSb5Oh2wadmROxAKywJcbX92JLl015JBuF3x/T"
    "xhzKzoHhp+3TX7V9WtprfF8alc+975k0I16x7K798OmLR9/iKOwfJh/t+M1M8M8OxTSdcdileLLm"
    "IStMkkBu0LhgGuDBjCxaya54jPOasw8PzjKHvK32GvdBhy/pIwiAZTf3T+c7bP7DqgcfuhAkxTGD"
    "83m2oE+z3UZIFhcSh9byjMSvUl1yu5Jwei3Zef7omxf7PUbln2ZDh/43zM+njC7BMaqJuBM5kErx"
    "zBZXeB4g+8xNZUONOExFgbL7Ae6ghHXi8Dqv3ktQjYAoSndo43Vubdy6t7bxxdrmpsYGvKwnB3Ne"
    "mpJijHH1SliocMeOilM2EuBO/923RPLlGmC/BDqxSGqfBykJizLw6BO1ZcPzI9Rh7O8+f2zCs2qE"
    "hYN5m/wKL4A7yWe37nb6Pt8XycxfbGz03Rfp9727G3Z3a61NqnUvrnXrXlzr1p2Neq1bzVp3bsW1"
    "bn/ZqHW7Wevu/Vot/rY6vG2JlzY3ciyWHmXv/dDpVuo8yU9AX6gP/QQZZyAaKq9PY+43uPYOP1Vm"
    "mMYnTj2+vWfZXNq719LerWXt1Rj7qz6yM9OP3L12p2+t7vSltPfFtTtNT1WaiPt6u972nxYTafvL"
    "lrZvL2t79YS0fGQsH9nc7F/zI7eXDOCOtc27hmWoth0jetZ7X1DZaOX1+aZ/Loslz+/ebZt4VR5/"
    "6evIpOnzO+HzsX++6fqpPLQ5BnkR1EiOxfhrhkCG5SOmfA1MuXCZRIl+CGRmjrOZONNnojRSjV98"
    "+y7O2fi8zcSRuCLmmpZJXMyRxKmbVfzyVOrRzsudR3uHP4JOaadAQBIdnabogm/Y6ZT1P+fFfK4D"
    "DJQ3YNCkbCeI+HBf2XtGXzmsGxlMqekNl6arX08Am1+d1dTvgNwSQ4RVYClq3QHZX8DXq1aH87r1"
    "wzouX1ytKMSruHlWmayboFErDtQ15MIK7K4WTbKe2MvAghdkAFs6iYb+0jKH+3sH3/785OnOH+vT"
    "+PzlXmBGjGbH1PHrCRXiu7Y2hkDTXTO+7odGEYWFqFWua8H9RNTfhLOgyTOcnogTLaTJt/mMJOU3"
    "tIPGl+qFcUnbFaLYoqrx0yZb8an2djD1jnAQGpAlapg8pRM9g7h/dowW9l0kNAYz8ArPekqUzyxh"
    "ipz0TGA8XKIU5oPMTmhEQDulPS9jXfvh9wc/f7N3cPhi/0dbW7EbUbNbxubcX7t1n6ZY803QY+fU"
    "xGUZ7i7Uo6iR6omY8mRuwloaD4H2udHhIg/0E2qN3tlb29jcMDFHrDaquefcUN4JR/WToi3lareU"
    "vxf8DUmC6VCYcfzMuhb11xypVnX4i81/anYVWDQuMetFlLg1Tb67Jdo25tx+dzv98hkk/N/dSW89"
    "206Iz4F3I3TrrV3igysAB6JwuKp7CRvxm110OlHeXJfQJhhNSHnONrgnZ0u8pxkSiNW36mGumTuy"
    "UP0hyQj8OFSRp+lF2naIWnBcJFm5OHFa8me0VtllX405eNnQ2JnOjvHNBoy9PGnT2SWymza+TH5a"
    "bGyc3E9+8C4F2WR6no2hO6w0Ape9Wu6ICGW2PaagfBMnm6Kgub+xhl9qr48UzdatncGAKIukZ9DN"
    "wUYk0bau6CgNWTtKE84AO4ztsmZwTdbFoUazpslTun/psp9Uxahg/Tzvwm0Pk6cxtDBAz+aA3XpE"
    "TTuMhlA9aH24ZX04RHz6nO7xcTYZaOIUhXbQflxx2LZ9rCOUcIwOosrqtmk7LBQqVkL4gri+T7Ow"
    "bBee83qasTyVKCXnuJRnAJpXs0e0B9pmasO+zoFfghAqd7BGOIGW68ch6sq31X+h9dOTqdpgtA/x"
    "RB23EIpDuO0AC+gA3oSLWe0wHdKlzqdJjFWrTxOH6wowvzjtLZl6b5jQwd32Cm06t0kGB7TahKkO"
    "TCtsugooXzNBJN71va28A7ou3SGM6rID9cdUpPGX1ZYRRV1aMexTi3Mod4splON/VTgn1SorvQyu"
    "Jz5zdaIJACxNiNa+/82zzfAWV238a/TPpgD9UI9S35s++5vkrDQXTkNzjp1OW3b6xh373Lc/PvKO"
    "qXSegdMafIsVU+Jt4wxATjhBXfAkZSH4jsRtjsfJYqKQL8P2WXkiYeaMI+BCXT7FvKhORSalrz6D"
    "jJXnTbIQXoZTcXd9PfmtNEC9btsYmo84+W0hQHL09xcT+G9ZWI0Bix6eLeZCDO7z1Zp0K+6nINuy"
    "91/vyuuWh/Il54D5ZOsgqvzGUWrbiB9E8MFNX8gqm8jTuNvbN90PwmGLalidZ5cMlxjD5BPxgdFw"
    "4XLGgKnmKuj2pPFqd+7IRVKbJmcv93tXmci0QZNwNHW9XmflcpogCAZ1hq92ou3gu0bvcNBG45RH"
    "3RW16AAWngkDF4tr9GsAMEBZceceT6/aP2VuzZWLD+Cm4/43btfa1quVtwE7w6vkEKakwTDVt53T"
    "v46AMOedZUq3ieyUxqHdfUWomC3KswA2XdCqvCmXYSEFTWPFhhNY6YD6gGt0oJSr+MYPoULcEY8v"
    "wJypmPyh5BEXCZjM2qnVb+QYZ3MAgIgbCUC9OUOBjXcbCvwrBbiPv500SKW5ZSWJS7Bc9CGkeFFv"
    "CWZcGTaz5eMfQOkGZ5mGYtfO4fYVJ0/O0FIGosX7ol2Y3/jHCPObVwjzt5i4mPwDbwdWh7Fpc2Ke"
    "D7w1tkNjGDJh2VlvcG4fK8ZvfAIx3pwsmIb7qh8uyGv80W+U4s24v1yM/19HNO9YZ9m1S1NnuGim"
    "tPNJpekPoEtuczqHqu2QfVBKZBcItuqnkmE/pJfXEyKNsj+cUztngVPyv0dpkqfoNrbL+FLUGC3C"
    "4jLR0sedGK+tvAWT13+UzGlJiZa4I36MuPcPkL/a7rJ79hndOrT5RiN1gkbSxSoYIjt6OQz1uiPa"
    "v7EsV+drXTwtQz+GeJKZ7QS3DXCv/vuWtogH1pl6OkWyTNsfnIYAnIPxH+qSxBYD3rGnBlKrJ0tv"
    "P/U5YCe/Fn7PLczO4TMckDO3PwIdpbXouKrfLmltfLiktfSqjkblK4pPipZzIOWn2SyKH3H+l1Hc"
    "FN+5QkP4WLDDaDGZLVwmE3hVnoiQI446HChdJ0Qv6ZBCqcsemO7yYTA74YMDX352tDmn+/MsElTs"
    "klLOg/f9Cs3rb5M+PuSgKhZrm35MWWDhxZuUe0RMa7mKfn+gKKBcZ8z4q8vtNsm6YxEKTRSARyJL"
    "b7+BapYGROJTTlbOg3a7jYyGxi72q/2N6vo13hR8IfCm2r4WV/5x0sbm7U8gbdQ55I3lokYQUeLZ"
    "5br4IB6Q/8ZChAH/uxuH6JyRnN8uNNz//7/QcEgzhyijsqnS+3QiA9zOM63otQ+1I8eZgTh0ijPX"
    "TBTOgHMBY730+uEoWA2w+GSCgqNtxDHDom+KGdXw/JWa0YN+zuGqKipohKqJCo/T5NsikBIeAVjg"
    "IJ9fILLy342EoGQ5d+gXrEIUx4eGKnW5gHAVX1+XCZjef7FSGvkQ89MHigWd4NAazJrk7IHUaglW"
    "LDl168m4Ngfu59w5memYFDLXLUDAWWMl2TeAro+RJJ/wcehE/v6dGzW+sAP4SIKSRxoNnDzZ+a55"
    "2zoGWPdQ2+V9/SOtCnDkcwNbeTu9E/HtHOwR+d39ZnY7AMFwh4wqgwtfdZ1d04iheUO4E3fuM4WS"
    "CJLkzpdN7hzs2ytxkK/x57Xz2ti1puOPCEZELD5+A38i9vm6PKskum7VVG+L3UKWQ6J/4Ejfxq06"
    "WREISuxoyXuIA0Hdvsva1OYOedgDnThjt94m2wauVwaJnRRNnrXo6ph6BUcJvz3xVHNpKmJUahmJ"
    "h0W4cixUFBEuQdFHXNSCAiuBEDI8Ngerhoy+FyS8/bXjbsxGG8mLGRg0QAduJSRn9iEfbiVf3N3Q"
    "xukcs8u1hNgzspR4laqnqPJXxtHBob2fOCTWLYNh9QAzWka4Mrrk+W54uUcNJQ6UTMJojNtGmnfA"
    "Hx3UJgXyR/0rIFeOj7+7tnm3E3rf3wPy7zBHzE6Jrxxp7yXqwtW7tbYp8EAG9b/lYyc27nPQtcTs"
    "69Mv1zgwAZskRCFzO00zqnRiVDTeB7fCfXDOmdecxpbxdMXBNdgC5qNKvE9e2wEhArLtgj+lyQ9n"
    "RcU5EqJ98I3Atye1BnUr8PzLXvBLIZvhbrQZ1F1YnIGv3AyG9BtuBxKOy4/aD4+QIgPJJeXE/z6Y"
    "rHBr+G/K5pCh+U0hv6/eFfdpQy3dFV80d8UXa7du+10RSxktO+G23wnLVRF+HzRAO2pbwbCHbR8c"
    "EA/9KqN7IdoE1krpeBO3A+6lX+gG2ETkyzJqoE7gzrv7H0QPOq2eQJ36lmDhE+xGcxu0UYjNW3UK"
    "cd3NcG8VifiybTPwFtHN0BBEWvbDHb8fltytfjO8mDDGmldRrKII+2nyEklBoo3wWHTrZbSjrqYF"
    "m7eX3wzXJQrS/JX0oB9539d2x+NltoPYbtDYL49bZ3UV9cB6EiW4vXZ784qNo+rtTvsGuisW7fYN"
    "dLdtA23e/QBqcje8VxzyD+QsdlkC7xVfKyE8ULSFAgRoh+XMYniNq/Af+fNLt3Xup3d153wZcxTR"
    "JeIDW4IgEdlNn4KcXH2TvJxjdUoIir/3U3Ml9dhcu73xkdTj1odeJff94jflzJYNcM9vgGWqXb/6"
    "WuJ5XkG7e/UGeJomz08Xl/kk2gP7gjREcgwt1slCD5NshLvppm6EOxtXs5bXvkza+ImPWP8n3gR0"
    "vVvjysO/bN1vLzn09+VNc903PnDd7/t1R8b6XDGxZ5deyPfr7krUltzlW7EFD2z0dWFCkMaClq6+"
    "NW4tOfxtJ15ugw+7L67BOirOl4afXyVPfCzLSKd588O4hM17S4g8Azwg0ffaOGORYjJkHPO2PfBF"
    "QPxXaXv8RnhcnBYVXZkPs8mrFi7Cg7lfIVxaO/TZCULHg/P/pW6GexvLL4J/hGhZC6271t4AVLhC"
    "wUezdSVl2PhYfvK2VGzfKffaRE5RIShlKMaAMn3DLogugrC2K770u2KVA7LfFB4jMNoNLqvWVcQh"
    "8lW+Dl34EMGiSRc+rXC5XJKQAfxmwnBv2XJvtl4Em/evz/1xCwbJv9yp9rrH/9oLDhLVNduMSy7W"
    "u87SR3LEtZf8Q68Czk/WBInrfICm6VOs/v21W8uvhVutqx9oEh5qsIePDGBkLTOqZHEsRtv2CJSP"
    "7U43kcaxBiUabQ1D9nf5O9Lk4RyJGqJ9oXXbZMsv3L2wWWMMby9jEky4/GTywTUpwtWyYqsSsiEp"
    "bm7evZYWcnOVhLjZdiXcXsUsJt3vbvfadkOgglzuhnFNWeHajGPDv/ODicQ/hlkUB6bAh0SgTOsO"
    "tp2PYxo+EfG4s3Rb3G4lHl/6bXGg0QiiYVZAKYNrddGu7JklA23ZMIGmss2J7ppb5dqqqcM5e/Rd"
    "OkP/hyupP4VY+TFixnK5sk2tdD19pIn3S3fHFx9iuiAJ88sPYCzuRLkV262+17NVXFOtFDp4uHW/"
    "nd7RZb+9SpnwP+ui+DA71X1Q+uspEzeWKRPvfaAykaSHOx+mV9gMFIrt8f1+2Q842YDlVfvYGyJu"
    "xbOmH6he+F9Hp/BpiP/GF8sUSHwt1Baant7yC010XldDfL2AQKXouFsOPFdSrwEbVzIZXAXRsAye"
    "gTGg4g7e6tTTC/LWClSV3+xrQg3Em1Un04Dv+Ial+P28nC7mTAw+blvRFw7O2JP8Q66T2//TttS/"
    "GVexTFN1X66kxsYKzRGrN1aA1hzurd1aJhWseACDyq4Zu35z7ezZYja7J9tKEZO+4WTlxMA4xErF"
    "GYUv8nTE+JL9ZFGKB9r4UoATxSOLsSfPsnLrhuwthksFL0ic36Ti3BdoFehk4JPQE9qgxZuEk8tx"
    "SgqBgAeCe9lnpFrGKROoME7xkzwR57iEbfICAMRAUGWaPOV/1edVQHCBSX8JPxaSgLAPGGpSNuMa"
    "dqJsujW+WBRRdE1MpGma9sK8J/wR9fWZTJNseF5MDMk301wU0innEERrMmE+kd3bU0iK5fqf9vZ3"
    "fj7YPfz+ZXoukdUKnuY7uS0lf6Hp/Pk8m6XS+Bo3Xqa/lJKnWjLBDOCFSoU0rhZLIGhQitMjIMO2"
    "lNIEdR4Au134k2lmK3fIMex0CW4pD3WS0BxNArQLXvVnj15K9lDOa//Lr2NDOOakZTwrjMjNHkqC"
    "X6q4nmWObLsME8xjMFQu3lcIcWDQ9ADCiifw2c5LBbvslEUFtL/OWVXNyq319UsicWvYddnkMs0q"
    "dnPIJukkr/iUdahzHUkQBk8yamVn7/tHyYv9x7v7ycMfgTYm5TTDwCEd0k5AgOz5I15cZD33vE5H"
    "Elx0DPm881ATowd6IHlxOE0eT1seCyEOSPINjWePkBJD9t8XEKeFwH1BXrm8vC4zV8RAuvr7ovts"
    "f/lyPj2dgx+JFNrutaSu9G5U7oVz5/Gti9bDAgg4d9sB0wqeuKPOY0nmJumrOW1gcLfWyGHnhyly"
    "ctBUsoG7nI4vLKVgB160T9hxh6ML1KWW3/Ap8KvEq4af+goVhKagWe6vL23l13TlQhWfvqkaq2hv"
    "hqsW0bU8bKykvclal9DX04VpLpJru6ytlD2XVXHL4+E3O+AgOoyHaITc1teUZMyZC2V3r+gCjWf0"
    "qHPAcfcvmZZzdl7+LQjoFlflPZc7YCs64c3eQRrV6IHd1PFTTZ1+/fXU+8DUZBFYZCe4LDoeFdI9"
    "hpi0xvCOHv6x3i508R7x0R6bPB2AOwazrpWuO4TJrOg4dEbq/umaunrUYRc7k+kam3QUwbzTCqDo"
    "uuFYsg/oi79RO4HMJo9Nco+EeHm1mLh88Xgd/gw65Di3D+gQ6rR0iB+3d4hfTaaVr7WkO8LBXqMv"
    "VpQO6YhpmcEXu6aM2b1WY1Z4rcyrZlPKAy9taTanTryRMXPJtfaJs7eDyFdwzTwFV3oR1tuYOS+R"
    "NfURWeI6Ei42s81MzhY522v1Becm3sLY3vxZeUd75bj12uiZs2TGEmPFH4eXMx6u5PR8JxU7nv6Y"
    "dBFTl4nwA8ET4dr3mTPXN7jdDLN3P3stbC1j9TO3ZDg6nLWw75K7EKfawnWtrYER1Mxn8gNmhhyu"
    "qVSJ1rJkA1XlceW973R2gow7AoP+wJIfzlA55qcOnu+8PPjmxWEiCdC326Hwd58/Tj4aJd63iC8m"
    "xMG9JI7ro9H1OdEi48XMaYJ9/qhSEHjcFIiIwKkgYtYSrv6L8dAyM4DR5pBfjtvlQBsUk4YlDYMC"
    "1Gi0AlLgMn4Qggwk8dHWDdn1ayvW0f23v3twmOy83EM+oFe0kC51Rz65KObTCawl1twKrtv+46SW"
    "Ij796eDFc+KvMw2yyDiPozUFo9UwThTQsUSWM6i1E4bdYaacthau+Fzb4h6yhMECHvPvklUEqn1m"
    "1DWyTTOhIgfKYixg0QzTr6D7mUbzlakmEvUpSqpsLHEl+M6275XA/J9NxyJZEfsHWSkb+4yb+L6G"
    "SDkRQaO2+ZN8ytPkiYpAHJatlgkkZGKJseBDxlND3NkMyXKgW0m6HadKO1Cmp4cwj4KkqI6IZ0xo"
    "ft7cuHV7s9Pb5mqchEY+JJypCzhBp/7CRf7CwltAFUonGXH0xSky2V5grgR+WBIGX3DAumSMyCSt"
    "h8ihhk1NC8ptvj5DRrmCBjwsRghJ/OTJH5SI0MeeyQZ4kHS7PUsSIm/HA3rKeWQOKrgEIKeMEJrk"
    "66TTSbaSspfSm/Mu/TPlLOuP6ILrIjdMknDqSCgZ4HrpkvSIUFn46Zq79PQ5J8em3owLWdxCQMit"
    "O0Ry/rh7aNkSEtWR+cge4MeDeQelD7G83R6wlCn8FtI+lDY+G0HiNWbXbdHZ0pMlLYqSrdFHSfkc"
    "gGFLjq1aSnP5bzoaMbPnIgklbMxNIIeXGXa7ZOHT+D9JbVzRacjPZ1WAW8zqvmv0alfZ+6FlvJBo"
    "ou7vvu1d0VktafKBX24XbsRpNgyijodGKw5CEeTaqqa+z6KTvLrPf9KUVklX1E8914IpM2stQMER"
    "ra5i1Mdw6a2rKzrN5MoWPap72Gpbi4EuNWyRpJrzqEX2/XaZf9wQTTNb69DJdDqOqh9EmHiuulfc"
    "rq7+sBbk49mvQLe78gT94KJhXVVTttb6Lvxj2HfJiSQgE+5t22SKovZqAvEcgW5llc/8ZhMNe71m"
    "YxmeFqNcUBgEp6ALxcCcEy2IItXvvpDd3FrRGdafqMLYz41XfK/sT5Dfrbk5nIr9iulA7kmVRKyq"
    "6NmTK9dG8romp9O1saUmlxxOpppffXb3LY3Oh5EbV83lf+Sk4whBVTopim70yd9Eoh/nkMkBylve"
    "Hn4SYMMFdoT4kItMEiR24HJgyrqBPtx2wHu7FHdMt5k455onSNpYJV1a+wV1mLjL5OJ2DwSRg+MS"
    "LBHJDcWrgtNLLWYyGczYMSXQuMYu17zV43tUcycg5QFnoM84t1FZ8t6cZ3ztauZ1vWZdSrFsOIL+"
    "tDuZDvNekDXsJh4g+zDmgLhE/nmTeILOlBNLd3zm4c62q4VSKSfWBO8h+80VlJc4gNTsilpn2Xz4"
    "kEb0KvjGT5Pl5c9FJ+9LSwHa1/My+f3vE/+Lv94LPy/sRjGZCFvERS1JMhU7Ou5xSjWdpV76C100"
    "3U4nTli2/n90Z9k8O51ns7N3Z3wYT9/hZtir8vN3zNVy4sx3A2qe3dt6v1tPwRP6ofSIz5JufM6j"
    "JY6Lf3LqsxvRipW8YBfhal0Yt+Ynm2VEe6+LeCETJrvEz9eFcnYY8ap6eoiDXaEvcGvkWbACykRe"
    "9HxTO/N5dpkWJf9Lb3pOiSFr8IY4TuoJz3Ypk01CEW317kNpXdtys/6mtBzZX+NvWZl+Qp3YCkbx"
    "3s9RsGWG04HvrB2Bi17rPFgpnfZUxQ64WtKBMB45fr5Fv4VChSX4SZO4ofCk3trEmnmVX0Yv8FsG"
    "2JO9EW2Np7TrrtoaR8erVsXtCWJiqme8Gmi0d/3NRNNQVN31o/72u+P1ns9QWer0LllY2QYw97gd"
    "Hi1ARcM/qo6TLR1AbeTPeXMuGTtWVPvbudYR0a3uyhblk2JSVDnap1WIttjSjnOzK06mVJxQRSIf"
    "Zf5kPM2qbpWqkohm8Hf9n8rj9dM+eh1PhuvPBP2ZUH+eZ8+36f36Ov5Ck6p1OllUyWKCCwKaUWfh"
    "HeoMSh9+5CB+omOX7y7z8h04q3eb72D4eafa0HfG/70r8+qduQ+6P4ZE0bZdc89fJNLc5N1k+o4N"
    "c+826E9qjtEJqQX8a01PflrP3k2yd2vv/v63/6wNBSuLbXLVnuZvLFvMBnm6uNYBQELXrny+sUXH"
    "g65b7GC1b/Kt8fyFEPeq19Y/285zOJoksmSdS/bTgIF4cum0jcKy46kPtUeyb1ZT6uQ1DwJxCbmf"
    "Ls7bGljwHWKG4EDQvJRm5xe0bLVbK18n2SDFjp6wLV2dCCSdEvJGG2dhrSGLGXRgZc74Yn2P3w2l"
    "k+T9ZfnhTJO+OzYNrAyj7o2FgVNe5cqFkjsD426QFlrEedXtpbPprO1+uwB/EG8WZW/woqMjesxx"
    "SMScXfg7Q6c5DYpcRcfkxTm0vGidjsdPw7d33q/R/2/p/3vraf4mH3Sr+LSf0xk/P9o8DshOzBMg"
    "FfjBjCqW9L/wpOB3SAT19xI6aFtTJsSXVRpPvXgrWp0tefk+kT+MHNNmc9YEc7pfC9zJk7Wv2v3M"
    "Q90PG7og1WOeoKTS5+APQuK49vPx50wb6crXm2XbRlCmA+Iid6ruBtRV30PrJeoq4q7KtBwX1MIm"
    "FRdO3U0jX1WTbFaeTat+Mhid2lTSn/R1/J/m8G2U/lZV2sQ8Wk0srv2dyuueMJMR2Ydukaq94P2W"
    "CshY9+37ftLaDhePNtJsPkWyb7QRt6wvuEv5RR/+Ev3kvDxV351v88uezxBMQg1SY/OFIe2lAKHv"
    "vkGRN8xtYAvQv47/YkI36/kKANjvzjhlYNsHAaxzzPl7fX3rCcZ4c6azlKrjRule0yl3L/kr7oVy"
    "d9s3jMpx2nJRObIyl+Nzt2IlseiDaRNypj3JZgBPKqZo3IASHJtIuUIfMCL2QV519bPwguna8kOH"
    "bqscvHiF57q4NCEYU6rOPbyHMDRpP82Gw+6raG2LYflQOMkHbrsFbR9xgu/j4AtI0EBUvSvbpEcT"
    "bC0c0VU16SExc+ORCjgyscOoA4iSISkblbARdAmUuBZluH+kwgW2W32I1M/jGtd+4ZhZWvkLkSiZ"
    "2N5sUHh+eqFMvi14T3/rwltv6aP709fNs+D0+u3zKKolBmzM2qZT9dANYUVIoye7XSINtaFL08du"
    "11t/Rugk1yd29hjC5oC4PjyQBnqOwQ1qTV/z6bLuqh4CvU75b7B1oy1uXQUh7PWOu/H67I7qLaL1"
    "/2D3es4uqlKarktke4QaZwPWrwrJfHUTyPwL6GXOdndxAOtYWvDEr4fsLep+TDzCW8oe8mBEtedI"
    "S5cRPiHU2Ue2OkTBdRqCkfiZgPisqmY51mqFmDiTU6AlqimIigqMlSrQXY+ZupjjJGcZAagJHPfP"
    "iEE0BO+SuJWD7JJTmYA1Op0SdadSr5ShCqddrCNg9oZDSwOvzpLCg3Eu6WfJa+BDn2XEhVVINv7K"
    "M0Ss2UcKBjdz09EomLZiMmKHKyjNghmrz5Oqz8yBDyWtseTzEJ3sandHuqRel34kbNUcDqNphF6l"
    "mCxye/L+hpveHa11nl2KF2IGQgMQnAuaRsTvxL5JWM8sURfCNeIXslNmhfU/8xyk8bX7MEl9+Nta"
    "ZWZOOdDQe0XaZp6Xmj7UXxa0FcRsDUIJgzbuOuynYbBGuFlBP81XGkbAB8napjsmnhLRyWVbLB3g"
    "8GCgBYTCl9vRWbGLg3rRpSpyzEH5j+jXcU+qgBbi53a8Y97eCDeilItvC7ToLgfhlYJVlB5wTdO/"
    "fJVs9qJ2eU0fFqdqm5/gxMDrYTqCWCM7+rXzdWWLOaZfDLn0pk6j6osvG018Xga9NDlkV/iznFup"
    "1C1VrzAvuyROhmFvAyID/Qgk/HTBdj5NERudNTdZIk90M1pNZqLkI136sWZ/Z71otpImMcvOT4rT"
    "xXRRRmez8/e//St+Yyt8jl//jY5DNUDqIjyOZvzz2pg6Aa0rk64vH2jFPgefnHzPfuGuwNHGcbMx"
    "EdnOp54PKCZp8nJRBXyTM+BDc02/iyo66/50h3+5nYPP0u2uM2aPerSTcEh6HD4BhltfbNvZqVfY"
    "do2/D+8XYmaC/UjXT8qXVQJlMcDZSZbxXbXlCS4g2LxzpGSGGtYtm1a91hW0hYtCaBoAD6lJv7q2"
    "KlhhogB40bMVZ4BlWHi9KwfT5ZAYPzrL6T2WAgeGtQZKnUJfbXiDgN+trkWDMUeF8HvbwSPjC0DD"
    "mL4QQxdL0VLO8Qt+jRxDWVuA6auOZwmFOTNeqV0aIl6hLxvCRIj3Ie/H1rhn2WwJh4cAAi7Sxt6B"
    "axOHcMeTW3MghLQT0Sd+FDKV7BCdh3IBtxT6SYfGg/GgF/HW4+n01WLG4hmPbZ69jgQyxyKJwrh0"
    "gjoVbLk6jl71k4u20YVN9LhVGtOrHstzIPP02bpGzLHpi4nql5yc5fsv2dt//nb3x4NgCjSnO4+4"
    "YJkBYk88cs5ZXqvn85hz1TmqzptVDw53/rj7897jsCo/OwgVzLTpYjFmnJ3uDUV0T527uQ716/gi"
    "jYpAqxo9IEIQ35JxcbsvmYqZliaSQ7KhSEgWatRrylAqVdSPRQvr3L5K7mPZ61ZpjDdEIJKppoqt"
    "IuZyYx9lY0n4ZW88cbrxtyFZUU22U8Rje8Vci7wgAe959pzkT1D5xtU4ySbRpVjvVYN3zRLpDmyx"
    "UNialAJQ35K30Xak5wpuI3sceDrxP1vJM+IK0vmUprc7Sf5ZzmkqWVloKonZ+edkc2Ojl6zjn+2W"
    "G8hPFjtUsCTbdqJVuR3OVVydze51rWNYnJnn88W4KiRAwKlAMoa6B0OkpnUfHZBo1JHpvXr+dkGY"
    "hLHxc9BOc4gFV84vzgPGKO4rW3vrQ/W/xaW5V7OnxUI/k8KvsYHBIWwlyydGbPLhHqSZeDFR/8p/"
    "6SMejIqYe92ENthwj9/RxvlRBb7Ov+CXZZc9uUx+7IS8UBcy9NDZ+hE8LVFr3DL68lmJgEzkDIEg"
    "B06UPwePwn/5rAzbkmbyyYAo87a4CwjHyvzna2JHtZKWzCbIsBmwoP6wlkoC9/PT3Tcz2ZzOW5qN"
    "25G7NOIZQhbAjOTLZp71D8GWSEztMwbFYr3NOA0nlB/wyqgyvRTzhzwUSyab3HtRq3w1cpNha2mo"
    "aXwfq5iQOPVBEu6BsmJrdOtQ1BjKv2hIut/w83iZZVm+gzjKB4EOJrhrL3DNoh91IQ3aVrnX9VK/"
    "iPUHO4lsfz1gMKMIKRM7iqBwsyBUVKygUMDzAfyKh8NwJzkN+8WURLO1k2IqdiISjFxGGsk6kA/F"
    "86oS39toO7HigKfRXSKsb/Ynldd1AKu4dA9GHXAQ4WFmHd2FlwODd6a3C1lkmiTT7ncvVLRsqVK7"
    "N2rdjEVNmtsoqDTIUalTKG7NHFymMxvMvNwisQCkLsnw+kWO3OJ8Nr6UNNOLeSmpngA3J5QWFGBW"
    "aTZaOvlxU5pzBBtVvo07G7j+EzWGUW/MK/q0tkLegAPOnBWlGh/SWy1eMuENblGWR/DzYtV9KreE"
    "SikXTaEQ0okqwMBgXjZUagXPJrHtU0m84e7fUOFQEz/qwuF5qB2+ieRvziRwTpsND1ijeN67xq3r"
    "rhpUY2PuEk+SOkX5mkkAMXz0D+4hFXiaNgc4tYs3YGZLLfdPWU2hUkuyKk32KvMQpLl7LXEOiKA0"
    "P1mbAGmIZhEJWQvkQYCByMUcyGvVZo4ix36W1yU8wRrTGvgotTjOR5p1AzEV3NG+sAjQ9LEuxWJl"
    "09gEwl99mAP+RrwVHyRt2v+zgsXzLnhO15SynSleTtnmHOuU3MrXlSrqPXSSDqiP8C1I6T4j5gsI"
    "8nTIuvo+c+89xQho9RloNb4dmWUKjnk4Sznjg3Yo2oIkMMskq+UTc8hcTSgZohDNtnSkd+x22ooy"
    "tT0XeChFggIJj4/YIfoBAyiUrwreSP4+Wmp7ildkxCsVCQDxLceWPT2j8RsZs4r9em2OUnVyDZ3n"
    "rMIgU5cIK8W6Hf1b/3lEC3UKJd7yVxG1sBHipLAmqDLPrUnOd74K4Sy6saxune71dELlZpZz84C3"
    "O4tfGkwc8ZVSCDTHyZncMD/vhTdOg9qeECPJLsSgm/xX3xyXZR9p2sZsxkEzSmDlg6L0CTwvRKIZ"
    "x67GoKUxIbUxhWqYSAHmxyMz2HNVYv2Gm7OGViduprWVgCzQxPZW13zb6LwFZTc1cc58IaRK1svF"
    "m5vF3SV95/aEyAgXjWCqITMMln23oUN7iTsmInxQo+HKzyJKK365A9Yun4OEzvnPS6Pw9bVprkI0"
    "dDnNcoe9FTu5wwvRo+M3iB1C2SWdwIIeTJWoKftWnXdhvLSyHZc0faN2w0cWIQlN0z0tl1WZu0hJ"
    "mgm+V+wKYYj+5l5tahxjZptxWpjQsGw7ckQ9pgQeuSUsu+AnQ6ZK0lK0C+URFA0rZ542kX40Ucjh"
    "lTM9maozfGfP70RJBBk2EySM5C00lACwYNrcZPlJqk/PYuBioHhUwy3uu08nyEZbT6QZmuuS5yMq"
    "JwFUngYyZIA3D8eH0/9UtCHXvqbCy+Ua+H7iU+P5FiywKiC4LiCv8T0JmvJFGVKApLeva+U4jMkX"
    "A85ASykJHAo+DIyDlnIWHtT1RRWSoGc8ikqIr8CPBApPvhVe9Xq+LYvDuXnTN6axNkGpINjHF/Oh"
    "+y0z4wN0wpZdCHrQtoQmBWNhZILWkTgFbHMcQThPsBwuwrqlh3K6QlAl/84ifHxTGinO7bjzq0Hj"
    "QTckkMdXm0gIAbabR2GKQlx8WQtlaelrEFUTdMkhFbTUkDgYX5ijXFrK+YCXYAEM9aJl7wUxJsFO"
    "cCHxumxW/n1EzxaDFAcXBE3/xD0aHMPtFo3qlM96n0P1TurxkUFsZvkqqQpO0DURJ93c33feU2LM"
    "ZkVHuN7XuqdHvZf4v2t8ipV0W4s5QtHT01+qtRkdyaNj8/fhFn2dBw4whuXQYp516h8wNXukIaQ5"
    "YNpsAYhesqqmabIfWIMLxnripHHZEEeuX3fj4HqqARRcDk0eaa4AXnhj91e5rNjJQMP8Y68QKO3Q"
    "KA0YSzRfTDjCKHBKkDtWRMhyGmkL3ICZqZ92F9Wg6w9mz1jOh5d7wyOxh6X8qcdo65+Txzs/Bnee"
    "a+xxLildH4i7ciQoOdayZcvpYZdNV9aj+NLkG04pyhGurKgOgq7DqZqNF6Vfor//7b+WtYle0LU5"
    "NlVKmVer2DHrLg1OZfXwZnVwbu6u816EfCYDrgnEyLCPQjrA3IQ/1BHqhApO0Y3AX1NK6L8m60Wl"
    "m3TVUQMaw8+MVfAgZqw5C7HvaR9y05ZJUV+b9LTlxSlk1cSLajqcsrGbFvM07GVeDubFTHwpiV77"
    "n0FQipuy4DV0rk5l1w+4wXPGzEdj+jdOfazAda/s3zLUeH2dNN+rSmHtdi8FMNAcrr6sYB7g1uu+"
    "rSmzXp9N3UIP0mxB7NvcWBrWzgEz8SyfuPUZOK60T2cQt4irjZ+6uMQ3hh1tmQC/gCrmC0O6GMSW"
    "bVUtMTkejafTuW5v2B+8zzctMLSRQFooKv+8nAHl2qmMBVVAsmkWhjnAsBq/LoocT4fz6UxY/THi"
    "+vmzgZOcNez0VIA0oP5AV6ZZ0DUbO+pims4V7YTOe1nTJ6Gxst1Uv4Ayw+alJyWPFnzLwQrfjR/Q"
    "hG+Aqm1u11pXN9CaLZwr9+qKphP41K8lGf1jC8e7pnsknhWT457sH/W0oOvyrDg920oO93b3f37y"
    "/fNHB15BiSI9bAEfXuBWWRXkEMitj6KRVHM3WnV7p0FPMbM8ACGoyCc8igx4pVtZ9hjid2hyjdeE"
    "Heq6oQAcdL/hILQ30h0FYEiX9KpP/JZmu6AVk9QaAL1mgZHx+IN91o+k7c7E4xkIOsaZStbo5v2N"
    "tWF2KZsn2N3OaUVvmsDztNcikrHPJoPPGfCKA0Y5ywAgY2bhxDvP/Om7p+5ezQYcWMM3jDkPSro1"
    "7khoyM8mr9gXl7/N7rFYpq1kE1mkR0RXbtkpd/7xtV2HJo6ytMwvsPn414n8ok19kkaDxe6Mn8SR"
    "IW/dibHILg44b3fYPSPKtpXUNqXTMRqNMohTV04FiAX6vtC7s+dqi4Zxy/v89t3ABdsW7+xcvpe5"
    "eW/x0ZzSPcTxsQWpptMxdAywwbNfrsUFnaEEHKS2FMMG/k43zJ2Il7xvoUeMS1PqYTmHSfiEbTS4"
    "ZLzmVMKuXKSFtLUS8KkeQw03cGb4u5DooihqedAacBjfeVywF/kA4VFAOfBT/eaaVemFhZpErm+2"
    "SywQg9u0yM4ZVtTiK3oCUkxlmj5YaZpyxXNfScJXzGvqfcOfrO3D7gtv31uN9yumww9IW6t1LGxN"
    "UGLjsxGFSrkO0Rj6fsWcRayvNzo69r4Hh9dWMKxPg6/1W//DKHef/3Hv+S5LBzDJDQtO48zei5KI"
    "m52VIbh8OkQhHoTQQRIYiAx+ce/OBv7bvhGaiy7Z5UpXCzLQrt7CdYetI3hs0XE9xqUZtPBiPuR4"
    "/NVNdIFG3AvaKbidG+5cQgYaltW852LIjhCYRHsFDAXeaKxyZ60j7KK4KHmXITB/6feHj7qoR7SY"
    "iPyQpV73Dc7ljRL+IxP1z2DOsaWtSUqM0RPanD8S8eri3OHBs+mkOnO/pG78KYh15zD0uA1uHzkH"
    "ONN07+CFWsbMxEaX0+YGN3JDI6TkP4WYW2MhazgvRlXw0tC6pAzbqJlBDsCxdp4/+ubFfpo8hSIz"
    "G7MJEt7Hb/KhtKl1wQDe4AM5xIIKP4nrnig6Z2NdTFT/y0IuSRvnU6a3FTOGIPCHRAFQQxx2slIs"
    "7B4vGYbSeVGyJR1Z4ScMdgFf1HmaHEzdN9GpMxoo8SAMWN3lhaMllbH0IGmPGXdNbyD/iVd5PpN4"
    "2QLAEDhh5Vk2Y/UIg56hPbF+y2gE8QxQJYJrNkQsCHQqr7OJBBGk8F/UT4MTYkEKXx4y5jxuKVYg"
    "KB4eo5SVySnJ4pPAWsTXZoQTJ8DWfD/FC26xvFltoXektgs5bMCxecjCEJrwBa0MZovjJkwvwihw"
    "3Tb0up5MgWk98JVzWmpaGACUbyWeQ7wR3L3KIZ7MiXOARCL4afOcl0mh2FDotTk/w+5j8c08B7D/"
    "Hbz4fv/RLrNsr4oJEOFlEByuhALsxLC/+/LFvsdW9OHUs9n4EkMJ4kKn8+IUAR/4HFtYAhy1Jj9G"
    "PM+DAHwtjWNMzYOCby6HiMhkSc6vf2YMF13GTkpCLVye0iUR6dGtThD+7c/yZ6U3k03UjjbUbpYq"
    "6p/kqvnKhcFPE4ZMqlxMBnSbZgNiS5gIk+ZwOKINa0rFy+TUK6mIcB9+f/DzN3sHhy/2fzS+5kGi"
    "/pOH+3S1HojToH+pTy15T9l4w2bSWmPgKeJFlSHiXXM3QI3SaS7qlvurqfIVKW0BKXuH+G0Xo2uP"
    "fNTdL7+Og/cAXW9vDAjpWz6COMVvFLXt4R50Oj0fAv3T+ue/W2dwCOZabmAnRFihvWD/Ri9gSQBb"
    "y8KNOlh/s/cEc9WVKUoxPeoDoefFh8or4Ypiw8GWCim9AR1N4ELbDe7INb6UtSAcaKF4TLawcF6B"
    "MS6Gubu4DVGGuwc2mJ4DK0d1nFLsc33/z9YeHvO9hznhd3Ii6voGd7zswCxSZ5GUftgD5S0XaWSJ"
    "tDKBqtXKOXWslVGFtGsHJDlogX72gkD6HaMfr/P8lXiKPYNykKSPA6oCcnkCyCd4bOImYwFW1PPs"
    "RATVvd5N4g40HY2gQjoDGRLCOcqwR+msYt+hEgee4Cpmr9TXSEvBV2ExeAUPawj46tTa4V7RBD6Z"
    "F/T1jrs2pY/Y0Ox6CNzsYa63I9tqRdMk1UyQCuLg0GZMKlwMvsRe0JRh3WXa5in64bBR+JcqwIe0"
    "17pdxyKRxEqTT5vwMUkX2DD3esk/Jfd7ge77/Y2A2RqdCw+m29AR+OtykF7kcF1oZSYFTnPAmvgq"
    "V/7N6w0hsIAxxLV1JvjgNG8CqJbDxtgHKHP+v09hKOxQ42K8fl+7/kU3hOu8fv3T2gLWxTRK5WVZ"
    "5ecSijiYzqkDyo45NzRQxAC9mGVpZQCGWXkmFgrh1rCT1LyEcD/4sgpIrLCcHIMJli9VJsRiZ4j9"
    "uaG27aHF19adYgR4dmBeRV1kapoSPSkYx5ozIdAv6LtZrWbc0pBBbaXB6V9zJP8YTMfTBbEXhj2c"
    "yfnhW427yDeeeDcoY/UDXYwjyFi+y9Fl6LQVfCtyIzxCVS31ndLUp2HxQ0EXzWs37mPYRUHAnYLR"
    "sYSZwj0hrcAJEjTlKHiC8JYtjQ4EKiVcUMVHMQx9PJ/yJ4uKT+cNTowhrXZcmhjLBiLdBdZoKRCM"
    "dvTRfiKIiCwYzRoQ1nyu1WYh3j8KtOfRJiUbRwzIyUYMNVEwwJ4kbajVPbRMDqvrupwOW0HdKHtH"
    "P67LFhGty8keat/1iT36je8GdS0ZxFZYt5n5o9/aZ00VsVX7rsv50V/+XQ5bMTTGoO6BZpdY1Wfx"
    "JG7WrecM6Tfqvnd8Ba/8zp/hwdj53zY27t4asDGa/vzi7v2M/7x39+6dwQb/eTK6dW9D/hyNvjjR"
    "P6nsMLvHf969ded2lnWOA34BQFhFNjYN/NuA9MJEYnBkP5Xp8efrTYQgUO3X0CIg5sQj/HkR+lYN"
    "Q2Y7vCeyCxKV5l2xD5wUihgDucLxo8H1NmCnVOkn3nfP6P65vYlo3DOGrHk0HeYMW9NLvvrqK6kv"
    "VWHry8fdTjnL2CjwS3YBZ64ufRMGvGR8yva7Tq9fmxC+i7K0rC6JU8YNfypa1Qe2NEdndBPq38pK"
    "Hwf3V6bXCWQ+TaIkBITdprPBfFpqEiOhblt1cAXmXR5ls+ykoJWQS9/N38A936NxdsOrtqiPGB9k"
    "P0AxDhRpVVRjdiX0rXeCnhfRSikt7ZZV+JFx7SNUKhEnuZS2NH9nnDLLNOwapJEaA6EufE7rRS2K"
    "Hz1NfdRfEkXx79//r/9X4du0X+OoXxJje9EFFNJFJExOsgvt3bC44BbpiYxdXZwlqjAsMcOzsEz1"
    "pgqK8At6ZEOKqmK74K+dveR7pLvL+H9uZnV4rrhbjhiGwfaBjhn9Cb/mZmeWXcjH0DB1KejzwlZl"
    "MbZhs2d+r3acCuVVjjr702xIBxml/R3SeYhL2zvqSQoilnblT8Er66jxbzEO+zkuEMKAD0DMkcXB"
    "QZsyNqeCqtBrGSX10CpjwH1qLOIBswus+Q0VxwX1yvNLktbAgL3ZvUOStr1B1N22qHL9Y7qjhyyP"
    "ZydwOwR2+iHnODjNhlC59QWIfcr8lZnlSMI9ReQNbhv6SjGI0uKylg6qs1IYSqfqy9TVou+ueYc2"
    "DDPgec5WQOX0JmKblPRm+bkBNRhELtS7jD0Y9es1yQGsMNtlsiFyDPLz0rZaVKEXDfOerJpyqeOU"
    "bZ1Jtl9iOrmfPDeJEHrzE1YN08RkkblEaIRcEBvIkHf8r/kcDgLC9LlkbUh1Ni3Bf+E9Y+tOZ2bT"
    "xMdTU/I/xV5RHYnPdaecE/Nip4yBQXO0HejVPhPNn+N7b/hAjtM8Tb7N2e1nXjn+r2TFjRi3SBjU"
    "SFgMWPV4ehRjkguCIx7BL0bdhRActlaLT0nP20r0ytcXqUsYiLveHsKV5H2w1c1CyGBxDjBZMoYJ"
    "kyBOKMCOC7jCo4VE4h/jnLgIBZKmiBK8CmHg8GB9rfvT8HOA6DJa3iuvZAdS3ucKlbfB+G5S6+Ty"
    "W4538FbYLC2GgfAGA1ocZXLSKGButdSrLqpDnaE/Ubi3Hc/xS5n8rp/hULXCAV2sfPIox0sIryeM"
    "ABIDJ5WmqQXBewUhGBk10jZ63gtvdLQSGv6hV1IXOr7pdyTAlbUBqoSVI6xeBn2P3ch6KToY7DWT"
    "It/5JFeJhzrIGzg7ca76rElRTS6nppTYvDCZBiBGudV4z/L3n1KvugvaRhZ/qSajglUxDb0VT64g"
    "LUrmwZ/Wf1pX3GUtjKqCMxYlJWwpdENcj4JHARijePtzWzrFwU1Hve3zkvSazFzWeJ+lZwCAeSCj"
    "+jzprIv+ex1MST4BgvT3+3uPLJa7G1R0CqfOzyfjbCI4GxkQKvFsMpXZh+1TsqrMtUA2HO5C4wvH"
    "S5TodgbE+iIRWn6B7ZRfpKB0yARFtwKWoxuxM8wgguPFhGMHyFFTDAS3hHOYTuasi4y4PMNPDLTf"
    "Eh8mfhN8cl2aESgzKn9Xcny6k2j5hnEofnrwp8PLGouER8JK4K82TmgwJ0qKv/QIQ5WA+Y9PNaIm"
    "1xNlLXp1YDW0d3Zb+FawqczrjE113tEoJe1kNq/1Ef4P9FS7mc1bOShxfuBEfQL7ErQd8UmMLXW0"
    "5IAQT/On756y8HDIePcB5XGxI1sJ9Z2HoBEA+Pvz5BntJWKfIg3d4KyY1Tn3Mh+bQw9eX8VQj67k"
    "pKNJQZNOdbpsspivwF+bf//bf8Jixn42WEyapMaLXmOj0AfCtStJABqPa8snDyM2XEtUnJ8ufBEw"
    "8ZUw7/3krLINUc0bXO+ZsLz40Le5rJGEffjlqq+UT+ko2Wc430sq8j1+iep6WF9KtqlIx5AMmXle"
    "c0CqztJyMGXokM5gOlb3a+q4zZO6KmFNqlAIoCLh/FUn9g1/Luta+jjE0RwFqF6NlYkAeIMZ7IO5"
    "8c7jX0vqUWQbFZEZcvSC8Y8ePIioGARrkE0rF0cCi5Z++pqLqIWYCRE7YDBtYkoq2U9yMYLqHers"
    "YjRhtCf2iDa+8dYwPDTZFn3hfck9xD7l5qMEBugAuJsIVCYmx6jtY1A9KbZn7izSHbI7zvEnHDm6"
    "TCXWeFxQivDG3ptU0z8X+evuW+rLWXZRcOrx8nw65Y3ChmOJaEPqsve9CEQIO2TpjYOB9FaUI9Zl"
    "KP65cje95bs3v3BAtR1Oqc0RouFTsDlv8WTGiUOrx/koW4wB6MqfxL/vuaM3YqyNR7k729XQSJi9"
    "cPSnpsOImykX53ErTCAW56GHY7A7e1ahlYph3xYDxiLp/P3//o+OGtbqLCOsi3QSRsjaSWodpTy2"
    "FgPtSVz79dm0ObxzCG6d6DxSufqtQI+sDP1pX1KN2iLl4DMihssHIyV8E2GH6WfcUdoLrePU51Yv"
    "4jQ7vyDZdC/YkUrbdAf0rXbfVqCv89a3/rTxBTpLktKHBB+gXXt3ejMC8XMYMznyqXeNhhA9FzQk"
    "D9Jq+gSeOd3ND2hrdA6HpPySegFAvlUVZK37zmIWGUPd1J24qZv7a8FfFawzqU74ldAY965xAct7"
    "5/tQ9w6uM3WsFPrFeQg/nzrvhSlL/KJ8YbXCgJ2DOSOnqVuABMufWk0fRT1lpvlHZ8V4SES2a7q9"
    "juMSuXsROyvRKyUyvKvp2bGwkfeG3jIQhuiiYR9q8cM+p8MwTlnp0Gd8AyvHyiKoLG64JGSlqm9O"
    "tzzIUzKySCoT8kZjqIL6Ahgq7rgzVbWoqy3npTMuPErdV0yecG02w4ao0YwofvONORAH2r6wqIce"
    "b17HIoQRZV/po7C8KZKv1zY2bhsOETVknY1Ke1LcKBZJJl6XQOI/Hz0JSlhLulnwG/K3a4j7BkRL"
    "27zQv1zz7q1vLqf12A4yebSzRX51lshDiX7ErwrLQLWSIhdJIfx51XVzHfmpSYwaNoHlVwDu9X6o"
    "HJCzWoQ0gHvab5PHottQBXN0Nh40HsmY8VfrrXxSIctvwXz1sKiaAlgmLPsjCVfy3Dn+Qsd1+unX"
    "T4tbt/IRGPFVX6N/s5ahoko4mtN5UbcPNNb5HFnH4jJ4JEWUAIVhX6bTZfMtxnj+WakpdifwBmA9"
    "eTYpX+dzVhXCG2+oZiJZ6It8fkLFztMkzHSZm9ufZroFJFoxcdGS8/xXOjlER+hrgFsTVSkonPdw"
    "oc4szk0NHGUzobt4DMf/U8k8gZWBV6dohHkg7F2hhAzjb535ccZagcd+OnSp1TeFntemEo867qpy"
    "Gta3AecnatRwimO4qxs+Eq95rWWJu3+RN1S90tJEo5LYo51hYkYNvKbgi6UkE9VgOskjanKK4374"
    "Mgj2NFKeYVu3DgEqxefRN1JID2KK/Wny9lb//bufJk1r7BWj7fT5s9Kl940uHf1K54KhUI+4naMO"
    "p6W1hBi8Y2ipp2N4O4gakm54wDJ9bTGPnSd8p2aTbHwJxEM2b+CKpu23QAYJEpwEKzAb51DFKzZG"
    "JgFXHEYtb+DuUsKpKj/DNeVCojokvEk5arbk7jPUMvU6Ex/lNNnhFi6m4wUjWiaLWXL7zj8ll3nG"
    "QJf8rwuVAciZJlcNvnI6Z43scwiiJ/kgW+hV/t3tZDyV8GIYP7h5+nvCiGnM+dAtMxFnW4GnB3Pm"
    "rDLxR/SsslIj7WjUus66c/ml6ecMpMDHS8YFoLrhEGjzn1UKwlL6RThk52zuBq+D8jTsxjYewvCz"
    "mGBlQFkwVX1h3aRERdxJqSY2myQxXOfzoO/OFVYt2K+n6v2kyO7IHDKlBZT4OraxZZXFHzuXbul6"
    "KvmPdRzBR5T+8Lbhv2QbFbKxWFW+JUPQhNfKWF0CL3BYDGD/4r2i3jfYZBi+/wJcrJHMUkJEAQMG"
    "ni6irdmimq6pVQYjU594Pz715mE1fZbMiHLjvMbLqcmohCrRpyStbLCIRSn+Q7Ry9dPEG27GMzBd"
    "lLy1ZMgyCTS1vN5mZfvdnf7mxgY1jSiuU3d7+PBwrJWfgV8X2ZxoSAkceNaAo4nb/VsbG84URuWt"
    "FM7ZOFtMBmd9Z5cgajnnRFhqNuNsXcEXZJ4u2GfK9rlTldVJlZH+X+n/v6oi05Mvo13+cvX21NN5"
    "NszZVb90jviegPZ5vyHeQZwwNPtCssOn9IZPvFGKi+UJbaXP1FAorD9jSZ4Xerh1t9rNus0JFdj1"
    "2wX7qvdmxllJFRFJmprkBeym3ip8wilYxb/zFc4qXyKnxLPOQBykPdrE4tSKjcn0sUKKC/aS46Rj"
    "PAFsd4JhW427khI1EDFoU7AHN81MVQzgUnXUoWdrc7kH93cf0xJxWCYLOvIy0wS0nZ1nD3f3O8fN"
    "RCin0+nQSlPHc77z/7i/u/sczWF9g+Ym7Lr0fH2ncyyKLe1anWWeC74Im0tO2rbJnHW+0hvq+s7j"
    "vee7BwfJT4uNjZP7MiN8eTj5Gs6t3qO6J3y0Fn/pglYeEcEeFOMmKzoQ507dc+CYI7UqZ5mrDUEA"
    "Z0JlzhEbrWil4QZL03E0SLmnilHHUWdtDNScqkjyAdTvHDFIJT2iIRx36kr/+bCAKmKQDlPvyKRJ"
    "BBiov7fiQ3iv/PTG5h1x6ZmOKs5cb9UjzkaalR3IwqIuuEPbvPa3OLUhEXkBp+hE0BsYDPwZjqMh"
    "+Z2BjzgCEVKWuehGQtYUryNNenZSl13wSH1+6K+23osqUQWTsrYGovHvfCM3ZftL+MLCoUR32lW8"
    "8w4cadSbCH2KhK9TqAiHobUfosnKUIKhiyKIYz+TPzxINhTZAv7pW4nw1Zt4dsmShHuOAzTEBUgd"
    "6GyHx9mxxA+Sm8rmKkr4DUV4MC8IVzBC1P06OXoraBMBd+7AJWDCETQJtwAR7w0ZBhF4DV4eGauP"
    "l/TAJ8VtvAkAMaRTg5T+sd7gRw7jCM1CV36wwtB1UrAuHMjFVjg2N1NtgzNWhHbJqUWMFWYruQRq"
    "Cw2njUy5WQUm0g1xQ5UvHqTJi1fZiKP/9Xu3/BoabdfvH/AtwxozjRQTR97kFPxvZj64z/afiS5N"
    "X7Op2zNSUwDJzhOJZ1DUcHq+XYMWJCr+jBvZB9tW8E2uQYyflZI7irj5TMLaGb+VuIDFXN8r2YZY"
    "MRlmPjO5jXs/TV7CtdsP+8ulw3YezSQzDV4xSi3H24Ph+jODUlo+pOR3m+mtZ33GT0u+6CcwEib3"
    "0i/S5Jk4hhND8Uc0NUEeH+tVzVgoScoidVF8abR4Ii5xZNR3S10HB7Ac9GX7rtQOJY1LZYBp07q0"
    "wU097T0iRRXtmbYBmyX7uvsdxZ6+rtkr9CzBIz7wZ4wJoiVCe+9pHvUrr1uP+ZlMAv+5WhdRZcW4"
    "jPUQrkFxnxSuMFT6kGQHcyEyhwQmw2H0pWHliLyLsPElLlxaJzqnmG1Ni8w1h66mZscNSGpZPXZL"
    "rTYYPGq3MyXoadcbtVEyujHK00Zr7s1ScxO9+23GJv6sa6I89T0NjO5cKOws1OyN3srD69n6Vux0"
    "A0PjVGlsK/Za7ED9FFgZubt75zOSMlUnKV2RHvNbpmCHBbPNgIw5AkoLa5SFfQk5T3y0XuYEVA5l"
    "II9YgIOfK3EWiyxHGmrnyzw0wLoDxZBke5kCyxkooC/+iF4gMCp5CJgWcz3iSgycF+yoIKHY9W1w"
    "rv6uUs5hsjOZLLKxENQWw5mroY4XH2Ckc1X3BJuSvcT4T77J2SvSpd1hA4bPuyNJW3sGwS0w7/Be"
    "7AWOf/4Lj2H92jehgL/kwCm5j+7XisS6YSlLsZso55OVJTVsNmH+5mE+OJtMiSe4rH3ZwTLyl92v"
    "lV/2pa7x5Z09XKIMFYnvKWxky3ZSfcIfp2swrnHhsbiBB8ZOdtoP10yOmmFA2lLridu3x8v3jdX0"
    "B5ceOoRIg/U0c6fskDCLiSyflW9d7wPR3iTPBKgUFVS/8zWuFGZeOzaDyswG8/LQ0pE/0qTw3IJL"
    "Uk5t/JiXWr8TkkBJYFAjgTpfIDa//30if3nUR/lJnN5uNjgTvCxppZVmkqBF/85VtGPBTktDi0Dk"
    "oZKEvgyj1XEDkhQSHc2sWgY0UJC8dSM8FtzfRQ0d8WuZJ0TXGhgljd1vEQ389fNn7lbLjOaNm384"
    "li7BoGPPwFj0pVjTEoSC1zBbLzMtttitCzVcN7BEPEio2NBxMUDEDVSDmk6D7S0jDj6qh6FK2GgQ"
    "axrCDEC5DWO95my0/I2idazMlT9Ndm6YCoxkcJZVXPpCjUh1UQSquJbPZgweInjfaPN1xpYqiVUV"
    "KOxt8VdmuUVYNmLCx6WLbc1mmZqPNJp+988/f78XAoUddUxdxff5v/4X01Hhleqq8OYmnguS2FFn"
    "ki+qudQoRNGkrMR5RRvzHH6WZSguD0PomTJ00pWsW5zXrER8vAs7/piQ4zMShKIH58VkwcmAb60N"
    "i9NCnL44s0HN/feAasKCHjgAi/Pr0n1azgfOEdZUVBfL/b1rYuQEYqRr+9cFSUMHnL1lOt8ZE+E4"
    "wp5dgyhwTPQxmaRnxXDIvnQTvs2AKcpiMdz1u0r8BQs48VAiQecQcbFqOHzsXISUkT88YFy7X2p0"
    "Sr8YG863lkUKJN2dvV4QLlBNBe5O6O3JoqqEm3wD/35QOx3PY+f8wqNiBBcJMKYXqj+SplLNFmeN"
    "ha+We/WFfomSPOcwO+lq9INKFssmDF2QrrV5H7Z5Gr4PlqPMZ84vMrwo6Dn++R//3a/BzbELvxMv"
    "Ys4vq2kwbBt63+M6yeQZ9mqxA/HZkQkEIt2s6xwdlnLxe4a8YrGTZV8RgV6R3J4MFnOJ5BKootQ3"
    "bGsQKcFMjWjICg9CVBQ/RUyfcCfPU4dYqFZZxXor4WuJEyZ4iz4F+9J5SuSEfJ50tXViWuapxFf9"
    "gf5igEL2rq3m0wU8osXBNoh0KSSDcW1aObLKpUatzeyyebUvBz7e1gXJJMi3THgldHrOQ0fJjGG7"
    "9LhnAtuqc790OaWOKe+ZYDeaCxiV4GseWuj6X+NZwbfqbbgdHiywsVfXbl4BNmoNYIWbD52e1V36"
    "wmdgjeNH0Ftw9xr9CDd023FL0xR1hCEJYnwzumQeTt/EN8z0TaxhGQ5QMNxuxWTGWd9qw1dKhIwk"
    "9F5pBf50dJDRlrb1oejX8JiToveBvkM3Prq2jgeuoLtlDFZbO1pNGrR6OBB/n+XRGwq45SMqFXXL"
    "kfIaGBdPaTVpI+V4fBUZlxHws26odTp3GpeZnVcxaj0GvrD2QfMTe3RW8I5dnq3elgfxamJuMkjn"
    "hPWixKDNp5UkPmYe0BSwHUV+FWQwerGOGNH1bFas316XL6//8usYKbkc9HihymhFGeNwNbB62wEo"
    "WbKYKdiZ+xJ9GjYRsEtgRwWUzFA7OBqVJqkUU2Y7PplFIL1xcSUVsfM0iX2Z4V6NAC2F+DIuquWe"
    "572TnJ5Ny8oiox2qGljttWISXPEJN9K2LfTNVTsD8ZOsM5fp6LpQHRpkQas9ryRlUBet8Vh78R3F"
    "yG4PZJ4cw8B3Mx71gnst4ULMLHV7KdKfdVm97KMfxgI2n1l8A1LWvRURhS7CgxfPSe4HTjhrapP3"
    "iE2ljdkFBwB3tulrZqR3cX11O+z6wd1SFxhuoBMkQFB2Y8KJqAO4txo2bJwkiUr3mh/zHsqCrsNb"
    "VL+fJrtvZvlAYqhbTxSD2XIknAucCTKAx3h2fd1KAnsmJkkfIzKiNs/AJV8dI/LhTBrYtJTnvJuH"
    "y0abopW1MsaN+AkEf6TneVnimBFjoRKMdzZ/73XOSpebG5d9H4KdC9B+LouZ4Nzy/nw2ag/n2SnM"
    "IUEYSmtoCWozd4SqKYv+XA375ormx3l24fsXNzTPz6kZa2tlQ9PZh/Uxblqt+ZgcqotFPoRvFV0z"
    "fppsKCpnUnPxlSxyHyQMvtCjixmEaZWw5LbVmo8NWxVHLZsIrTb20A0ftzAT0lhyoENnX33fjP0j"
    "QRhMm0h2hno0t4N/ptYw7lUqCmTGp1b8agfODn/Y19lluRVjofPF5i8JdkBquezW1tjU3GVfGg+A"
    "kE8uivl0gglCkGDGnrZ6J84so5nSjuizoDGLUwGG534+e/RS1DNzhBkLWMOEb1QBQaXxQ7NVJy4c"
    "eQb3xLEO0bnusFYl+qZ3NmVvuumgXJd4/93D71+m5/A3RaYGgaz36FOIwzbfJu8bHjB2HyPjlIwj"
    "UFt8sT0tzkNFohc1mhLCSgOM6L34FnbiSeqc2+tNe3kETn+x5LFalukwkn8yN5QFtKERFR3hxi3V"
    "mTDjLtd9p6+CT/yeG3B53MxRtLUpz9cXwlwC8UzyBgC1g7VuQboz5NyjQpiEXv3kEhfWC6d+6Wj/"
    "9N3TrVCoQcXVHu7DAZ7FWmcMLyo04JlmcB961+KWhQLimCWBA7cChxfcxeIFNyresIeQH9/NFhmr"
    "/omY/qh7QarwJ5p5z7K4w1c58toUpwmkiNVZ7gQSZMgQ1jB0hgP0y0h66MbN/mCu1/U8ouLpdTq+"
    "nJ3B10v0mkesEziOM/QNa/bWoXgKJ74Bz0dQ9WqnonubmExa5WxeZGuseoeDd13fgB23K39thW85"
    "PQZe/qDaUzVYBLk92xwPbCFnqTGgxpDNapkW6kBJNjLgZ3BH6yHk9RYCSZifb8mRcKD4ODw+oZnV"
    "DbG74/wcjfa/ojLcfCYe5s0Sa2iFj+g5YvVFzeLz5bZgHsnsDMWHoRfC9IcbWfGNAk+GuUZ9tR4z"
    "fvlh5+wJHwHkBMEf1um2aHpk3CsmRYSMdXX8PINDaeN9lR3drydmOMAPDotfHRLfDIenLoSR8HHA"
    "ow/2d23Mo/GtDoofyZmVWzKWAzUrlIvPlNZHCIH7OumOUrHsCKrxiDFsthJOP8XRah2f/LMT+lty"
    "fc7c6+rHv8CFSXPsctZyaIaDgg1eKBT5/sBGkzywLo7S2ZRYGTatB/q6kd7GamfdjlNUM/6LZBVW"
    "583pq46MV6px4p2g5a9p/c/poKjNZZeDQ4EZdISaWH9YqTouK9BW3LpVrbcDK+BIanJbi4nOJb17"
    "MRp1jpcBFDQCjBvrZwBzvzD+jg+/nbwW6c3A54JK8exL9y3/a06se1//2jy+bpjuSfMsV3LRinqR"
    "07046inb8mNOvktrpN7lxTzIheXJl+6fFcTAlTlrzHWTIDzx7iIBYNyh//BHkYHRWYMM0MdXUILR"
    "WW18LbSglRpwiqva9e2d8vzII++1xkabSM7g2nOVsel1r/lyxPmrcA99Q//2wzxOfOEcaOYyxZ8d"
    "JpZs1adtP6m7yCWNmRqdGOcf7qhR5e+h0DqOu6ovRQWGsE0oJBasz7X6NQFDjNw7I+DHZU7xI0pA"
    "xbdUUVDtxQnJ7K8RuzjIBV0OvxhDL8axCrUqvFSCqRbBf7TBKLG+awzv0KrsqrwdY3jI70P8E5Uw"
    "i6t/Esji/mG3pkl3/iivPHzZK6J+6stiiGVGjA1ZLPmKGJ6NDWZKfscMyatknZ/0QhcnouzPeGtw"
    "Gfb//5bRx9S+/c3uztPDbxQpWOIyYhDaFxOEebHukVlL3Av/+p/g+pFNXm0lG+Kh6kJAQsjdigOq"
    "gFlrNW+6eptSzweWBF+kRR+yq07wxf/iat6Smi5KJKiJW2Gu/h6u6t98Z9c2FTFXxv5kf/fAhs6b"
    "JezFEzyoDzM75U8GYzyVCykaFKf7DEsdVIIAHAwAFnva+IAXG+eV5CE9zzPEl8FHwkG6GjqkumCU"
    "yaPv9/d3nx9qrk+EFBVUhUVZBEdOLMyWATWLcvJZhalSVyjQMjqXjJOTXxTDHKdo6L2X59PhYkAs"
    "rWRV4abFLRzCMwmOuNQ5vwmE6ggrPPDI2N/97vu9/d3HTfjpRKLcSudhaMmgfSbn4xrq9DWqWPrp"
    "KM/zcQ2B+mPb0RTYYULo4xhk+tM0ahm5j3lr2BSm6j7/IAmeCEJ1+IyRp8MHDDcVPrDuOrDoJ3u7"
    "Tx///HTn4e5TXSeXTrwjsJh+VJbEW0eXKByt5ePuaIRiYkO+YfnBO79MTxIdfpCXm2fCR0aBL0HS"
    "8c5F5CrP7fjc3B09HcMkmDNJas4enwkt9RyVIl+Ys6xk6QYQMyO9B14XbH8YOXYe58wt4pYPbbl5"
    "03vAMnIheHaenPVCcAvde+MjuCndBFtBlEzXHEpjp8LkK8Ohkpo6g2FN5y8IftjnBpbybiq2gvLO"
    "O7Ctht+EW76G90C9GaaQHoru2p9DV+NodBwWfR9daIOApiHhaqCGJnIV7MojpK5mKFLMiturQjAC"
    "c6ew/Zxd5ldzmBgxxolf3gHWN1SPv01m2LNhSBOqO2FdW3U89HoSvP5nXKS9vhVChqFft8IC7+M7"
    "PJ/QCp1xLzgKKgLN5MwkLi7NjTmIIsguy8NpLf4KIVdBbu01a9iHYBkmJ9FwlyWlEcGlwVvUUuj2"
    "GLTCAOqSJJo4aXAAHQ+ZYgmcQxwF7e0fAMDiKzqXu1qgn5XGFLCD6Q8MchxWNZc8k4LQI76O2erP"
    "1/DqHoVT8BW+E+bbvtXzjfHzeg+X1w5q8sXfqcUTs6REdPUc6Vs4ibjevYEXvsvmIEnHOQxpfImr"
    "HmMeLcaaBZPjz7IIyl1CdtkzkC2MFSKSEHChTftcwFqSuiytnSEzOlve2Xg2gVcl/Z5MibGenKIC"
    "BzJNlLUWcOt8nM2g5wYodRQEzJ94kFi4wSBy5nAQRH5pQCt9csHgkP/hQfA8uJJ8VOIVW9iCFoLt"
    "ixwhjD9CNaqC85QyGAKMSBrGl3GqLJd3hfkmS4sHUwwtEE/WDcXDEFfjEK4aFx6i6WhdGe/bVglJ"
    "ocU5gUYwg8qYp96BN4nTK+QE4ErQzcGz7brqRBoSDPjKFUuPYRtkp9Nt3xbfmedwzOXFFrDrDIaA"
    "POliiGW1Ns4mkhwESQLLnGbV0rf1FKZFQaU4dQjSCZ5ykB3DvminONwkHLyIcmI2Sh1a1o5keKXr"
    "pTq7TP4iK/8X3Vh+GwPOdqa5q7HJ6D1aAtpXAs2fh5SRRH8uFza4A+rBgDswvhQwLoHwZsjdkhHF"
    "4FCsP6XL1l6GZIVZeRY5ikxxWumI4mHHueF2os1enrF3ktvMikbc1XxcQUp7Vn5x2kxop/wLMP4u"
    "x73LXu+y1neEF6J3EU1O3lusp12q6lZLm/gJo+0EndLIWCr85MX+989+fvjjz5yts+1yyXiFHyQ4"
    "P3wiNLeZy6atwdSdnowCZQzS2t4cbR6nxIOcs0es9c/ds0iTN+i7bMaYwb4cM0nvRiRVknbIXdAP"
    "r6y+3gN9IbVikZO06Pj/Y7brumin4xRN9BkKhkuCukFttOUpEREfrPVXjVo3BJlNp7PPf8KGsRXM"
    "8dfB3yRRy9x9zbFXLrhdHgpK6VbgfWVsz1aTAXrf4sxPu/AyefziGaJlAdjRDd2R+Y7grAE49fCL"
    "mtBJQxb4XthGqO/Ix90KB1/wAqgtzl/InnthoovlnndU2xnXGPd7Evmb0iN7yxgVtaBEdXCkSxC4"
    "Olwk9rfkSjejmG2kubOnouyY1Jyy8cu+yu0bt+YCPb13oo9Ij3kz2WAPkbChexY5K9bMaCcoEpo2"
    "ltnZaLeK2uTo7Dj19rZWW5v4H3Ju+bnBgXk0t1h1XL2BTOibFk105PPRspH0sgfAS1mL9ng4JQ5L"
    "846VLhocjneg3eOsGDL6B5vRJd1vXyjKgeV2iOlLdC8gP/gaq9/4ClWcEqbYknXMOVOwupivV7W/"
    "v5ghbRZHgnMANxVIk32+BJNMzQwM1gS3C3czcT7yqRja6cpFOj726qBrSbJavClUU8FAQHzBGv2P"
    "s8Py5bklecRceSHZaOhiOshOFuNszrnL+cbnPvlsm+zOD2cVMyZLnxE+g+/i5GI9brApLwPKDE8G"
    "cVwcw1PDTKNjVpy7xBUcwGOROOfETkqyC/uvRkWARBFTBCQQYhCk0XQ8Rip4yRgG8OQR92orCBXi"
    "6S/Kvu0icLHyA5qkYc4ZyuApPwfmUF9DkAK1LIfZ+/rs7Dnj1CMWlRTGLPGEAHVHoEAFFJOaZ3O7"
    "og5NxLsTW8KplA53Hv689/iAU1vhu6/UDCT8Nv5yTj2scXHQ3JpztJMV/C3YhWh+vqHO7lWcXK5k"
    "BmwErCsYIdVnc+o2qEJ+fpvnM0EDJaaCZ5EHL7lhJIlDSbsHi5+NGYkGDA1nWGB2TbJFoohMSJlP"
    "yuIkUpthjDtP93Y4bRsvGDt+6GBxh/i8nS6yg/dRI+EmzvXIJq3mvVpNVvmB0bRTiTUGZx9GxhGg"
    "5SUK78lfVY/TatJG9qSHzPioQWPqIABWfdy+7P22b06d65HiiJlxAbHqeVctWZyyDJVlRjjv07IJ"
    "uZFcdwKudMT1KyHGVrUT0WH/JmPJ0XnqYuO4kFkriDTVnAHVLf6R1WWdiP3Y5uyq2n/Pukl1koeC"
    "DSGPRLu8N2E9EGN6rXEuCih86fA9pvKA5Bgqoh5vYBqrJg0lzoTm4TN4jM1fLWacKlrOirLxrwus"
    "qYOMFAdmc7g23A86PwrsQXvcTfhVOTDexq4HF6oBEc63rCyQjPp3HEQUMVt7szFBlQsto/K90K25"
    "zUPzRhgzFVfFO0nPpF63h9PuW4D1biUb/RZodskNqssQpoNn6ZO27+UJMPqIupAcH9NvdRayIisO"
    "q5XBPCwvdCKAdJ2rN7O1J3PN5jn3aMWyBejwLjMKEQmr2mu0K46snpxBrOfo3y5Pz94wUp9F2jMt"
    "cBwzacyc/Px493Bn7+lBVEa8v3lzDMPlXzVdrzgJL81XLZBZApTZ1BaoN+xr9FjMbeZIIQxV6PyH"
    "4+LW7KpeCHRuvRMli1IBbNJZMStX7hFafpRRvhZ/tsAbtyACHXV2BoxFCeZNPANLQebghG5IWWtP"
    "LYEt8eLDlD+h7hzyuRYXFbwA0kvoiaN4yatGUssn0zoOVjqmvy6myBFURyhnB3l+xzzDifvz73/7"
    "V4xFK2K1/v63/9aEdCtznhtw+uI34aIYax9i/GO5mqhoWnM0CD0Gm14GlmsPFfF3w9VgbPkax0Xd"
    "AW8otw6qERUc5m9ejLqy8TqRAx6X+yrZ4Dzf+PsPyb0N/x1wae3Outyy85tD1d4KZ92gtBR1nVBI"
    "2XFR2+Co0XSZGxeRq0I42849znlxEAG+Yh+hiLl6TatV+wgXY8xAnU4bwT+nU43ylfIqt0mHT6ft"
    "YT70/Moo3hbC6e8n/RZfTi7Sg4djwARTNzGuHejMnuHOqTshMBVjYG+lZ6ZDcBnAmJK2E9olubgs"
    "h4s0FZ70xgxiKJdMWVEPChf1Z7VEq66Fk9ZgOp/DBZEwzIDEaIDWVY+mExHikysXo3lHNeXypVsO"
    "Zso1IA1c4xL2H+p4JJ8mI+E0rEOGpaoJ/vs558pmzacxEsMi45yXUxZRhfMo87kl6Rbg7hnnP9x1"
    "8h27FbALPXxtRDXuA/bEcBBbLQxcvHpNpz4Qbxg77QEUUF+FAIGJYgMKLiAtxvp60hGRTQR+/pNY"
    "LAHO7mhr9AMTSA2+YViGN84N9w/JLehr3yBkRnWdN6BWfRO4+65t1tx9vVsv1XsTuvQeh4yKzDUd"
    "k7zLZ7wveZ2iLLd12ryMkJqb4fLwA0OYkm9EaW2L+PRiz3xf5ozSo2kmP5zBkcysXsOsqmu3uLxK"
    "39tK/4//ruhXTtH7cQyNS7XkGhQG59+CwxGoKniMgq3Z0u8bj3Pg/CFknPLzQzibT8vawO6ynvwg"
    "IVKVKl5urGQ9DM4tZLPKqsZ7CChQbFUtKw996ra8FUpVVYbRyhYJQXNdKbY0O697/1wMIXz2PYZa"
    "/C5ynW/tS+dbhH9b7tVQ9zPMB2PWLrNHqwbRQRGjvVbgT9VECusKM5JrhBVVFuzxvhnuMR2akTI7"
    "KYEXxVaNVZ1Vje4iFVW0KnYt4MpagEWdZmWK44An3elQSNMsK8X1K55m8wxg2Df+u+N8qF2boLPs"
    "IgiYXLGmdpc20/MNcPmlBRE4rQun39Euu9lYvXhPMaIFG4AUEs6b4F1LwUMl0afTTrif1Dj/wHkJ"
    "YJxMpSQAi937jrScTjqD8bz2gGY+iI7Jg6R/BkX7DPmExT+OJ0x/PJkCwpBL2BWyrVdIz29ZOVJm"
    "YOotmYXn+RuBmnMFl+Ypa63/g6KpKuxeDYbwfT2XUxXQEIFzEmx8INE7ZHkA8ZbVVWRFME0ZHQrO"
    "XSF5uShr5OWibO37dTH6HPauv5cELYrdvYYdfc/hFJd5pY8lTTb9iflRSHZnlhuGHo+C16pDaO+r"
    "RyDMBEnOkjky8KB56nLPtBPmwjZUdLIIp3DFl/7k3eUUJ7GlcTznhrUIkwiBV+ytQMUTxDf0gKes"
    "vQMOM69iMrgMLk+OIyfH6AehqIHnRvD9dZ0n8alC1X8yXwxhcKmM8/kL4vvqd5JLGySgVHE2Zk4o"
    "pV5Yb9QJS1HbV2TFclBSyMPxgLMhDYrq8iX97MqHghP56MWzZ3uHh7uPocp1RMDiVtrn85G2yJzB"
    "9PwcrLFsTrMSBDnAxA9lIMCapSpWkWY+MrthF+eV4LvNk6LqNLDV40N17Q5iEmiuKuKT6ZqsJfTi"
    "5MeOWCKtZyH50JnSclXOjOk3o2TKZIKqCSE6rj6dV45vFuuXdkEA8Y0l6Po216T9Be+FEAC6Y/uo"
    "2Qf+QzsyzznzUsYxBpzWY76m2T+g1bbMCuwxBEqh/B7gSFsp6UVZo6QldiURBnFTQQyD516ZxTXK"
    "s30FXRW1WuQ/4CZkkM4GFZ+eiN4OZjV62+5oeYWf5axtb7yQsbDvSux3GXvV9vgE8ovAq/hodNyr"
    "pz43uZHImA2i9cvPXKDXII39NNUdxz++xqeDK+LMrBZRYInd+cQGvpI0QWzGxFq46Lwoz9nMbQAG"
    "7vWBNletb1w6Wsh5UVvIedFKodEEx/fwJREgeOrU6LOaeIsxw44uyRi5ERomcNhPGCjGowb72Zrk"
    "9UlQ/SSjITY8mj8KKbeRlmr5yB02L322ZWMRD8x5hpvLNS/ccj1W5/kt733eNy3JJGKDGCoC1nw3"
    "7H0OaOCK8GGfqyc/4CgLxAF09K9+cpqRxPpqItlzF5PsgsagWnR0VGoKasqq3WKdbUcct23igcLD"
    "yXpc97CPYYb3QRLcAyYLYQHtqAf0XfGlAFx4vhRcmL/nHuj3fIEP+d7OXjJbAinc2AVLeiw2qtPp"
    "2vhqrGFAzWZVEqniroYKXrIoUtwY9lbg4MbuNUDaT67cjnW5dkNcX9kt6bKbqlZrqalqTf7+H/7P"
    "zj9GL+61psaYfbxSPFa0Cn0qW420IzEJrliP0Rr3puNdA74xv/cVdURPEFR6on7oK+qICOyrfLe6"
    "+K9BUVX0rSwvXDODfcioQ6o1nWk0r1IuoNbwuEUk0QpSCnpZF5/UoVUPzWtg6MRu6gOAbQvWPlIq"
    "iFYyda2VSLyexN2bciTwjYbuT0r1bT36Osd9mw06CINVaFYSy4nBfddSTEAMg1IrZpY+C3boWqCu"
    "OrZg+mwA8TMeS/zou/injDJldCVee87EVotSbZodKrqmq2LWehrwfJVrUTHD9vEmJzp2h8Vsp4LA"
    "phEzVIaO7+U4T5Ezjw4o0wcYbQOsXQlGmOEDDyFsEhP3aFzQd/YZtDdACH5jmrpzoq9vYKG/0zc3"
    "jmJCc/xDMWQ1/zx9rX99Eda/DOtfttT/JmefYzRwZn9KC34kiokzw/c7szed+C3yPT/Al+zl+8Bz"
    "tRjmNENdBsprm5kJQ6vT/l7hXUOM11A4kchRw/ixzm5JAhgwDt3X6u4ZZX6K507R34cDbGCYRtda"
    "bxm8aMIRVFUncA+PWOB6XhuLpK9F0Tt/2QvvXsb9sfu3loqmGjfdamNFYK/eXwuOX2Kvj6z1EpyD"
    "zzsD091ebzngS1HVbB5FFeQow/KEg0m+otaWN9b5nKXlqMYaajggmsbY2GIemo80uTgWeYEczw8h"
    "m3/82rabdGoLzZDDlvUS4ZuaSyXW/sGXk8M6LUNmqPOqxMPTdGZWpKZvk1jbNNbdBc35Xd2Rq9re"
    "6TxA2fHQKSs42BJ84RPRfwTaDUbaUG2K5K2s7ZSji34y5py5GH8tpVP7xgcQ8LKNf9G2y8cOXyTY"
    "yz0Xo9lwHh4j5EayRLaR9Ecvnh7oQr1NiGRocDBC811wu5kE8XBwPttKfLb2jFc+HTP8PULdM0CS"
    "ynaQUHlrVaa+n4Qh8/IgabQaOF9lptdYC5+e2NPoE2zXCz/xwh4kLR3n0o2eS2aiuF0O2w4nRHXb"
    "be1a+vqvv4YNOshfrw+ihiVEPGh4F/vYlM/NlqFkDRsOfkftmnrJknBIUjx71JgJK876p7XkJH4Q"
    "taxmKN/uoT1om2I1HaFJ/TNqTJlg39g39qDZmBL3E2dhg36PWtbnWfychLUrvz5S+Af39dhmVfv+"
    "SWTCWqPmw9/UMNEChLXirAnYiB8enj0uQAA2t6GjGNLfm2BxoBtFXurJZ2UyyarFnMgXpze2GH6A"
    "2ciduZTp0iLMeNVYYJzt0HOhDWhnEPgyVQavwxdBRI+yOb7RZ6utFb1WigKOv7U5IW5kAL6kF0zJ"
    "mv65rXbYYAa57HY8fe8VsNI4WEOopQ6ZN++roPKNxOYwRA5qEkppcFnklX0unEu2tD4I7BBBQB6D"
    "cMXmi8UgsF/4KPKgFtS5xsNrLF7MwgRKgouCYwuoBn3LFGyLeNYXQbDuzZo04Py5nEyg2GSh9MHm"
    "JFGbMiRZ8G5Z/YZJR5uNJBhuV4PDueHwbVvL2kgk8jxg5rhSmViZ3haLca09hzHtbClRs9w1aYN7"
    "Frxr69j7oJloiHDsv6IuKv1a9/s84z3VdfyVZ66Cn3xFBb8NwMI/4fxs9c0TgGXTZ7wH/a+91qGF"
    "GWANYiLMBuLMdLoXo13o90F0KnasTn3XhuVXORll5XTUdNveKdUjWwNANWdPz+Xlwc+23Dyv8/yV"
    "5OOx7DxXZeuBQTR4IHKUg4eqsqoMzYry+GUxY7SO5puHwpZ33dT0+H5w9jIObfduKwhyl8zlWcKC"
    "CD9xrT0r3rR8XLSnLd3an2ZDUCb6OH02Ye15pCjHD9nOiKCLu1Ei4c0rb9rzQ6KrAJZDaTaamkVZ"
    "Hyh7JdIajC81pkxztJ+YZ6N9Mxq1B+gCd9vV/Vf7WDGoO8C2rFFAz1/NipU+aHgvHDv+apeYLM/x"
    "QrIcv1W0rY0gfzr97QGxNvoCJFUAl2pDMXI2xGwQ3OUL7O6wx4l+w/sbff556FfiCZgjglIhtc/F"
    "5SFEWQmwlJ8/EIN+7HWNkDsv03noqz2zb3fUWXLLJHbps4nsNNjFCZVXwuHS8gR5eSM2uOaKoU07"
    "2c/317WsniEzPW8tDQdQZ3FXtTUsmGvuJL9keAWY0kQlBIIwBY4Rg6jU4NIMfo/J2pYyQXXdXe33"
    "AwNkcY5N2rJM0tby8o2heSy21pHpDnSDKyYc5N42OJ9ALQB1+9jRWWNugL71FWN0tZor6KDjWodp"
    "h8uNk13rNGZJOXsZZZBBLsKg+9iBuvbcSIMvrBiqr9cYq4HKtY7UjrIb6WSqwgs8Tr4iAYNR29x4"
    "S7qwphwy63Hz/p9lw421yys4LzdY9yQY7Ipq79vUJ3yNM5mJVSeTKeNbkDxi2bTwWTUqsSuj6FRQ"
    "VYK3UiUyDOfMfxpas6d71pbnwfCddpuVvrvabuXSfdEF54QUZ6fSZlqiaWdzsYs6befNmzaIXlzZ"
    "4iDCMT7hb5rng0SQcGaFMbErChtqz6R/nZDLc/lEYxVVKZluBUs8mjjaUb0oT2IbhgIXgxVH8ROu"
    "iZ6A7znLqAN5DR8ucacvQzQFWzANLspO+tHI7FIplT+P39J54nf0r7XGl762hpZ7TVC0dmYvYDFe"
    "z7OV5hN3b0ksKpVexWacXJppUsMQwcuVXgT0kWa4tPUqDnluk+1wMmFXi3JBYCtXjNBYqiXAKMXp"
    "fLqYlQBF1KsqTLjpiNkxd+eM9VZvnTVhS7XocTcMJ4z6cdajs+I8Rk7x/jSNFP/CHYWCyHnmjUDZ"
    "m+4mRynq7HAvOM/tPG5G2PaA9sxBe7RWTXFbt1nMVN0SECgS0B7l41ru+RkrUm07ahHvrGvhWHNZ"
    "hxTIufa3V6dHphFrpBdjX/t0VU65jEfZm6L0+8lwpePZjMVPSR8aNOSyhVqmRjFQiSntQb25ZJ0X"
    "I3ADdeRznsq+ccmHu8jN1QuzFfk0k6cNlwQ8A005TTk1QMGbxbXpY3mY4ANyKSb3kivzdBltl5cy"
    "tNE4f/NHWXKlxLUNuKzSw6xkCaKz0drueTH5QWets7mhRsKg0NIcDoE3ZLg7ML1bOifRGpgWQBWj"
    "NGNLHON9dEbwCWsM56bgHGBsy2pkOg8XjMFDOJI/Xs7E7Iphv/tYw759J2hL9md+gWx41OK/NJGE"
    "gBSABRTBhqgoCWSBjdlXBdCA/v1j9AXVMPoYRUz9MiNz0PSJmHg/T050668nt/r042RK++g8yFym"
    "mbL8ujY5BnZZzedAvoHFFn/3rlnH8lipHffKajJH1/3IyXgxb20c596oVu6zfHimhsmNS72Xzduw"
    "0blMdM3OOJ2A53jqFLoX6djetn0raO2v+XwqYd7/Odii1+uAJxSyjnz11szEZlwzd2qBjWEkMPX5"
    "Fl/kfuiYXAfIEZ/kGwzVShuOmXVOL8fQkiyqwDvxs1LSgyQHAjBzcimmAvpV9QOlCYdusmKl7xQ2"
    "5eL0NC85lEHi1z2kkURVDIsyO53nErhJA2oCTsJlGqqnEU7fcEscJakZhiDmiE3V8RCvcIFgXOi7"
    "Adak+E8Ov9jpsVZ5t6ehLVL97zXz9kFedY861hzfAwORiDpq5A29Tdp8+wPuyy+UcUO81hEvsioA"
    "gHgxIGd3uzSjC7FS4ipSc/W7dwnQZDcCvoT3QcCYbPSTRzsvdx7tHf6Yqt/6mu9VqECyvVGu6Got"
    "rgY6/pW9hxGlG5qzuDrsWPjDuc/iLA6QHZlERgbgh48wULWAMj4CPlTgVy0e/kAmyxBUkOzD9CYo"
    "T9Ia27IYYetNTk3SKvFufI0m0eCAdsX8cm1WgFtJynPaSPlc0BFEbld7fOq9IwvRQR0bsO1C/Nqg"
    "V1sQ5UaKu8jXqa5H85Mb4sveDCrDBiDZwKLFBbYplhSCj7x/kATvt7lrknZ34W4EJl1Rx5wq3TPy"
    "PIsPgp6plwk3GHAdjjN3m0aITZ/70w8a6HNn+tr0+zY9qFM9f7CYor4k8HAI4xFIWLpGrTXIVkEt"
    "Bje9RrWJS0W1TC66cc1QH+pAe0LDOHibg008zQhQX+qHGK8cybMwrasSz/mWM8ZuitXd7FfTmu6u"
    "GQPT6fmsMTel134jxWx+eK8F92DOGXs45Y4F1wUkyJL68p5MO168rvK6HabTzCa4TEojEa3eV7aS"
    "etImH6oXcuLDIhYf2KfKQIk0yKldxhHc9Ciz1qIKxaRESE5b5PcYTDn+ehRGNHVqbjpUbL4Y5wEb"
    "Ek48avSa2hfzRXqQFMj7UR/F9iqBFPmWxUfMOzTJ2Y/FIC+s1urXBVWnZFoWu+8L1kL9/eua2HqV"
    "yHrSLrPW5VIvEp4Esik41CWplhsiq16cy0RVrrE8od4Sy+xWstzDzclXVN1c2YIItCCgru/DSiPr"
    "h4Vph05vPkw6XHQIdEvi7gSCAwVGDce2eIO0y3PtLoShWfkfJ7s15Das0qeT2977pf8QeW1l+XZZ"
    "rb1Km5zWXrJVRlsifq2UfU6Y0NOlcu5itIMta/uhVRCK7lraP54f41/CAtXpl4au+ccBtY/VCy4y"
    "NKgdgMngqWzlESJj/eG6Okw0dZFvmic0uTrElQHcJbw09WAaXFTy9+olwy0H4+fQfwhu7I7Wde1z"
    "JcRHCBnpBQGp8XsjDfrVsOnHJHUJdClDzs6V67ZIPoHMzSB0EbtH8pI20XJjS6sy9wwfJjKuxOEl"
    "58UbFvfYRjiANDCppFEJNlQUWI8CLDkULUXCYDqGzaGMk3ZRo/vT113sLPX7M/0yCDIwwWeHuHzo"
    "56LKI5zAxr137hSxNfdxey+3dWAWWHr9nLddP8svn3NcPtip3EnemOypH1y3S+6klhvpGirUK24l"
    "MdQ4jWBDH+hs7ZHGr+tVfe0nUSLuJjH8Q9vtsNSHfKUXuS11fPt8hJ/0dQMEOi4Uv7PUifq6AH6f"
    "NiTgHxYU0AwL+Eff1v/Qu/q9HYbr39MffEtf946+9g3dej+vvJ3PoYqTu7l1b3tBOLqcm1J+4BLG"
    "R3V9PSDuPtz7KpFfwsCpSifKDHOF7C61AtG9uMqmKfYcatPiy0GbBmpEJJFx4OyILfbMRri683AU"
    "n2M2LYYx7m12Q7Uo4btt1sd6aNApyIDU6dnVVsjddqoYUNZEn7/ongdCe+wmBVfWNuGahHNPxmtC"
    "uRyOBo6VQmAQe+ZGdtxUBNZoSNZm7jKfZ+wSaZVz3srZ9M/knxhbj+lNy4CosdTdW8DQB4KPeA7g"
    "VeMOU+1LNFkB9+dI+zYXk54tNXyxkhLxfWVlH9Ua8XdNxtKXLqSOcaUXeccJXYKyVBIzB74MyrHq"
    "bI09rPyiAXaAWaOU+YQ04l53PMQi8itI8h8QctGaQw0b5OZLO069YhAVEYPmeaarjjaYu9rBnl91"
    "sFEnONbzq4713J3r/b2Db39+8nTnjwce1kOO9mjV0VbEC3egR20HGs4uk3ZXh5sRjEbYs1YiML+C"
    "CvTlW2FzdZowrxGF+TKiMK8RhaRWA+fewED4q1YFL+YhVAg0yxGQwJiBEpY5f4QTEiiZ5i1HNTpz"
    "KslZ68uPZngoLZlVhYPOqQYki9W25N64Fm5JKL6tIIUtsR3i6Nz3divGNRPbmqJL1POqIHfF+WJc"
    "FWuqI0kuDHYWiYMHxZjNY6Vlb+0H3tI8pLH6uN6wvIxI9+FAhERFCjWPJn9F7bPLGcmlOdwICska"
    "5tCzYDjRfC2S60o7reLpLAeARYsiOU0QqC9Jx4DdISbCTJKgiMBYAhoxMOrgFqFDaOAZieRwYqgR"
    "zTBbnC7mYgjMQGiImJaLXBIM0GL8iZOqGxLPK4A4KhIjyKFkOqH1cThkMmcLDr+RhcTCLMUPQ14N"
    "xnprTDDSGjRNk1W4ZoGt8eHu890ne4dEjF682IcBKb1/16VO1TV/QfQpORefqsDZzQUYwH/BW2Uu"
    "t5IhSOX3h4+eEI/+Y57Nu0QqftUMlZz2vGslniHOoIs0d7fh0pS4jMW/HlT0bYiFl1SXr2h8K0WI"
    "EZ6QaHi7n/j8Er8+5Ts0LN/5jmWDXz1e/d//9l8Zr154ycueyiy3ejH0rdgwnsC9n933rxnudEKX"
    "Ar16wZnSUmgDdukeKnJuxIuXRwt2cVoc99qiSFZFhHgd+VMpLCVuKqoLDHbIHqiQLn/QXppJU71n"
    "gy3OtURLMvEbi/bP2XQ8xNmrpoF1TjdUKxmVHgGR17D3YlA2P3q65RZ9SVjagtz3ddICpyepx3DJ"
    "tZpwuxmHZ/p40JPgd7g8alewkdgAToT9Q53AiiwP/hCfjzBQfuKy9K5s0hJ+2SqU+a8LwGtuhWDS"
    "xOkgruN0KkuiBP+1B6+E60EVQjTR/+lGGajSkehSxTeGaSCXRU00EsU0kX0izpkHB6ibYngcRLcN"
    "ESaB7IKLIIhrGMTZDWsAuiJBP2YdSmiHkjGIPo83xhCJlzhxskMQEi3BUNBYJZsU7gRJYhB/psbh"
    "vg9TBgS9fe81DbJvh/9fe9+23ciVXPleX5GCu1uABIJ1kSw3S1It1kVSueuiKVIttym2VgKZILML"
    "QKIyE2TRQq3V/zCzPC+eV3/APM3DrPkYfcnEjohzzUyQJctefrAeVGBeTp5rnDgRO3awjSezMXvt"
    "xrklRq2X32B2ouWW6XL70l98lixxZxtpYGHsxP7HJYYstFIst1onhOkIi0jSj7P2HZDdZu7tkfLE"
    "Ss9h912VwaamvGlNTAc2sP3nUtz6GFUPsc+d51hZtX4yJ7sabr/RMbZFHUDxhl7BaOelpYIVcHU5"
    "b3jI/edAZ2VpizND1Gv4dtt3NJmJRlSYeWNOFao2MZXBgc9iaWhK0ZNjY23OVIRK9JhoNYFLftWv"
    "ipop9oEVp6NY2GGOpTq4kix2qjPOF001QBabRd+XdMMIwRRGhilaYuxJuLGbxkbSjE1bxv7nxrIH"
    "dgIt/DA7b0M9L+udNF/a+++DldBXvJOZHgTwUmtzv3+jvZ3UGigd7+i2VYokZ68fuSx3WCbfJuVk"
    "DMvdPYGAF772hOMZ1JIiVJtAjePpSCvaAT8RzWmV/Db5hPUjv763UQzrSUPzabhMUFPvzzf+K3c6"
    "XqEaXrGi5F14w0v8Hq24O7SYAOmKbrNORZXySYTK2uqJPtrL8grduU1/kbaIFN+3ofMNqT7yWwz9"
    "/rHtrCqy0AReLXHNH1GEtMfPwDtSLXFHnsSvDst7pU6RQWDUP38TFydhcvHZ9s0bbJ6mR0b0XpdR"
    "vlq+oX9EMx2+ecMD84bGY9Sq2LkMEtpnL9Ht7mMs9O7n6bqb6n8+sWt1ZN6By2Q4m4jeOYtfq+Q1"
    "Wdcj2eDNiwDQVfziKCyt0tKqVgDBRopT8XBNCEG1bMUQtMJvZKRCHASn9utKrCLIhJHL2Nc5LMrs"
    "0snbI691oyhQ3g2SmrgEFVqiF7VDZVwHAdFJh0yKeR023B4DvwjyjhsWmC/7so57sat8qKKlOrRL"
    "lMXYWNUXk3g8QkJk+pKv43QjU1wvG9+grbSJkTN7hzi5/bnGgyf+bboaonacx1B5xqQxMWYl8Ck6"
    "g9bk0zE3Y09ea2FdmnT6FFmkcAQOxqdYg9LSBfzGXEp+68xvzhrASs7AZ2w3tw3xklA4+ere2DDL"
    "WM5O++hkMhmGVKMnPtOoqGQeBSvbZF84EtYDn4cU+0JTfkdT0lmDvds2eyPq08V6enpK5dFhwa9c"
    "P0uo1rWLBXTsa/pRsafvhUQSl68ZLt5zF1iQi5M7pxaptKCGd8Rw7ML7dPl034cHLPKYOmosU1UX"
    "Qdjl8v0ltFiRN9dGZTA/R7zaRn2u6RbMy7xK01NenZA2r9iM/wJA/ecFQO1/xGbcLJ8VNfRxrlhg"
    "f2CWD7YTmPgHyeWL0yJsPnPpXXMomyHQIWXli73/Y2NelKhremG2qSrYzM/4Qp3QuYptjtaCYKWm"
    "NVqZpCtffgHFtnX5c9JdYwhrtmztOdRIh1/NlhExpd3AtNQoOI+et9nVvkbNbZf15ojpDP3JlqPY"
    "0LCLQrkVyuM3Z82sU0zor2loermUA2c6h/pyyYaG2NMtXTBPcPZ5nlZtVQQ3pEvtM9qrJJS/rZA/"
    "urkaDvb23jovPTpaeZ2iN23/HnO5sdJrHxS1EofDlvDF8y53htU0bXd2voQ2rT2QN3eJ70DxfDTs"
    "oUjCfRj794Qt0JJ3PSLLngyCs8u6YrqAiXc0Dg7gXbrb5190KW++S6oLasgi3an8thM8nJx/2+II"
    "5DRgRfsMojxO8+MB/czxoLt8vfdLCvehkpVggPO0IileCZ20l5MNeMgq9yCQNE6sXiFV+UVuvcgD"
    "38BFw3bfWGXgUwmHTWw4ZxvmHPD90u8DFIwDSnzin/cwdBj7y3tFheg772Hq6Fwd/nKytuwwbIDf"
    "82TUOoqYEI8CdXHgVGi7rbCO3jd4oj92wqsuZp/a3TX9UHTONY6H5J2cUM2b1xxR3+DKdL7jnBqd"
    "QZM3YlnwDqI4/3WeKPmGjTFwQQN8YPwlJ83eQ+Ubz5BhtqtWRAC8LX0BAYz3dT6SeC+eF3HY/xtc"
    "kmXb9qTwAhZysShCHW91nuKMAcnLvYSC1XIU7uTBlooSuyJN/r2Te9huDg4vVSmRm8XybLDjsR1n"
    "nKHnV/LTZRlzLfWo6cu+jFbWx6aQhVZQBfhizGlV5HXyUrMKKrY2SE2yS/8IEH1vLjjSuKMFtvY2"
    "M19v7fd766znr84p4mcUCuVZWx2q/on3bytcTMyr43TFOEDS2J7siHzlnGnXFqPyyrzaIRNtS6t/"
    "iobPwCaC/miNoIFEGL9KS8gL9MxnI+N51n7Obr6y8ZqpYZHU8yAaAPAYvRBI53agQ/Se2+MLDXJI"
    "qzyAiQlOIhrrUMJ0ZGHbiSxhJMdZKfib6xEUKrdcy52/xG++d3V3H+gA0OpP4gU90W91qRsxr+H7"
    "8OzIqxHq7TqdQ9+6QSRqC836005GP3GzavGjZCivndhLp1RC+5pKbRNvHBOvKxgjVyCGotFa4M+T"
    "O6ce8tP9dR29Dr7icet4L8bax8lagX0eLXoQA7IO4z/WwZBwqGa3J890mFHh8LDV3YIvsDVQswaN"
    "uVD9Fs5BJruQva8wOms5FpjYF1x1U4e41aBb6xNiIbxXjJP98DWFuMlXfcQdMHd6Ff0+dP3KI7nu"
    "ALkOXSzIrmgrpDUNrjgfdFANTzoJ4kxFlPxhkmyLxLXtO/BDiUm+sHFYmAU4tAhZzAN6CJhcNLO4"
    "l6vWGyj9tpxwGGrn5ybn8lkjR37Cy1UnILDFkRGB/w6FiiBBFG+dUOMRMgw3uRISXAQIu1f8VLVZ"
    "YSzXVVFWCLkUGm+gAZDUfJEWSx8JXAsjx1k5Ntnai1XRIKqLylaeDmRip+cuS0a4WdYMoPaWJJYy"
    "BvrWkwTM7hshINE67ZECSXNcyoGAV9I3oR7hmcbfnVvaOLRLcgXQcDExA5LgCBIn5X5w3609FN1X"
    "L1999/zHh3/6kTnIIOqwGvkwCZp8oXZ9yn/z0iqYUiy+AcZfk6+VKeVnjK9IjpAAe4MTV2azunXd"
    "ZVaQzlsomba9sxXd/dZG1+teNhjbA3HPbYWOdd27ZRF7R0/++OOrwxd/YMbXgNzVsr7eAVEDhmdD"
    "o0yNuJsEbz9+eRy9fOKTRzIv5alX3IlPufYBbgWlnwxW+YZUUH73h83dO7+/OzjFF2/t7ycLCAle"
    "LTQrqvQMGxzL62WR7dUwwGJt0lQdy5bMc2hJswHcLwzTx3zBMl9dLb0MMhaP0shWrP79/T+fHO79"
    "4+lPd8fv9kkw1g3uP0gAbmsmILQ5bIa3Ry3h1VhPTLj3gyznaVYP3Y7hb/xFhq0visrC/kWb5b1R"
    "JAT9TJqsr0ZxEFSYD4uW5uBiqMHxy19KBm5e6xC6fNFGYnlKDMkhTUUAkU/zEvw6q/xMFn5RO9oT"
    "McONYbstzE0xThsDNENvmwnbuA0FOK9UpWURKHC54pylueCcEFowLxhjV/CAerJT2ITwBeWG5eBY"
    "rYZwCCXr8ypFUk62FQIwSS3GF0m7RFaDXMXpz3/9H1xaeoVnB3e50YlHxUpdNS1pejHVUKMpVo36"
    "B6Oz1v41HUG1qXlVUQMl5SFNyVnazM6xf5JMykhw5tRMhnU3JelctInXjRFsFWeH8YNQpRLfojEM"
    "3nRTaNWb+V3UNJfI3ZKmrwzAauUlc9dmtl7kbO321UHaeL0s5uKBN904R7smYvc+Y6bSoXb3nDsG"
    "47JwJ5lJIpzbuovBeLvcKPw8fztbbGrMKsSuCF0PzVWoO+t8VsyLGW1kJW0HS3ADS9SozBhDKTBW"
    "9Ljs4jSUvDXxl2aCCuetOc34hIGAnmAAdN/lXOsCqfIHATPDN/S6pALaL/SADZ/a17m/X4h88dKk"
    "cwArnXzVZENvGVBenV+0CHqhZoDOITWraYxAhCyfMWNI0VgqPsbyxVMII8/Wv5Xs5+mMeXp5T5W8"
    "8xoeMPHKoS35INpDnWFc0XgOhbhfU5evsq3vnXGtRor56xoccC8zK2wDG1zRmFMeFyLbdNjcgeBx"
    "6aOYr1IRMxqYAiS9EVaRHMq5Ej33WHrul7d304O6ZKi1B3q86eg+AhuuJN1GvjlkBrpuRFtoy+DD"
    "bM7/lVt38+ZQ/0JKQ+rne1OqNAeuB01qS7IWGHQTgkFZeGGIlaDE4D3iHdojVQSGVuSXmf/avZaR"
    "4N/SSV5CD2a8Htx4ch8iNgqScWWT+gQz2oSoYCtbsi2EJK2LuCPF25hAmEi7brVCMlglknXKB88a"
    "igjMVI8qoi/p+o1b9Difi0Ivuxo6l2XUHOE9NjNZ0MreJOuO4uKa5On9udNvMP+tPy/unk2YY+rz"
    "5LPbN+4Gk8rK64ZoaFnpkYoGnzE2MT7XvNcM9/OGawZ4Ui0lQ7kEv60yOCz8hl2XwPwXCRDXgY69"
    "eaASWyRjUwDNg8tMAAVctb8nAsrveOt+/3sOmLnX2/neycIOwCuE6yGqrNycnQvzR8qeoVj+DJiJ"
    "iOoDs4sXrSiaGp+x6di3zq1+OadjBSmAZVlJFCxL7EIkC7SC1Ebf1YuyuW7ySbf4Pef0BzWFSWJS"
    "Ghtzijt5O6GGI92cvXLFV7qyRqHKkhRUcuGOXYLxGkKUlhWrQXFsIbO1sN0wS7wk3oL9ZXX4rEpB"
    "5cJBS05JN2ZvdBx/F8WdiXO+YauK1IBUmHydVvA7DmTVwniy4uy6Qjg6zVXFnyQPobzTxM/FWlFf"
    "OpMAIgWTNxs4MUs2b0Ao1ufpOvcYR7nSBc35gltjKitWi80CdKHJXzbZmRibpbZFoxEZDNMDVmCC"
    "4Ule5Rl3BJ+OsIzUKsR9YgVRjdNEXR6E5xfTZ6LKmJ6xypcsF1FjitUkeUlK2hnHNsoxydyrYTvg"
    "My71zaF9DeVFVTZnFlLD4Gu3H8BjjLwpzON7tD9u8syFephATiaR/ZAtVZBanlRf5ZbaFUsn35O9"
    "qB7IGY/kKvd3U9rGVnI0941pSLfOFD2i15WGbrVjGodpeKgFotTnWCtrWnnt8Fh9VBuZWst5gn2O"
    "VWD6+nKKnTN5ys/xwuDDLQJS+YRYNBBLdDbcsNo/ZkPXJmAV0oMGG8zYKofjL+c5KG3NP6wdF66d"
    "mNMyrZjKMGK+HavpcZUueZxdUysoAnxNizvD5y9J89KERNpmVnSoL3nOPjERzFTEh6wby6kMJy61"
    "Qh7Ewk3K0R6ZYZUVKxPga8LfMtbvsrGZvbBo2RdVd2Q2XtG26rHvp5H4Xu8jvH9fjm3pIhZoSrxe"
    "IejFyi2dv3RDvk9rgPtCWmVUPEU94DRgVmMw8S7SVVGfm4QUVtXiuEp6sICjjZNbkXa3WTRGamn3"
    "NiJAFzSZaEpmFU706EmGXbgOlmWEmXZVbvjgT6KGRw+HrqbkmRKeO3WYXknPqO+ofQDdFREzM6nU"
    "XX6/MJpJz6rO3GSS/nXk/EvZ8JRx6EhXeGlWO9IDS+jrOUiEytEatbqpGhUHScJ8zSf4Ci4hZspO"
    "hsZwhCWM57MRdB1kHcPuhHjYvLoPq/aqEau6bLiBsbAS7g4Gj12ty0gCyR6RrkW8KhpSHXXnpan9"
    "vq3A9s9UsX1zqjX1k4Ot+MzlOXNKF4S3/uG65tGfHj2DQfqz+5LZLGU5wYrGgDcR/DmAq3GFvQbt"
    "YOM+FBmVSrek745a3oJ0wdhyJTUQmW5lyCWH5edLq9OY4/ot5RblQGahPMiCviIhT71NcyCT3Ynt"
    "Dmu6aza5A22FSDvarM/gBgCcBNssT4Y5jDq82GoBeYnpT8juAFCixRqMgbbp4dV1fsqYAis19yI7"
    "zigZ2jJP0glrZqfqxYsu+j5MJgFJx/RJP9TL9B2+AEBAWW2WcYqTOmeebUMYHqYx8erCL5uPGvz+"
    "e2uB5kVdpil7I1EFRpan4uGGks3X0iwz1+ybHAyI1zBguBvkYvBsDSky/LCROWXE+YOEY3c+TvhP"
    "43ke7v8w+c0+B3QZz7xFGb7zsJniefvC8OWqj2buQ/4V0cTbFA0YyNflucHpiL035qqeN079OGM2"
    "pM/E56nRyb4o8+AKgnbVME4jL5G9lWRbsp88PvwTn0lkBX+koXbemJ7Yo9lPCfJYfe9togNLI8PN"
    "CD2oxo8qt6x85nHwRoE1D/QzySe9zokgVaxCKQhOh3pExHLQR3DkeYxtkV7dw5uSYY1GJXgPrhqD"
    "IFw5qIXTEyaDU5MVzDX3cDbL10z+XeVw8kOvhp1ynlcVe7C1A06Cb8Fpz8PT3249MO+KLI/b7YaP"
    "JGJdcqTyJCxIblw3W8dxZWmK7a6pb4prjcaDHpNdVzW4Aq0SOFGh6WicfOQsaU9g14500KSOYTzG"
    "MV1Mp0jnSsoyu4O88QPOE1NhrP1xajskqG1X5xw/ffLqRGp3Khna2/CAisOZW09PUadwnAGC40pG"
    "+Wfl7aEuE83wFu/OD8wyAnBKd3O3uMz4u/7R6Cf6m/9VxbdTUi2FyptE0lx0ozoSSFMOk8Vj3Smn"
    "PrD5FN3CjDEyv0bi8bharLH3VM1N1vClzXpnU9rMBDRQdOrBNLtWgMLMVze0UpeJTVpuxKj2rARz"
    "Z3GGHxeRzND/jvo5M5WFBUf5nhoT1fkwYNzw0wJ9gPItukebUTcuMzImvncskYiGyaDrewLn4QJv"
    "0JOjgIA9LCldTjlw7pqyjP2yu6iexmCJeI3GOvP/dFgch1w88JleBx3CuhK4plTbahMnlYQjVcrm"
    "JZuIPESX5Qdje/BrcBpDfk1YADu/+8RpKFo7WzL2/c5GjAqHR+qc0rRBFpXerieDYEa9GyHkY0by"
    "gBZ+99Z/gsmONLvsUoXkpEcRHOnkWeAH8u7SZhzv3qejtlx/qMdxEzbolpIu++6KmZs797z329Si"
    "1F52x+6WGDQCr7DXtbpgo61PONdvNEIMI0or7He9qg0OW469JF1dlWJWMuOZNCR4OlWdr6yFywPl"
    "aG9u1t0dSdev0xuMXOxQGwaRnneNXnfDvXbPS7PbqWt0+R6dbSfb2b1iyckBgkoV86DH26BPo311"
    "Jv35y/ZVdcp1inscpb+TPLRGiY/eNpNBDxPGRdQ6TiyE7Ov41ZMXj48kUaf5GEcqf3AxQVxSkS7i"
    "c0jKUN5FALv0DiB8w8OkX1hM+oXFtQOWnuzvlGNJsqsgapRo51ySgrKF0iusrbah3VKqKbezr5lm"
    "GvfR6rS2fz1TX7SCpJwpC0vnrWe0ejv2jGCj0U2OYh+ypdE/iCELcM9BDLd6l6t4ZY3D0c0r9WEH"
    "F0edZ7L0jFPHXybX+/tYDe1dZFKVEAv/Ya1un54VF5xPL3NeqMbi2ndMk6nrIkRelC7oQZgSGQHP"
    "FnFGwIrTwnKysR4GycGh1OLT1mk1iBpXSVeKR9TOVv2Ki7RwrJJsG2M2gYjmU02ihhamve0MzRzn"
    "bZ5tyJzxQK4yq45PFppGgR3mOS8apn9hDlqxPeZ128bg6BmePPc/Sr4/z1ee/4AT4THlOsaihFOi"
    "FC4NzbEjBnCfWDM4nW1Yf/Lt67OybmxaPsS55yyNeSBh7F5bu2BcGJsJ2RibK0ia/QbZX1I2vCyY"
    "AcLEm3uH6XbCCqhCp7fibehkF1xAuzVMk2FTzIRgAj+7zGRw2j7eD41w8uvDK+6J42l0M4J9dg6U"
    "CKFndtOOwi0QGuG5kZXfAUMVEarZgSUa0ahNuJC/bdpFZxddUcUsuGaxJW9meSLEX6Z8arJfk+QT"
    "RkRWiyq1FCMsi65Rd9KUgxOsrOj0kHUZSKgmcfzxddUY9NskgCb0/Mxmi2bUGgJjGMUOc7d4zGIE"
    "vcAigsnPWfwUqyKGajFIN5flgSuXbdxK/q1uOynRL6qiga+N080uHIMEEPdD6RvMjdk4WAueMFaf"
    "uOM5KNk7ONvU+MvJ5uFw1HfgTYWD0jdQk7bkZboKH0dj8bx2rNvzfooWoSKZZU+vWQtgfh4xGacT"
    "ljz199QXQxdsPoq+aTWEy5VJKAaAMpdYr3kBFCCRpaNNpJJEp9J4Rw4mhrJjMC1Gz1EjyFHJCOlm"
    "V6YsP7IsKsmjVnVH187wTdoXNel9d1noFGumRIiISAT8KtDTL+dDySJLt++OYHhbDr0z1p8ndMTS"
    "cP+ASmikpO5hV76L/qaF9jCMsAPleRiEqL3PVLU5b74MgWjtLe2wPknZmsiCdGAZM0vH6qrnMKV4"
    "nzDWEa4TpvZFHMMo52VfvkTBggfhqPhxou2h2BGNa0LZw2jOYRT2KESzJtwxLv23o0miEMnL81y8"
    "bAh5eUv7ZbmWXKQecJKBdOxDLlYXOYPHW2NplF6SvryeJRROOox/Y4GdhhaJYadp07hmtETGLQWU"
    "+DbDHixwkjebWrE6ECaWK4ga2p+GSHNTb6Z4CLflQ8ZBrpl7T5gt/3Q4Z+nPlPktIJOiPxRAEWI9"
    "XqUC0RA9RdEZKoPVYe9hLKpi3jjshstoKZ5jkuOzqphCS2HYhHFGc1nAtbDrn8YbR6rMwFWMA9sg"
    "cxDuQ/tJNUk4y5YFkQQ19D2rOCAgg3FpcDdabyrxirloN3UBzAD6kJuhaGfmhBNwAuO4xP8I/b0W"
    "pAY8v3oGKNzaEVB96jAv2qDa2wxNwx6lGTvRLYxmXcGTg2uAH8kXubBlnje1CIRy3rCOmq4CaBPD"
    "IeB/xnicsZa6yEUSkKqxMfQUXJIgnBoGMh0I0HO6QOyoF/Vxi6kqpmV2JQqYdB2pwA78tfIGgJ6g"
    "Hmd+/WRakIJQmSiCSXLEXS9wNq1uLZ7b6RUDhrSlNkNAalqpVEzcFtheBHRzzMT3G2meAO5yPpzV"
    "Cu+REbQAKJRbKm4IQQmpfq+sJCSO1HjJdHy5sm2DQCwXuej33lgz6KWpUohaqQ3bhJgeZ83oJO/Q"
    "hJWF1bIqBVEsMIGas6MBXqOtAYLXzm/zkMDAqnNSh6nL8fp5ualqRQHwgCCDOauXV/i+LLEFLbBK"
    "ImI2K1IyEVA2p2WJ3l4WK5NqITPCEXDDnNGKgBAVFWnzc+kXHi+JTjSaOA4/cHOZnOb83THAonQC"
    "udpjkIGB3DEMF/NFll3K4SWgvFtCypumoyCe/Q60KEhRDNAkeQ6InOSF+B39sSqakvGJBmhBQh6e"
    "M4OeOuIs5YIypG6s5EAJuKkCMj00FauSZziJrFKswXPmRTBHDSMreG340gRHLruGNAODLHwEUgBG"
    "DZ29xvLlhmAB2R6QVaxxFJhthikJfXAODle8wr20WSdQ/7ixm4aP33Ho5ZHSM/6UkIhHlIYJtZSt"
    "oxWBORNpY+8MAGLGTnHnU3Zx0w3qYkQhyVYie46cyRK5Q3rjp3hJnxDph4Ob/baFB4xZPBwobwt+"
    "y1dBsHjLJNr1TCAng0PAVLM8BxmcF3X5DItq+JgDzMqK9rxvn/M1j1AyflpmN5cjDnPjLh/73vKJ"
    "X8JLRjryKzzd+Jhp/LITfFM8n+zgpEUnHmHNi6oxBmGJR88OuSHmTarRqinmhSZppIn0yd/pmqZK"
    "qQmXoWv162K9t6BFtbAFnqrt1ox1beNfdbA7ImN7x/vebTPex5u87hlwvUVH5dudI26DdgdMZ4mO"
    "kl9iW8RvDs3dMRPu3mgmIImJZor49jmJxeOcZDGGedwrHmiH90eCtQ0ah31ZzursxMHTwCTxnSNF"
    "3CqkcgzY/yS5+8Pm7u079+6hD1gP6Js1seuHBaExzOM02na0JhcFqx40veIYYwPvmkeT6oktMNH5"
    "9YpVJTqxki5YzemUgk1VB+9+YpaNWRK4+T3jrOHBePLysZofruwE7J1yM+uE0SnXFTTdO+c+szLm"
    "+JymfGvSvdqwNmDqO1Z1wTw8pgJ4CIYNC3W8ZcBpralpYtj8eWkdDfSbrZw75uUnN5qXrqoqkMYy"
    "E+XnV4VsK6/ytTdl/aGEMYIn1+9rUmUvk6GI1hHKFpltxYs0aJI4ySSbziQuj8Y2+QNM3sO7rjDd"
    "I3Wfmkht5qRoFdNiUTRXk+Rrtw2epWt6xE1mKPNGtnR+To9Zw3vugyYOkETZYxUHk8RmTW+A1N8r"
    "53P6zh8QcYwwrewiFTSpTmY6IriZvqb9tw7n5akJoX/88vsfX3711dETiaKXbYoD8HUNcAC+nfIH"
    "oEA1k+oA2XS+qgr++YkLy390+PjJi0dPfnx8+KcjLlXmBU1irPNiTw5MAyr5E8igVXOOm5Cq/02s"
    "nvjz97cl6v6j5Imn+C43HH/xHtpvoM9P0AOPSHqs0bmkPIBpyqis87RYbBh37gKka4VSJ7AVVJdF"
    "nZuzh1+rIoP5AfG8V6LbqaoEa2dh472nuWaCkrcmEstymfJxiPRqFMBxZGny6vBrTkFMsrjGESiv"
    "lulKEN0A4VPT81kKi0fRWHoKIavgoq3CdJ4igiRfCWAfR0+IhXTBk5lNb4Y5UcyKU1LMaXLLOa5C"
    "vjQ59hl0CF9flCXHt1UlHfNJT1uTXodMhkXm9ReNzYr2gyr3UnTkb2khLK7k9HflgPQ22IJR5j4A"
    "WgPWP/RicLj/hy4Yml/kYEJwGwQpj3N2DBpsK4c1iZ2AIeM1A0s9bDpmA6cU5lgT6lLPfsk4GhTI"
    "SFWOO9QTzgQIleHguxVOtis3IX4YuDQlPwxMILqUe99kY/UgwXMYckQv7Ui5Y33JUk2u40C1WBaC"
    "n4gRyBlRW0UoqxFtRvUwjPUatUu19wbXF8bP4enj747Covw7Nyjo75++Ouwsx7tx4/o8fnJ8+PRZ"
    "Z4X0VqsoLunVk8PHT188OToyL2aclQuagrnj93jW2eOM/baOYVOSOlA9lkfvlZq5lGWSjtyciyIa"
    "a2RCPo0n34syhNAz3MXDRBWrpD2qMK+RgI2XktpUgpWkKPGfds3ZVpbncN7qvoeSgFLzCRrttQcP"
    "6LA1B5kP6Sv+JnIyn6hidLqz2wJo+xkTmXHh0muOkpJv+STjXuYlr1sfGWVs5fqXdfagh+N8Rygc"
    "bL0Ta3W5pvR4tJhOTsxP6sz1C+t23w6EJQSsM8y9TftgzoRmUms+v4tGiPKoihrWqZPAzgFPi8vK"
    "S38OBMn7PFgDyuH0HvSnppE6c38wAh9FJXuJu3HF1z9DLpjPRn5GoQzm1aAyD4tLWx1s1bPzsnpa"
    "l37N5CKCYZDnyD5xP6p60DCmoGNSjqEPrucqHhdLVHxPC7aw+t+SvsKo19uja1r82Y42NeePy0vk"
    "GySRwm1aGb5cw4laMajT9rWfwXAJx5NfeO9TXr9zid19j6dWkm0YMJvPxL4dDIDqZ8OuujY75sQi"
    "146XBjcd2R2bMJ+j1x+GvMQfj8/leflr9J5lI/VQVH7vlLNK6Hu3WfP8GOEmGZmarqyVHyX34CG7"
    "YUe9+VW7BoiRezs6Q+ch+0rgyoIWlDHiZ8YyqMmVsd2KzzHp+FimckAVht4xDJXNufe33F1tlnlV"
    "zMBoRtX9x3IFCUg1FBIIZuYRJerD2pyGnX1/Ds5dTh8g9j9YpAt1FZCSKWqrsxJfCAoEfm8jEWUx"
    "JEdq6Sgaib2rm0ohlrKV8KggjhQumQO13YvjAmZWpnLKMytfIbvZQOoYwoaDqTnpiFmSUQDUJVW5"
    "MC4/RhVhMxscPjVmmEf6CNKccITDij+tweUcJZ4Vc/ZyNDa8nO3NpB5XsFsPB1+Vm4q/zX08Ld8O"
    "jIF0QTq744sD8Z6GuuGmnJrEFVKYOiIak46hHFpnrAquPnVPqLsH6LlEntzesGGx/EnUH+cxDUJO"
    "dQIAH1CLih8QpInqccuPKWMXoMXd2/hP83Z3NtBA10itrkFiMbgzdVqIS1CqH7S79w+b27enn6k2"
    "rs+HcDnxIWKmWwuQWCt5ntQHGtjMcYl0+KFTqbgDFziP0Wyl4aOumzlPIc/KvNqjA+GeuMAdWQQf"
    "A5kO0TBNhT28C+7TySolcZ1sjLN8awpntvCiNVWsqNnOaz1sTAYDVg+F/CkBwS1NDqKp26e5j1WS"
    "N5UgRwjKYPCYimdISdEuFSHYlIvsliK9YAnh+SiUL7DVgeHUj91kSsrrwJ+ttLFTRjYjOMXAmTl7"
    "bKqXU3fZCmoUZqMvHEWIepsvDhLvAVIc7wJf4ZDlPoWL8H4DawXroSW7c4Au8wib5fxiPw6q0REA"
    "YTmTPZ7NiD3Zjrb4Kvaacs8S1OgEkPiCYAp4ZyUtiSsS0AkKUqFJOuHjIXg8zAhxy4ZYPSnUamD6"
    "g9YJGygMPMzQKhUqiph1LxU3nIdJBRxnoluRZeR+23RPlH3T/q3YSdnatkXkW13vYFQzE4PK7ZgX"
    "MidwjymPdobX3HCqHGo1AbOlbZ/lve5EwYxxFcKE8f7yqLUd06qZMe5Se86c5wu1Szm02CWSOuG0"
    "JKYyg7TD59qzYribQcyx78YTwsce13TQa1iKlhYf5AbZEE4FEM/RDialoG9buFa/Q9+DQMqHBDD6"
    "b3qVcFCcI45ylUQmNiGRMg2W2PzgIR9kTPt9pWjwDjirHV4rDdDLMrxOHuBaMLjMXLrMTYC8Ia1Q"
    "KNCaQUDhStJq9EhdgJZaJNuMXYNgxV2zcqQcKzO/SO6GR3/27OPwL895QQYbG2QQ8OcHhNVGfdcz"
    "oRSCLhdiUv37zqmgrPb1awKlcjYGKYrq9sntXZPJTqQ/MnQcIVjgHYc31HAGTXN4yEySCp5YUrjB"
    "n2u3CvjcuOoHrqpUdSNklWPVtSFIDU3r5uk8yUWW1otirbwoCkZGcIIgstlEYYhcAvo2Qz5Ox4S0"
    "b6BJ40tN/kGT6NzwkOM9b2Dv3ajv+GOOCWqzgikL6XmC1RgW/nEkupAOCIaeLCxL+cpEEGkJOwjB"
    "zeIYeWZvkXMyOialDVi+hU50St967RaKT7JlwNafiMYoXQvXAHwqiLylpn8Nd8DA4zceHHKk4dgj"
    "RIaPE/kzcsZDHGiGR0yxAftYHMNLegZVu50VYBWx2Ae07DZN/VdAAvGRrFb2u5lypiozkM96tijm"
    "OXMDPghUMpC29kyb7j3QY5tnk1nPyxJ1JQkE8dN/8bIUk4t+Pwp70qxB5qYd/A4WSKBYb3sJlRac"
    "F8jHIw7QR5DW7Cw/ELXM++Y+dfWXye3JXSgLUi9SCe+EO72ldo/fpnfEzRUsoAduyUCic8i2rAsS"
    "3nQUP4gb7ic2H9ucS92PiYIW0vR/LLk3rMZYVIEmLzIFJ1EI1OlVFGoprdYwJf5D40ut8PKb+DHn"
    "9KKle4aDsmOgTAP+SceBZ/gsJXblnZm6In0Z4AaCZxPDg0lrzhc2AsZN2ExyLNw0yM5LE4M3bxJF"
    "R6v2L9c8HsTKeZ+ROD5vJ6MP76M4t1P1hgqeBE2ytN53TpUSibSeMG7Ji6wSViARd4b0jX2QLjO8"
    "z+SWSGCDsSKk5lVho4J5yTCgITMnO3U3K9kfMSGYKw4jK0TXcvgr2cm5GAfOxHUqoT/sQA2OgvLB"
    "L5IPMpcGA2vpA+qsB+Hy5Xnird+BClWYu3QxsXS1iYn89TPo6Lb5zhA103QboqZBdB14l66wtbFh"
    "3FNGuL8vqlQnPkmCnQ3j6UPy4/dMzs4yI3FXP/s0liqOYTeQLDZOLuyI9w2a8wemI2gujtbmGDsN"
    "jKt3xMZpCKqfJipG0/MjXvCbDXt7Z0whr2Lj3g1gl3JeVArFunTxCc6I5qjn+BDV2ODES3HsS9aM"
    "PhOMlGYP4QKqxunHHHmhWILPyodwYoExclJIzMwcs2Uxp3nonzfHA1INLVzZW1lc9Z4d2aNgVZiR"
    "ULBet82jzO91x8bv7u2a77zHXn0jc5C/tQtIreeNykt76YlkTIhIH2jNHofG4nXoWvsl3E8kla4x"
    "F/ldEj19vSJgsjVfs8MHa9ktL6F0S535UcKEhl6Vbrn4Zb+iHxtbgckJ7K8PX1sQZg/TJaok2Aut"
    "HAJUgVseKZFHqtDztYmvxfs2M6/ioWFt0FqDg15zm1md3P3OWKYp0ZzZNKj0+8Z0jsYReZlN/gp9"
    "VPOyjHmQTn11YfXaO1dECVjcWeKuAFecjpHZDKe6BNaSUknDYYoVFz0KV1rKeR/5davWXCJ/FceT"
    "0vMnpoDTRC9c2gsPkjX1y+VY3gfDiOfB+kkqMzafMducWU96WQuLtVt3R+QPLxGbQkqRvSY/tSFV"
    "KRc5YFN+ziVTlkNg1DYqgg73pIhYu5d9FGFl/UldgsdMfhf/6J681H6FcbY24HuBR1jaWLP5vxMX"
    "hD340XYH5/iwCD3rJ+qmBlyDbnH4YzMc7A0k+vcFGwOud0dDc6RSjPPlOk+i8RtizXe4DRGheK0f"
    "0c97o3nFhbe043C7ZMyj79blJsll+Pn5mv55pn+y2T+4KI71v/VADQqEqUHUqU825dOjl9poL5z6"
    "Tqi5n/Hi8M/iXipncON/YWPHv6U//YfMMhBsMI3pASowNp1wwCnaZNrbFUKfmliVmZePXJOVpEk6"
    "xal6sJMFViUPdT7cp7KQOACXKnz7Ps5Zt0EMawgfWLSvGKUbmAaKut7kFlveyl4oQPOOgTScvSTq"
    "OsecwwwFRvbjN0+Pjl+++pMnAet8sSuFobSGvap79Cipgy7TNf09kbBImwMJlgatT5QUGQ93Jj60"
    "pMOTeVkBcz8cVuOkGLU5ZkpNmivfBKJcSBawhj0Nlpd0NUGVJd3SRLuFTfkQQPp3nE63nJgjkU7V"
    "wt5C7TUDqmFmM1G6fKudf5izodkExKYh4eQQScL9yF+2n+NDm46i9s6J9yozkprrt0+DCr0zg+N9"
    "6cv2oMSz9JY0JOoA7ylNQb67XpEICh6XiXCTiUZyNkp0vWOE79+gUFlZrWLtxLilG92jFpG4C0YV"
    "VDUH0NTCb2MzLw6OzBFdl7CmgGnPRUs6J6nx/I+hRDpOwA4LDrpYb9DETKh0tGNjKphrLXXjhWQo"
    "dS9xylJ6hSpl1Bdk/g2UF+gAwWdtAmfz9sCvIXtydogQkql7WpzIDrywKwnqDBwqQX5sJJ1L1bof"
    "1syz59gk4+YlSQkdIeLwQL1OJeqobNpFjg1NY3D1dHK2uFqfO9xfnH/6vMgyNkkPsNXIVzk1uUiN"
    "bOw6aEZn7yY/prn4gk7Mw4FRYYxu9Orw6+jjurGC1sPPGe03lnPMjv1xH7nO1pdQwKhDRd45dPzQ"
    "QJd/xZmZO0bOw6au2bwj0yt0UM1ao8pDzQ48nXyBX2q1jF6AYhmmll/3jakp0A6nVa29kaQm3Xgw"
    "SWFemo5c7xjOdZuUEQNqP2/Tz5vCVstwJOVUCs/FRH6OOkd6zavRlCZDY8bZOaY0Dp4DslUldkkY"
    "rIJs4+E/1NwNkyhFwa3EZwlAxHxuhGTaeJkMWJ8thCmhLtkcLREYXr6EVPngmaChP2GCb3FZ5OmF"
    "4taUDsBmXEjCsNpVKYfmykTmhoaZku0n/fNdarln4vu4Hzn9+XWTvmpk1lsYnnCGh9PfyTXtSYwn"
    "X9XX5Lt2hmO970h1XwVIbGMmSiPZiVL4alXhH1M4fpv5gqfP71qFypQbFMyhc+FqrHDNlAcE4yrU"
    "YTVEHIgmjfZnKja7uUpEemPA5evFpvYpS3A6YZ4QH82NiWVdjIWlwbDIRjZs4CuCZDRl1QvOezZ3"
    "GEoL3Ew1+ksBPkL8IHnNJcjLsp4Y9P8X5qu8d2p2LsmrAPW3Y1TkoOUrovQUes8enZWjw57FAOr2"
    "dFgXr3Yyh71wDoMeq4FMFAigtn4QpfrjauRiVQFkAYU00Id9NgzJ0/4NTEQDzfo28lz7VOV6Mx3t"
    "+MIszWRa4rmOeYY3/bmtl/GIXvZDHPIZLykqTcXOyJ0HvLeDGUmPwpqfzybno5gMeaHTd7OQZ5FW"
    "YRA9JCGxX3AJQXLXB+5SQPKHlCHITTIZWBIXPxpEYbv01ogq4Fd5Udj1VjReXb2WbQx74zvpScih"
    "cCfnWIZbhuxkZvFcyK90oKhVDYJuJYTKrVVnHCw9zjZhEp6BD8N4sxlLxkjKo5IJMsTQIsh9TQpq"
    "6qAJJjSITlyVyP260czBIuc1L7RWv1znGvzHKY74iKJbwryiFQXf+n1d4PW5MO2J7R5wZkluxJGO"
    "nJ2K3T/WvyYhiV5+DbNNAX7JCZlCEhr0EBu3wlQwchBf5zMJuZP99WuIGw7Wr8+LtVi1sZuRqB4z"
    "6QebLiF7FGStlZBEnwqBupXYYGSeAzWy3V5oVKbUUFMRmTS456WNzsZQBftctXOTAwYFSVvdSb4y"
    "S6tqbXSTycRGgLH5i4HxmMFNZWcw/19nMN+CHBicsbo2NsFiY/+WZEDEPf4V3kT38T2k0DMUor46"
    "4ydQw7mLe2wshDuMz3GajSQ2MXGhMg2nOduD1HNasnqR28TI4M+YpYh+By+cZZ4RMPxigc7XgxJP"
    "Je1mO4ANzEW6l/DgCueDSfE39nDonPy9pEGtFXHESaBpsKWwK7YmlWUGgmJ/eOuza0w2ZzkkgGep"
    "ObNmmLOuEfaCRIeAh3VZX9qnMv4QLg86xZf/5IxVj3CiJIHeXq9K+scYXhC4MtJJ4Z5YsqdWlZPd"
    "4r3O3xZGgYuEcs7gsWbCT4w8Nj2DC9CCSEJ7ZF4G+tBE540al4o9qPl+3KcJWXQF0HM3P2qIO9ce"
    "Hssm6opG9vLcZ/Fz+8vCGa7e7dpXrN0Ud40RKQa11TewDy5y8E54821h59uia76dnAzg20ZTTGZO"
    "ECucDLAchMkg+VZXhtzgzccRZmSD01M/Oc7w5PU4Yb34NKJf/LcO6ut/nyEUuck19sdQx2NR2PFr"
    "jUezc/HDJxau/cau/aZz7YOLXJZ+YyS7rlqUxau+4Z7gOOO2rDcPU1vglXCnX/h4HX2o/yjyhfCz"
    "+NH5BHY0fgI/unYAEe72tJWGwpg69kqDa+gJ6PiMmRRCPLbjFcbEr8xfcijg8QCJqtLivuIN39jo"
    "ROtnJaIzE6A91yrhKe8cXqRPAtk29gjdapefkuc37UVnTDsYbuZnNziyhmNe2TGvOsc8Jg8MJf20"
    "fBud9OQbiKiyc5X+6NLAuZ/p19zf881NjQvi23wW6BLPJ2zagsHiVEKpeSwczXbPh6Fk23XFC62p"
    "xJNmlxpm5UFIaNtrk2O7DSrRJjCnCvTJyuXOoRJrTjhSSztSy7Nu3evou2fHMlTLaH1aQ1HPklxe"
    "KLppqe6FrmeMMWE5EWHU9YxanJZqcRq5k8etlpvqGFrtUCmKpG37+0nNFiejWIWmE1LXaJyhIFTl"
    "5WSmjQ9NJ2lVMai0OZ+82ZDqdMSuqLIaDiZ8a+CdU+kZWNFJUENg8Zkcn/9DfuU2e34pcgfgocdF"
    "5XALP//z/+UT8c///L9tVhgqvGMHqCXUs1UCjFWKlOPsUPYvc7CT+PmfOuszGOC0Q5MClrLOL47u"
    "8/7uTcBZid360ctnapxQ0tm4Hzyva8nErcxPKmN2GgcjBCYsRqA9zhcMcx+mmrGL2noHwCJ2D0/j"
    "i+wC1Wv8vbpYvfYz7vmlAsyr3fgRmjOZLddSF550vvm6Yavmrs0QD0hf889dTocuB/ONcxwYEAg/"
    "8sFbk8/TRoTjTHKotlP1tvVWmjOW8tlwMJqIagHbEVLXWPjT7hJgezMF1M3VIp/QkYPadxWVQxOU"
    "p+UKqlgXlQcejkJMKt0Z+PC3cSM9kF9YikoPLSNlX8xeSOJRPeaFdn669bAx5kWa5Y2YRlmVwP+m"
    "zWow7klXaozzUsakuVrjM6aU6CYzttPdlwhOkjK0zCxv0mIRPd/h110UrIeKWxcxTt/V+SNJwaI1"
    "kaZa674UFbRXicA7MmF2leCfozZT7gfIXN80F0DvGMNrc8rGmRoX3tZudzbmXGm/4gf/+ylrYgV6"
    "BrtHqEGz7ojLojvKi4F6yHA5HUnVBL1y6VU7WqIFuptze9DBY62jjm+VxyyWzhl5r/kVBWAPRku3"
    "zYe9Pw+NcEb9dNAzIct1wekz1uSsJckPATgQXU+C0k1zODadzeHnYI4tsjxlnCuDx1NGqRuTnWaD"
    "iMKN1SBuylNThYYs+az3qCiHr7PhibrJWrZlDlnAZ2dHeNNQoxGZJe5muY8cYOuX5kAa+PPdzlXB"
    "znrRkTep8/c2s9SBIZW3BQSLyqyH6wvV9sWpMCV3VCvdZTt1pt4TPIqRApX5onw/FqhHgiSOJGpc"
    "c36qXXWFzjzi52zfijYSZl6q0vXj4qJLaugtUzjP9Ge0tfuMTzZ3jr++gjppKcEq6622lYB242HH"
    "CRwmQVJYRAltmO/8hYUsdHYsfyfuWclcGfesXu/ry01gyYyqq1ksu2rAhcY1+N59fcygPy6FUyN4"
    "mX6QcoBTWUdJETq+8n38hSedX4D9sf2BKGdCR/FPwuLh6KcBUdPO/eDDj4IPz2a5gYXYQ1Te2N43"
    "Pky+Fj7WVCkT1/mP8bXwsXmxWERP4ZJ5CL9VSbosMqCWSV1GjgCO3jANpVLtflAszI7AlbJ9gIdC"
    "K90M5UjPemWOgrfNHjebgCQC3pUAeE1j8FyuH2hiFvOYPbt/9fTJs8c/Pjt8+OTZyfzUj8u0zkUm"
    "w50X+YKTyLzZFDampjBsEwiQ0KBP0+rskWkbV9WTL3Fl3YbxqHfJDvQVboZfZ1vYye3TU2+naH0F"
    "oQAsPT9mqHnrNrM59UrQR/ECOG4tgB4JetwrPTnlR5fo3PGSk1eiE4x8wXjc133OyGsyxX7O6Vna"
    "ER6YZJmNY0wO2m/iIMjhTQg65VMMnwIKoxDrYyjHtu5dqz+P4/785pqtKLIxRfriNM3O8tgb24Xt"
    "WeUbWmps4//5f/4rjsDZ+9hkfUBWoK+yPT3ev/2x+ca8OQ0P794dieF5iKbYnJldc/GbuO++65uL"
    "dKt/vwnz29Gop2flLjWpHQz8aw1KnVdFuWF+45//+msPylevnhx9c6LVP51ENnOvh6a9k/U70+Fi"
    "BrAi21xGZ3GmoxCznPgH948/jvqhSi/z4Dg8kAOdZ45K9Cl3jkfDw3KwAbaWTsKXaQddHK3ZLsEm"
    "nTAXcNvv1WVOTVkhn723p+tktqjHCUPlEAdx9OSPPz5+eXyS0rhenF7vQTEwPFfKv8WPYuq7ysOt"
    "HFdCf8sq7zrkZfAtpsi1M9qBwxS1PPI6Xp5f8bv076jfsyPpgILNH4df5kDQ18GAe2NvHQa/7a3T"
    "yWQOv/nC3QomtjxnJrejBzk7W+QtIwt1Ct9w/Sh/d1tSPLQtBw6IHWQYTnO2nf6fRI2n/0/QRN76"
    "8nd5/7Ij3ImTxQnnTny1btc5sKByJYfxMx0zL3+75tQsbBBISaq3Cr7OEuTWVrziPwguuAlwkxrf"
    "sM7qNQ+/5Cbbux7ThpTtCU02JPdbU2E24KyTMZJeY2WcZdGLoHQ2VO+eo9dRA5BvIMUDknVIBzkI"
    "rSlm1in3RcJjdZ9zIqFetWMgX1+FqZ0WxetcIE9K6b2oc4F7ZEV6VqVg4WNgzC02S6eZgnVMreGo"
    "U6+ZXhEeVTbxIAIdkcTTXGMTkzotGPw0YKSKMtDUxduBYj7q3CKmmOlQ8lhx9DOMQGtRyc821ENz"
    "5AqYVuVrQQsWLg2MQGHXQg9+tBbPJWkuY8uTTltH/jafab5DpiRMBEt0RoUwWOpFWlXCbAUIbiP8"
    "8imgLzBIDA1Oc3GVLMozkmQcTY9+xcQYwabEXARC565FHCg7ZV0sN5pgGpRJaCkJFXaCci0clBef"
    "YdSXl63mxXfPv3/56jG8E4N/yisS4QPGDAyaS/xmDzD9Oy83Ff6hJtA/6GP6P1IL0b/S++PBqpAX"
    "c0lIMsgX+kBzmS/4PU5ixJwyXKD5KSmQpFzzi9MW5a58+YlP6E8qdNVcDWyygUcvv3txfKQh0GcC"
    "EBLhx6LDwatcmDENHq+PA/tUvI7Gt97d9yIZ6VQqS0AZrD0NYFUy9NUt7MCDRkfD4eAEDrM9Xtun"
    "pEEGJv+5qB9owgmKss41edzTNudw2vUQxLsPHECDbZVDKiNCwYsVqUe6DToOnvkKBK7w/+mcOFkx"
    "9lXlXmhcBwfeF/IFT0ipXT+6Sg/u//nkcO8fT/eFt45eBnMMU40FmRoho1wA6kFyaV2gHWF6xUxH"
    "wQRiOaE1Up8XB1zF4kyUQ/WYgu5lJakcofiWYENgw+3QBSXRhcTmfht5jjHfKxY5TP+GS5aiPAeZ"
    "j7zt4xb3vT+tY409v8jxpFYAQIwKNHdh2v1eDOgfK4/3oO/pwZfCgOPTgf+Cdz5K7l7/ns+96vFc"
    "gWjPHuWmwQlC980AHMo96q3J+/YBiE//72P8EzxxRPJnlvtXQL/1iLn0LemUAgwbpAUyaFOG/dpJ"
    "8OjV0+Mnr54esvw8Ym61s2IGj8LZCvOCwVSbWvi+DFJgwLnQ8OMrl+nFZrcilaMEIYvgtlbzQnmK"
    "V4J7VE6TgRddOoN1d5eL1tRd5pOpswsFnYVgROu0jkx6AIyaaNLysusIMOM8Q2FMQ52fRYjG3Lrm"
    "6WekdVWl9EyVZkV5VpWbdf+zQZzGrA1uX1wssMhOBt/QDoJCn4vy+YzOjqfxsdxFtnkRbR5mfRX0"
    "sJxqtJOHA7q78WDu9KdV7LkhNLNxTcIXpCfZY1fIdRMQShUO/TOmQC/GjZ7vwrhdeKd19JSLYAvO"
    "69640VNmnDB/zOVKGezfdaUjbbBUSHFakWbni0hSqkjsXbG6VRlRC7rBkf92G+Vt1mW8m0qCB2SL"
    "ovt7dt3Inza1c8clmQ7eHaboiv40DynVct+ygVzqxDJQn3yjDVb2cFqcEDkHMeFSB72S+gnHJi9i"
    "4lJVC6qdOcXAO8D0nIpYZtIm5pHBnUmCPNMIwzIdb8HtPDaSGRMIOj/XKp1bjBZYp3AafBjGba2E"
    "cYx9RU8z1h7zp+z4TBtPOvR1l7w28sXC2nU8Ay7w5wtXaSahksw1qXV49BUvtRm14TstqrUDJqw2"
    "LFjiwRh6NEt87GGPxdDyM0lGz3OGqytx13VC1Z+bFmn2QQe52Yh7dtiazBd7AvniZg9eXTtzWsRc"
    "yq6OUCKdgPc5hyoj9G37y5BDTupqDekmuvjttz4NIxCr/kvwgzDrnEcJN4o1mgusWf+10e795I1n"
    "w4v2E/OEwF0vJm9G13ml3gReKXEmhR6noVf3ZF+abHJUOzdUnz/rzTX+LI8Lz7Hs0Wf8j7a/1uf0"
    "kuukPgbcAbZdnTtmsTyLmt+/WV4Ig1mUFvwi4iuL0oAbs6d7POQuc7Rr7Dqy/IRsaxqa+Wh5hkYh"
    "M4SGDazULXnh23uaYt1HayE321OnaWwzo5owiaipxCD0ZYUYWZrEDGlliOzJSVc/QVPR3wyh7+wc"
    "esh1zelp20YcOWKd4i/RQh2KVoMHqX6RHbXB4GLP941brn+qlg2UucIvJrNFQT3/D+y2sHw58GfQ"
    "PVZkxJ9BohB8UogHOy7Wh433KtI36O8/2a8o7tL5PWRikiR9iJVCu9EjfuMVdQ0NqFfwdMIGj4+T"
    "qa6wfSQHnE6mZdOUy5E5vb4LllHLesg82HkFaCfiOFbOwXrNGxyrRK+ck/J9bNFPfS9Jv9zsA9MF"
    "DClRwZ708zzcRvJIZszeVbofL2JPQmv5F50KntvqnqUcsX1jls7+PVH3tC7TpashPrdb1MQP9wka"
    "i/GRx4SWURI52CU+Gbiwhn1OicnK1gEAsmekDMKtJnm/N8uVMk9buky2c6ZrR25xM63Aqag+MQYt"
    "zPo93jVqaku5sE90KhihepwFSsah0Q6YB4upBIzu6fQETx81gaH0NFUbtAKkoRqkm2qlCADp1Spe"
    "dGsVrgU22DGbrEadSfPiV6Jw//iQWi4wRBae0qVW0DMXzqDPHw42oWlatRw49A5dNsXSz27PDW6I"
    "YnAu4ZOBZkCfEs3jBRJifcKTef3Wf7V/y84mS7dloyDB05qh0oWggldTFoLtneY2fXdZvB25GK4L"
    "id+64DIk/spDtPw7bsjaCLtsW+0YdO/EXGcvF2PYsF9tQ9UZcTHq2lZf/2fdVDFxfvUtFYW+z4a6"
    "8/nu7bT7la7NtPvJzq3ULXh6yRwp/e1vdmmuQhx3TAUxqNDMGkXbZPaVps+LJdLJbVL9snATdTd7"
    "hPYNNtOsfzPlr7WEgKKL5OZSmM03a4FJ8w1ugb5mHpZrbl0qW94aLi7m15ZE1+E2+shaKcw+mtxd"
    "vxXwAO+gsBPJ/nVzM6VvsfGZqm62bwamHT/mhMMAdBT4IbOfrp1T/HNO8xHso85yNAv20BeSV9hk"
    "hAbZMe+mbNB3+YtsUpplnhWpDI5fCWyZxk3hTTJgUu8hXTWQXnRcBGli9g/0++7f8s/jEl149xP+"
    "4yEjQu7c9XSM58XKz39KWy5aCcmv9GMZJ5Ci+fo8fRttzp1PurLxeMG3UKOP6fdHyfB7msd36Qeu"
    "IWGJ36nACrrXbb4/bQUdzLgOe0nGL9q/qAnMhcZpI4ffIL2NvLGnbfbzMlycvYDTb3DeNOuD/f3L"
    "y8vJ5b1JWZ3t3719+/Y+3R8ET/cacV8cDbkwGKgv9CRNP6ItGbT/D8u3mBa3k9u8gL63u+g3PS/R"
    "BK5rg6RZL8qmr/TWUb79SKATwKBdpCvJz8qr3HgsSisVxlYtiIZ3aeutQx2rAEYZqvObdJpDCeGN"
    "qNZv7wx0Iu8lf0fzvusRUCN9L2OM2fV3fWVdoaxvZHJ13r/r7neXgKDV19zRfzP7/SzLPhl0lyTP"
    "7fFuiafvuEGxe0ydB9kOVjfqq3W5uHL9xXiq8MuSwAl9pmM2XBsXzdthITkrMHJXQ7NMdfDM2HWU"
    "yQassQai9T3kdc3t+ad/m356zZOuc+5e9yTuoJIa62yYDHa/QGev6Hmv9/GAUOb5vKbrLmfW7CbD"
    "MiuqmYNozeJVjFWP3ocXPb4H07YbjPYDjFz8pK9oMzSuz1uPeAMz5//6H2qNSdBpMw+6WihMmYSt"
    "/IyEd+Qia27SiUya4c4C8Sp3fRjfCroQn7/dWwq+sScZlAX0nmUBtC5yEhQWja0KvvnIgYo+gWFb"
    "95nrrMbHbclC93VJerKTl3ENIOhsp365Nvqlzk+jW64bUSdnqk7i73BUrlEaZ/1Ko9kuGDLKOmLm"
    "e/mNRjjz1ccMuBKrQEo13WvmDU+HnAw6/Ia6Lc1KWqGSuKNOVhYTZdK9irnh6sPKwaRcGWjBq80i"
    "r/emnB5XCK4K5IbgZDz3FfSVbcTBaFmpzsvydXLJGU+RgZG+hqKePXvuSIwkOgPBu1M8rGaPajOt"
    "ipmHlXr08vDRNz8+e/LHJ88s0IgZ7em/n0TbBU+toUTQ/xiXC4zmv/z3QfIOSqRlv3cvfZ03Sq8o"
    "WFbz0gf6imK//VdED0VWIvmW/c5f/5VfemeQUYxIewq1sIZYrJVqff+H+uN9G1T9sCTdI12NLPxZ"
    "mQ7TWviTzdv7Jz9kv/2NQfLUQYJ3Hl5gOgrO5psuNhwl5uW3Tneo8UXmax0xOwaXrfpF+bYN9cbF"
    "bmVKyHM0QD2dFCvqy+Yw+0uKZHjWg5/Okd+GGVOoKBtTjhNO5QXyb1YWjhtgdiSPJxUv9lKqxHLo"
    "xwjgARww2nUPzgCmPBplJO0F/zzy5K2Z/S55x3YY6dYhl6jHY79QRWua6z1Wmt1Uvfpxf76f8LWQ"
    "1vU9wg9cmGM7xtGXqAGYBMK9qw4Ci7Z2pIBrpM15NWOOG+pHF5HPf1mC/Lue8oQtgTt75PWti5tA"
    "VUfqcebZ1LZKCBTEIpZpG8jTCtnTy00z5OmEvQ//MgNiY27R1BonnyJ5lu40naWrzWNn4VTSUEvh"
    "zH66KAeb2Z7m0UGH8Iz90l+c1Cmah1km7f6ff6g/Gl7mJCdGD4aX6arZihgFzHeLSPotlbcu63wL"
    "pMLoAR5vSnl8Q1enG5p02wJQAyyybYbDz9VWNIctNW5Ezw7T1QN5JS22i8Vye5avfqgf0B+z87SZ"
    "lg3/S1f4Z7ku6Py0xW9Gsm7TTVMuOTnuyKTF5ZUx0kyqNNCc4HHwDHBjK/GnBpOlPTK2mcKafHa+"
    "KhflmaBZOBqc8yjSOsyq9AzpPyrqsrqB8F3lVxLd9cCZ6VXeSj2Sz+l83qrMoYMz61ZlUiDBwJ4G"
    "dy/PwdCaUCORjgrAgHzF6QxQvTPsn8g3PPHcBPs/TIer8nLLFdvyJjlEZout+mC3bK8Ybd+c3Nn7"
    "5PSHKQ1MmkGZ3lb5GbDE1KtZ0WzztykNR0UlVQWMPNtihbGrt1m5mS62ahjaXsBzkm/rNaYFh0tt"
    "wbA6BN56S0edYna11Y15S7M5K6vRljMSpXSBZFJ+mdI4QoxwjmNIQyBdrhnPQ1YauO9+/uu/oJOo"
    "yT//9X+ZFOecGkAcRFLBMQ/amPMFS3PHTJ3MLS4rbwA/sLuejuHvfpeEg/rlF12j+nJlGQH8z56X"
    "m0pmTVYuFmklxvrzfEHrTXkLOeEuTwMQiQ/CpDMs9Q4CEWajC03ytPjmnTghkw0es5U228oBAtRp"
    "dkRTUIPlQdGLANvycpIcK8kiqZCcglNXU1FPONcn08bE4gb5qm8mbj7YH8qEVeLcxRVNO7hQMJVp"
    "REnPw7LYLtPVhibM9IqUk1VG045x9+d5ThN2mRaLLTu4higJmHoz2YWJNbpM/+cuGm0zelPu0D98"
    "b3F1zQx8LMj63KYV0OZ6ZK3MH1q6lDmSjuu8vKRTAi3wYNEOecpup8hZsL2EC1PF7Ra0FNTGrezl"
    "RuRtObnRNl8Uy2LFfy7Li+28yvNhvUWbHiSb9bY+L+bNlg6GebqkOX9Nk47B3FanV7KGLCmtLKZa"
    "mwReaKrQWpintTZgyJjTuQH8IzTThU8pm/QvqvaCzjDtZNEISIN5gEEPKgldeB3x30yxi0cs0yxI"
    "jTAvp7KWsv/4NfQ1KESnOR1LcjqaZnusUE6Sx5aHFNUj5a3gSFI3VSwfbv8yshRkN1tFv91SH0G5"
    "3aLHtpjxNENIQ9vWNLdoyfD8hzDc/vCbrcik7Wpdb2c1phH2ZhXpHDSwzauqpGLyec7yGtN4yybs"
    "LTSOLed73lJrtzhebTE2dGP2Osd2TXs/0pNswY1ENbhm+jF7EUepcItxotusEIjDAjMY/nHyWxpd"
    "k5z0N3ydl+37TDmEEbjlq8nLZE5VINpP2SrIVj2Sg4rHS0ihqWhImQJRSWP+46fbYSKU/9pTIoq1"
    "IbbS6DbaxGckS2VFO1ZcSf1OraK/ivmVN/U6T+40rZfUv7PXNMXP04uClngI7HVZCF+UoRG0xaVI"
    "z+wZI2R/uMyHrEifoJVf8DvMIXT64cha+mZTuxamN00OxMQKU6GQN3Wl3Z0KmAH6T1rsrYiz8BdU"
    "rBTlHN8qJVmTfmqUlOY79qRmAwfZryv1s5Wxb7ZeMwhtjFhvVxcYtsGoo3PqzXTJ9M+56RtkIuWg"
    "q8f5PN0sGp+2TXHrvd8hGSVJQ4LjLxPCfLdi8o3MRiN67hgwxzxFkwaHT4XbV8xzHdGMd0aTdQoe"
    "maoZ3oPzZRAlzDT8eu89bgfasx+OTtnSrmR+AmANMi5fiMPeTN2d5HDTvdcQgVU7y9JzLCLu/hru"
    "mcH9a8oRrs9WMY/SdQNwsOBB0CjPmHguu8KuYvkZ7UT8bBkK4jBr5nRifYQ1lFy+yyM4agdlM9Kb"
    "bh6YuMbDp8lTESW/c3ti6Gi6hmeQKu0CqfqJBv0QbU65cc/LYSb85JyyJDQXBjVpRfv3JhUghQkR"
    "mHY0tW9qE8HJmTpMvCx1wXe0CBDZQf9bpxL3I6D/tGIQGh57+tjrWrZy0Cq+BEOweOdh8oQajmA1"
    "ZSEzltT78lW5YzLzrGkXoaPV1diw4Cd8ugNCsVhMtOG9LeS15dPlPMDeY7Ow4jiqC4h3zkLy1OS8"
    "tXA4037y/NVzVYyoBjQT1rx9ThIqJl0XGUahKRkQM+P5Jfg91pAk4XRqEthCjuSri6IqObjK5QZ7"
    "Uboq2QqJEonMENjKF1S7eplKKgje20khy0QbM8kSoMAmixRpUExGAVbO9OBDTXqcgyuuurq23wZC"
    "cu/ix0gG19wO6HCcH4+Uo5RqLYcsbM8fevmkddwSnPqXayQdhe0RSptkkmc+ZeHU10mAcvU4KYHd"
    "nguYVE/mzRrr4U6y1I9aC0ZpEHatwXkJ/3X32jMW9AlQR89JG+Eoe9Eq9jkOPF2li6saa0bSjfD8"
    "gQa6hk2fznSZ7D7JdIPM7qDtq2UKUHdwivU1cLW3NCFth4GMJxo/HGz9O+JyhZSynpi6DdxOrshE"
    "MFCqvTbsn3ZhCNV0BCW2oIqTz0ZWWtM3EguFrvp8X4LNv6RfGBf8e94sF1/e+v/Rmj4S"
)

DATA_B64 = (
    "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"
)


if __name__ == "__main__":
    raise SystemExit(main())
