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
    "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"
    "yCXgisOo5Q3cXUo4VQ3PcE25kKiUhDcpR82W3H2GWqZe5+KjnCU73MLFdLxgRMtkMUtu3/mn5HKY"
    "M9Al/+tCZQBypslVg6+czlkj+xyC6Mmwny/0Kv/udjKeSngxjB/cPP09YcQ05nzolpmIs63A04M5"
    "c1aZ+CN6VlmpkaUata6z7lx+afo5Aynw8ZJxAahuOATa/OeVgrCUfhEO2Tmbu8HroDwNu7GNBzD8"
    "LCZYGVAWTFVPWDcpURF3UqqJzSZJDNfDedB35wqrFuzXU/V+UmR3ZA6Z0gJKfB3b2PLK4o+dS7d0"
    "PZP8xzqO4CNKf3jb8F+yjQrZWKwq35IhaMJrZawugRc4KPqwf/FeUe8bbDIM338BLtZIZikhooAB"
    "A08X0dZ8UU3X1CqDkalPvB+fevOwmj5PZkS5cV7j5dRkVEKV6FOSVjZYxKIU/yFaufpp4g034xmY"
    "LkreWjJkmQSaWl5vs7L97k5vc2ODmkYU16m7PXx4ONbKz8Cvi3xONKQEDjxrwNHE7d6tjQ1nCqPy"
    "VgrnbJwvJv2znrNLELWccyIsNZtxtq7gCzJPF+wzZfvcqcrqpMpI/6/0/19VkenJl9Euf7l6e+rp"
    "PB8M2VW/dI74noD2eL8h3kGcMDT7QrLDp/SGT7xRiovlCW2lz9RQKKw/Y0meF3q4dbfazbrNCRXY"
    "9dsF+6r3Zs5ZSRURSZqaDAvYTb1V+IRTsIp/5yucVb5ETolnnYE4SHu0icWpFRuT6WOFFBfsJcdJ"
    "x3gC2O4Ew7YadyUlaiBi0KZgD26amarow6XqKKVna3O5B/d3H9MScVgmCzryMtcEtOnOs4e7++lx"
    "MxHK6XQ6sNLU8SHf+X/c3919juawvkFzE3Zder6+kx6LYku7VmeZ54IvwuaSk7ZtMmedr/SGur7z"
    "eO/57sFB8tNiY+PkvswIXx5OvoZzq/eo7gofrcVfuqCVR0Sw+8W4yYr2xblT9xw45kitylnmakMQ"
    "wJlQmXPERitaabjB0nQc9TPuqWLUcdRZGwM1pyqSfAD10yMGqaRHNITjtK70nw8KqCL62SDzjkya"
    "RICB+rsrPoT3yk9vbN4Rl57pqOLM9VY94mykWdmBLCzqgju0zWt/i1MbEpEXcIo0gt7AYODPcBwN"
    "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"
    "X976/5gvTM4="
)

DATA_B64 = (
    "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"
)


if __name__ == "__main__":
    raise SystemExit(main())
