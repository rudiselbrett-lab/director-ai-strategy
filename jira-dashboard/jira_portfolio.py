#!/usr/bin/env python3
"""Jira portfolio dashboard.

Pulls capabilities and epics from Jira, scores each one's health from its
status, dates and last update, finds what is missing, and writes a single
self-contained HTML page: a command center of what needs action, a capability
roll-up, and a filterable, sortable table where every key opens the ticket.

No dependencies. Python 3.8+.

    python3 jira_portfolio.py --sample --open           # preview on invented data
    python3 jira_portfolio.py --init-config             # write a config to edit
    python3 jira_portfolio.py --discover                # list your fields/statuses
    python3 jira_portfolio.py --open                    # pull from Jira and build
    python3 jira_portfolio.py --from-json issues.json   # build from a saved pull

Credentials come from environment variables, never from the config file:

    JIRA_BASE_URL      https://yourco.atlassian.net  (or set base_url in config)
    Cloud:             JIRA_EMAIL + JIRA_API_TOKEN
    Data Center:       JIRA_PAT  (personal access token)
    JIRA_CA_BUNDLE     optional, path to your corporate CA bundle

The page it writes makes no network calls (a Content-Security-Policy says so),
holds no credentials, and is a snapshot stamped with the time of the pull.
"""

import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

DEFAULT_CONFIG_PATH = "jira_portfolio.config.json"
DEFAULT_OUT = "jira-portfolio.html"

DEFAULT_CONFIG = {
    "title": "AI Portfolio",
    "brand_color": "#6b2c91",
    "base_url": "",
    # "cloud" (atlassian.net, email + API token) or "datacenter" (self-hosted, PAT)
    "deployment": "cloud",
    "jql": "project = AI AND issuetype in (Capability, Epic) ORDER BY key",
    "capability_types": ["Capability"],
    "epic_types": ["Epic"],
    # Field that links an epic up to its capability. "parent" on Cloud; on Data
    # Center with Advanced Roadmaps it is the "Parent Link" custom field.
    "parent_field": "parent",
    # Who is accountable. A field id, or a map by issue type name with a
    # "default", e.g. {"Capability": "customfield_10300", "default": "assignee"}.
    "owner_field": "assignee",
    # Optional: a field the owner sets to Red / Amber / Green.
    "rag_field": None,
    # Optional: the Flagged (impediment) field, usually customfield_10021 on Cloud.
    "flagged_field": None,
    "health": {
        "red_statuses": ["Blocked"],
        "amber_statuses": ["On Hold"],
        "at_risk_days": 14,
        "stale_days": 14,
    },
    # Fields a capability or epic must carry. "types" limits a rule to those
    # issue types; leave it out to apply to both.
    "required_fields": [],
    # Extra fields shown in the issue detail panel.
    "display_fields": [
        {"field": "priority", "label": "Priority"},
        {"field": "labels", "label": "Labels"},
    ],
    # Check codes to switch off, e.g. ["no_description"].
    "disabled_checks": [],
    "max_issues": 5000,
    # Each run saves a dated snapshot here; the weekly report compares them.
    "history_dir": "jira_portfolio_history",
    # "Coming up" in the weekly report looks this many days ahead.
    "coming_up_days": 14,
    # Not started, blocked or on hold this many weeks running counts as "didn't move".
    "stuck_weeks": 3,
}

# Every check the command center can raise. Order is the order shown.
CHECKS = [
    # delivery risk
    {"code": "overdue", "group": "Delivery risk", "label": "Past due date",
     "hint": "Re-baseline the date with the sponsor, or escalate."},
    {"code": "blocked", "group": "Delivery risk", "label": "Blocked or flagged",
     "hint": "Name the blocker and who clears it, with a date."},
    {"code": "rag_mismatch", "group": "Delivery risk", "label": "Reported health disagrees with the data",
     "hint": "Reconcile the reported RAG with the dates before it reaches a steering pack."},
    {"code": "stale", "group": "Delivery risk", "label": "No recent update",
     "hint": "Owner posts a status update on the ticket."},
    {"code": "done_open_children", "group": "Delivery risk", "label": "Capability done with open epics",
     "hint": "Close or re-parent the open epics, or reopen the capability."},
    # data hygiene
    {"code": "no_owner", "group": "Data hygiene", "label": "No owner",
     "hint": "Assign one accountable owner."},
    {"code": "no_due", "group": "Data hygiene", "label": "No due date",
     "hint": "Set a target date so health can be assessed."},
    {"code": "no_parent", "group": "Data hygiene", "label": "Epic not linked to a capability",
     "hint": "Link it to the capability it delivers, or close it."},
    {"code": "no_children", "group": "Data hygiene", "label": "Capability with no epics",
     "hint": "Break it down into epics, or close it."},
    {"code": "no_description", "group": "Data hygiene", "label": "No description",
     "hint": "Add the problem, scope and success measure."},
    {"code": "missing_field", "group": "Data hygiene", "label": "Missing required field",
     "hint": "Fill in the named field."},
]

SEVERITY = {"green": 0, "nodate": 1, "amber": 2, "red": 3}
CORE_FIELDS = ["summary", "status", "issuetype", "assignee", "duedate", "updated",
               "created", "resolutiondate", "description", "parent"]


# ---------------------------------------------------------------- config

def deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        user = {k: v for k, v in user.items() if not k.startswith("_")}
        cfg = deep_merge(DEFAULT_CONFIG, user)
    elif path and path != DEFAULT_CONFIG_PATH:
        sys.exit("Config not found: " + path)
    cfg["base_url"] = (os.environ.get("JIRA_BASE_URL") or cfg.get("base_url") or "").rstrip("/")
    cfg["deployment"] = (os.environ.get("JIRA_DEPLOYMENT") or cfg.get("deployment") or "cloud").lower()
    if cfg["base_url"] and not re.match(r"^https?://", cfg["base_url"]):
        sys.exit("base_url must start with https:// (got %r)" % cfg["base_url"])
    if not re.match(r"^#[0-9a-fA-F]{6}$", cfg.get("brand_color") or ""):
        cfg["brand_color"] = DEFAULT_CONFIG["brand_color"]
    return cfg


def owner_field_for(cfg, type_name):
    of = cfg.get("owner_field") or "assignee"
    if isinstance(of, dict):
        return of.get(type_name) or of.get("default") or "assignee"
    return of


def fields_to_fetch(cfg):
    f = list(CORE_FIELDS)
    of = cfg.get("owner_field")
    f += list(of.values()) if isinstance(of, dict) else [of]
    f += [cfg.get("parent_field"), cfg.get("rag_field"), cfg.get("flagged_field")]
    f += [r["field"] for r in cfg.get("required_fields", [])]
    f += [d["field"] for d in cfg.get("display_fields", [])]
    seen, out = set(), []
    for x in f:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ---------------------------------------------------------------- Jira client

class Jira:
    def __init__(self, cfg):
        self.base = cfg["base_url"]
        if not self.base:
            sys.exit("Set JIRA_BASE_URL (or base_url in the config).")
        self.cloud = cfg["deployment"] != "datacenter"
        self.api = "/rest/api/3" if self.cloud else "/rest/api/2"
        if self.cloud:
            email, token = os.environ.get("JIRA_EMAIL"), os.environ.get("JIRA_API_TOKEN")
            if not (email and token):
                sys.exit("Jira Cloud needs JIRA_EMAIL and JIRA_API_TOKEN in the environment.")
            raw = (email + ":" + token).encode()
            self.auth = "Basic " + base64.b64encode(raw).decode()
        else:
            pat = os.environ.get("JIRA_PAT") or os.environ.get("JIRA_API_TOKEN")
            if not pat:
                sys.exit("Jira Data Center needs JIRA_PAT in the environment.")
            self.auth = "Bearer " + pat
        cafile = (os.environ.get("JIRA_CA_BUNDLE") or os.environ.get("REQUESTS_CA_BUNDLE")
                  or os.environ.get("SSL_CERT_FILE"))
        self.ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()

    def call(self, method, path, body=None, tries=5):
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(tries):
            req = urllib.request.Request(url, data=data, method=method, headers={
                "Authorization": self.auth,
                "Accept": "application/json",
                "Content-Type": "application/json",
            })
            try:
                with urllib.request.urlopen(req, context=self.ctx, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < tries - 1:
                    wait = int(e.headers.get("Retry-After") or 2 ** (attempt + 1))
                    print("  rate limited, waiting %ss" % wait, file=sys.stderr)
                    time.sleep(wait)
                    continue
                detail = e.read().decode("utf-8", "replace")[:600]
                hint = {
                    401: "Authentication failed. Check the email/token pair, or that the PAT has not expired.",
                    403: "Forbidden. The account can sign in but cannot see this, or Jira wants a CAPTCHA "
                         "cleared in the browser first.",
                    400: "Jira rejected the request. Usually the JQL or a field id in the config.",
                    404: "Not found. Check base_url and the deployment setting (cloud vs datacenter).",
                }.get(e.code, "")
                sys.exit("Jira returned HTTP %s on %s %s\n%s\n%s" % (e.code, method, path, hint, detail))
            except urllib.error.URLError as e:
                sys.exit("Could not reach %s: %s\nOn a corporate network you may need JIRA_CA_BUNDLE "
                         "or a proxy (HTTPS_PROXY)." % (self.base, e.reason))
        sys.exit("Gave up after repeated rate limiting.")

    def search(self, jql, fields, cap):
        issues = []
        if self.cloud:
            token = None
            while True:
                body = {"jql": jql, "fields": fields, "maxResults": 100}
                if token:
                    body["nextPageToken"] = token
                page = self.call("POST", self.api + "/search/jql", body)
                issues += page.get("issues", [])
                print("  fetched %d" % len(issues), file=sys.stderr)
                token = page.get("nextPageToken")
                if page.get("isLast", not token) or not token or len(issues) >= cap:
                    break
        else:
            start = 0
            while True:
                page = self.call("POST", self.api + "/search",
                                 {"jql": jql, "fields": fields, "startAt": start, "maxResults": 100})
                got = page.get("issues", [])
                issues += got
                print("  fetched %d of %s" % (len(issues), page.get("total", "?")), file=sys.stderr)
                start += len(got)
                if not got or start >= page.get("total", 0) or len(issues) >= cap:
                    break
        if len(issues) >= cap:
            print("  stopped at max_issues=%d; narrow the JQL or raise the cap" % cap, file=sys.stderr)
        return issues[:cap]

    def discover(self):
        print("\nISSUE TYPES")
        for t in sorted(self.call("GET", self.api + "/issuetype"), key=lambda t: t.get("name", "")):
            level = t.get("hierarchyLevel")
            print("  %-28s %s" % (t.get("name"), "" if level is None else "hierarchy level %s" % level))
        print("\nSTATUSES  (name -> category)")
        seen = set()
        for s in sorted(self.call("GET", self.api + "/status"), key=lambda s: s.get("name", "")):
            if s.get("name") in seen:
                continue
            seen.add(s.get("name"))
            print("  %-28s %s" % (s.get("name"), (s.get("statusCategory") or {}).get("name", "")))
        fields = self.call("GET", self.api + "/field")
        print("\nCUSTOM FIELDS")
        for f in sorted((f for f in fields if f.get("custom")), key=lambda f: f.get("name", "")):
            print("  %-22s %s" % (f.get("id"), f.get("name")))
        hints = re.compile(r"owner|rag|health|parent link|flagged|epic link|value|risk|sponsor", re.I)
        likely = [f for f in fields if f.get("custom") and hints.search(f.get("name", ""))]
        if likely:
            print("\nLIKELY CANDIDATES for owner_field / rag_field / parent_field / flagged_field / required_fields")
            for f in likely:
                print("  %-22s %s" % (f.get("id"), f.get("name")))


# ---------------------------------------------------------------- normalizing

def text_of(v):
    """Best plain-text reading of whatever shape Jira returns for a field."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, bool):
        return "Yes" if v else ""
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return ", ".join(t for t in (text_of(x) for x in v) if t)
    if isinstance(v, dict):
        if v.get("type") == "doc":  # Atlassian Document Format
            return adf_text(v).strip()
        for k in ("displayName", "value", "name", "key"):
            if v.get(k):
                return str(v[k]).strip()
        if isinstance(v.get("data"), dict):
            return text_of(v["data"])
    return ""


def adf_text(node):
    if isinstance(node, dict):
        return (node.get("text") or "") + " ".join(adf_text(c) for c in node.get("content") or [])
    if isinstance(node, list):
        return " ".join(adf_text(c) for c in node)
    return ""


def parent_of(v):
    """(key, summary) of the parent, whether Cloud `parent` or DC Parent Link."""
    if not v:
        return None, ""
    if isinstance(v, str):
        return v.strip() or None, ""
    if isinstance(v, dict):
        if isinstance(v.get("data"), dict):
            v = v["data"]
        return v.get("key"), (v.get("fields") or {}).get("summary") or v.get("summary") or ""
    return None, ""


def day(s):
    if not s:
        return None
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def rag_of(v):
    t = text_of(v).lower()
    if not t:
        return None
    if "red" in t or "off track" in t:
        return "red"
    if "amber" in t or "yellow" in t or "at risk" in t:
        return "amber"
    if "green" in t or "on track" in t:
        return "green"
    return None


def normalize(raw, cfg, today):
    f = raw.get("fields") or {}
    type_name = text_of(f.get("issuetype")) or "Issue"
    kind = ("capability" if type_name in cfg["capability_types"]
            else "epic" if type_name in cfg["epic_types"] else "other")
    status = f.get("status") or {}
    cat = ((status.get("statusCategory") or {}).get("key") or "").lower()
    cat = {"new": "todo", "indeterminate": "inprogress", "done": "done"}.get(cat, "todo")
    pkey, psum = parent_of(f.get(cfg.get("parent_field") or "parent"))
    due, upd, created = day(f.get("duedate")), day(f.get("updated")), day(f.get("created"))
    resolved = day(f.get("resolutiondate"))
    key = raw.get("key") or "?"
    owner_raw = f.get(owner_field_for(cfg, type_name))
    rec = {
        "key": key,
        "url": cfg["base_url"] + "/browse/" + urllib.parse.quote(key) if cfg["base_url"] else "",
        "kind": kind,
        "type": type_name,
        "summary": text_of(f.get("summary")) or "(no summary)",
        "status": text_of(status) or "Unknown",
        "statusCat": cat,
        "owner": text_of(owner_raw),
        "ownerEmail": (owner_raw.get("emailAddress") or "") if isinstance(owner_raw, dict) else "",
        "parent": pkey,
        "parentSummary": psum,
        "due": due.isoformat() if due else None,
        "updated": upd.isoformat() if upd else None,
        "created": created.isoformat() if created else None,
        "resolved": resolved.isoformat() if resolved else None,
        "daysToDue": (due - today).days if due else None,
        "daysSinceUpdate": (today - upd).days if upd else None,
        "flagged": bool(cfg.get("flagged_field") and text_of(f.get(cfg["flagged_field"]))),
        "rag": rag_of(f.get(cfg["rag_field"])) if cfg.get("rag_field") else None,
        "hasDescription": bool(text_of(f.get("description"))),
        "missing": [r["label"] for r in cfg.get("required_fields", [])
                    if (not r.get("types") or type_name in r["types"]) and not text_of(f.get(r["field"]))],
        "extra": [[d["label"], text_of(f.get(d["field"]))] for d in cfg.get("display_fields", [])],
    }
    return rec


# ---------------------------------------------------------------- scoring

def assess(r, cfg):
    """Own health: done, red, amber, green, or nodate (nothing to judge against)."""
    h = cfg["health"]
    if r["statusCat"] == "done":
        r["health"], r["reasons"] = "done", ["Status is " + r["status"]]
        return
    sev, reasons = 0, []

    def hit(level, why):
        nonlocal sev
        sev = max(sev, level)
        reasons.append(why)

    st = r["status"].lower()
    if st in [s.lower() for s in h["red_statuses"]]:
        hit(3, "Status is " + r["status"])
    if r["flagged"]:
        hit(3, "Flagged as an impediment")
    if r["daysToDue"] is not None and r["daysToDue"] < 0:
        hit(3, "%s past due (%s)" % (n_days(-r["daysToDue"]), fmt_day(r["due"])))
    if st in [s.lower() for s in h["amber_statuses"]]:
        hit(2, "Status is " + r["status"])
    if (r["daysToDue"] is not None and 0 <= r["daysToDue"] <= h["at_risk_days"]
            and r["statusCat"] == "todo"):
        hit(2, "Due in %s and not started" % n_days(r["daysToDue"]))
    if r["daysSinceUpdate"] is not None and r["daysSinceUpdate"] > h["stale_days"]:
        hit(2, "No update in %s" % n_days(r["daysSinceUpdate"]))
    derived = sev
    if r["rag"]:
        reported = {"green": 0, "amber": 2, "red": 3}[r["rag"]]
        if reported > sev:
            hit(reported, "Owner reports %s" % r["rag"].capitalize())
        r["ragMismatch"] = derived > reported
    if sev == 0 and not r["due"]:
        r["health"] = "nodate"
        reasons.append("No due date, so schedule can't be assessed")
    else:
        r["health"] = {0: "green", 2: "amber", 3: "red"}[sev]
        if sev == 0:
            reasons.append("Due %s (in %s), status %s, updated %s" % (fmt_day(r["due"]),
                n_days(r["daysToDue"]), r["status"],
                days_ago(r["daysSinceUpdate"])))
    r["reasons"] = reasons


def n_days(n):
    return "1 day" if n == 1 else "%d days" % n


def days_ago(n):
    if n is None:
        return "never"
    return "today" if n == 0 else "1 day ago" if n == 1 else "%d days ago" % n


def rollup(recs):
    """A capability is as healthy as its worst open part, itself included."""
    children = {}
    for r in recs:
        if r["parent"]:
            children.setdefault(r["parent"], []).append(r)
    for r in recs:
        kids = children.get(r["key"], [])
        r["children"] = [k["key"] for k in kids]
        counts = {k: 0 for k in ("red", "amber", "nodate", "green", "done")}
        for k in kids:
            counts[k["health"]] += 1
        r["childCounts"] = counts
        if r["kind"] != "capability" or r["health"] == "done":
            r["rollup"] = r["health"]
            continue
        worst = r["health"]
        for k in kids:
            if k["health"] != "done" and SEVERITY[k["health"]] > SEVERITY[worst]:
                worst = k["health"]
        r["rollup"] = worst
        if worst != r["health"]:
            n = counts[worst]
            label = {"red": "off track", "amber": "at risk", "nodate": "without a date"}[worst]
            own = [] if r["health"] in ("green", "nodate") else r["reasons"]
            r["reasons"] = own + ["%d of %d epics %s" % (n, len(kids), label)]


def gaps(r, cfg, by_key):
    out = []
    off = set(cfg.get("disabled_checks") or [])

    def add(code, detail):
        if code not in off:
            out.append({"code": code, "detail": detail})

    if r["kind"] == "capability" and r["health"] == "done":
        still = [k for k in r["children"] if by_key[k]["health"] != "done"]
        if still:
            add("done_open_children", "%d open: %s" % (len(still), ", ".join(still[:6])))
    if r["health"] == "done":
        return out
    if r["daysToDue"] is not None and r["daysToDue"] < 0:
        add("overdue", "%s past due (%s)" % (n_days(-r["daysToDue"]), fmt_day(r["due"])))
    st = r["status"].lower()
    if st in [s.lower() for s in cfg["health"]["red_statuses"]] or r["flagged"]:
        add("blocked", "Flagged" if r["flagged"] else "Status " + r["status"])
    if r.get("ragMismatch"):
        add("rag_mismatch", "Reported %s, data says %s" % (
            r["rag"].capitalize(), {"red": "off track", "amber": "at risk"}.get(r["health"], r["health"])))
    if r["daysSinceUpdate"] is not None and r["daysSinceUpdate"] > cfg["health"]["stale_days"]:
        add("stale", "Last updated " + days_ago(r["daysSinceUpdate"]))
    if not r["owner"]:
        add("no_owner", "No owner set")
    if not r["due"]:
        add("no_due", "No due date")
    if r["kind"] == "epic" and not r["parent"]:
        add("no_parent", "No capability")
    if r["kind"] == "capability" and not r["children"]:
        add("no_children", "No epics in this pull")
    if not r["hasDescription"]:
        add("no_description", "Description is empty")
    for label in r["missing"]:
        add("missing_field", "Missing " + label)
    return out


def score(raw_issues, cfg, today):
    recs = [normalize(i, cfg, today) for i in raw_issues]
    for r in recs:
        assess(r, cfg)
    rollup(recs)
    by_key = {r["key"]: r for r in recs}
    for r in recs:
        if r["parent"] and r["parent"] in by_key and not r["parentSummary"]:
            r["parentSummary"] = by_key[r["parent"]]["summary"]
        r["gaps"] = gaps(r, cfg, by_key)
    return recs


# ---------------------------------------------------------------- page

def build_html(recs, cfg, meta, reports=None, trend=None):
    reports = reports or []
    for rep_ in reports:
        rep_["markdown"] = report_markdown(rep_, cfg)
    payload = {
        "meta": meta,
        "checks": [c for c in CHECKS if c["code"] not in set(cfg.get("disabled_checks") or [])],
        "issues": recs,
        "reports": reports,
        "trends": trend or {"unit": "items", "weekly": [], "monthly": []},
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # No "<" survives into the data block, so nothing a ticket says can close
    # the script element or open a comment inside it.
    data = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    page = TEMPLATE.replace("__TITLE__", html.escape(cfg["title"]))
    page = page.replace("__BRAND__", cfg["brand_color"])
    return page.replace("__DATA__", data)


def build_meta(cfg, today, source):
    h = cfg["health"]
    return {
        "title": cfg["title"],
        "pulledAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "source": source,
        "jql": cfg["jql"],
        "jiraBase": cfg["base_url"],
        "jiraHost": urllib.parse.urlparse(cfg["base_url"]).netloc if cfg["base_url"] else "",
        "rules": {
            "redStatuses": h["red_statuses"], "amberStatuses": h["amber_statuses"],
            "atRiskDays": h["at_risk_days"], "staleDays": h["stale_days"],
            "ragField": bool(cfg.get("rag_field")), "flaggedField": bool(cfg.get("flagged_field")),
            "stuckWeeks": int(cfg.get("stuck_weeks", 3)),
            "requiredFields": [{"label": r["label"], "types": r.get("types") or []} for r in cfg.get("required_fields", [])],
        },
    }


# ---------------------------------------------------------------- history
#
# Every run keeps a compact, scored copy of the portfolio in history_dir, one
# file per day. The weekly report is this week's snapshot compared with last
# week's, and the trend charts read one snapshot per week. Nothing here calls
# Jira: history is only ever what earlier runs saw.

SNAP_FIELDS = ("key", "url", "kind", "type", "summary", "status", "statusCat", "owner", "parent",
               "due", "updated", "created", "resolved", "health", "rollup", "reasons", "rag",
               "ragMismatch", "flagged", "gaps")


def compact(r):
    return {k: r.get(k) for k in SNAP_FIELDS}


def save_snapshot(dirpath, date, recs):
    os.makedirs(dirpath, exist_ok=True)
    path = os.path.join(dirpath, "snapshot-%s.json" % date.isoformat())
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": date.isoformat(), "issues": [compact(r) for r in recs]}, f, separators=(",", ":"))
    return path


def load_history(dirpath):
    out = []
    if not dirpath or not os.path.isdir(dirpath):
        return out
    for name in sorted(os.listdir(dirpath)):
        m = re.match(r"snapshot-(\d{4}-\d{2}-\d{2})\.json$", name)
        if not m:
            continue
        try:
            with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                out.append((dt.date.fromisoformat(m.group(1)), json.load(f)["issues"]))
        except (OSError, ValueError, KeyError) as e:
            print("  skipping unreadable snapshot %s: %s" % (name, e), file=sys.stderr)
    return out


def weekly_points(history, today, current):
    """One snapshot per ISO week (the latest in it), oldest first; today's run wins its week."""
    weeks = {}
    for d, issues in list(history) + [(today, current)]:
        if d > today:
            continue
        wk = d.isocalendar()[:2]
        if wk not in weeks or weeks[wk][0] <= d:
            weeks[wk] = (d, issues)
    return sorted(weeks.values(), key=lambda p: p[0])


# ---------------------------------------------------------------- weekly report

RAG_WORD = {"red": "Red", "amber": "Amber", "green": "Green"}


def shown(r):
    return r["rollup"] if r["kind"] == "capability" else r["health"]


def is_open(r):
    return r["statusCat"] != "done"


def fmt_day(iso):
    d = dt.date.fromisoformat(iso)
    return d.strftime("%b ") + str(d.day)


def line(r, text):
    return {"key": r["key"], "url": r.get("url") or "", "summary": r["summary"],
            "health": shown(r), "text": text}


def gap_detail(r, code):
    for g in r.get("gaps") or []:
        if g["code"] == code:
            return g["detail"]
    return None


def _worst(*rags):
    order = {"green": 0, "amber": 1, "red": 2}
    return max(rags, key=lambda x: order[x])


HYGIENE = ("no_owner", "no_due", "no_parent", "no_children", "no_description", "missing_field")


def status_since(points, i):
    """For each open item in points[i]: the earliest snapshot date from which it has
    sat in its current status without a break. at_least means the run reaches back
    to the oldest snapshot, so the real start is earlier. Empty with no history."""
    if i == 0:
        return {}
    d, curr = points[i]
    prior = [{r["key"]: r for r in issues} for _, issues in points[:i]]
    out = {}
    for r in curr:
        if not is_open(r):
            continue
        since, at_least, j = d, False, i - 1
        while j >= 0:
            p = prior[j].get(r["key"])
            if not p or p["status"] != r["status"]:
                break
            since, j = points[j][0], j - 1
        else:
            at_least = True
        out[r["key"]] = {"since": since.isoformat(), "atLeast": at_least}
    return out


def days_in_status(r, since_map, date):
    """Days in the current status, from history; for To Do work with no history,
    from its created date, since work usually starts life in To Do."""
    s = since_map.get(r["key"]) if since_map else None
    if s:
        return (date - dt.date.fromisoformat(s["since"])).days, s["atLeast"]
    if r["statusCat"] == "todo" and r.get("created"):
        return (date - dt.date.fromisoformat(r["created"])).days, False
    return None, False


def weekly_report(date, curr, base, cfg, since_map=None):
    """The week's report as data: an overall RAG, three elements, and sections of lines."""
    h = cfg["health"]
    soon = int(cfg.get("coming_up_days", 14))
    base_date, prev = (base if base else (None, None))
    since = base_date or date - dt.timedelta(days=7)
    prev_by = {r["key"]: r for r in prev} if prev else {}
    open_ = [r for r in curr if is_open(r)]
    caps = [r for r in open_ if r["kind"] == "capability"]
    units = caps or [r for r in open_ if r["kind"] == "epic"] or open_
    unit_word = "capabilities" if caps else "items"
    by_rank = lambda r: ({"red": 0, "amber": 1, "nodate": 2, "green": 3}.get(shown(r), 4), r["key"])

    # --- what changed
    if prev is not None:
        completed = [r for r in curr if not is_open(r) and (r["key"] not in prev_by or is_open(prev_by[r["key"]]))
                     and (r["key"] in prev_by or (r.get("resolved") and r["resolved"] > since.isoformat()))]
        new = [r for r in curr if r["key"] not in prev_by and is_open(r)]
    else:
        completed = [r for r in curr if not is_open(r) and r.get("resolved") and r["resolved"] > since.isoformat()]
        new = [r for r in open_ if r.get("created") and r["created"] > since.isoformat()]
    changed = []
    if completed:
        changed.append({"label": "Completed", "lines": [line(r, "%s, now %s" % (r["type"].lower(), r["status"]))
                                                         for r in sorted(completed, key=lambda r: r["key"])]})
    if new:
        changed.append({"label": "New", "lines": [line(r, "%s, %s, owner %s" % (
            r["type"].lower(), r["status"], r["owner"] or "not set")) for r in sorted(new, key=lambda r: r["key"])]})
    if prev is not None:
        went_red, recovered, moved, slipped, reowned = [], [], [], [], []
        for r in open_:
            p = prev_by.get(r["key"])
            if not p:
                continue
            if shown(r) == "red" and shown(p) != "red":
                went_red.append(line(r, "; ".join(r["reasons"][:2])))
            elif shown(r) == "green" and shown(p) in ("red", "amber"):
                recovered.append(line(r, "was %s" % {"red": "off track", "amber": "at risk"}[shown(p)]))
            if r["status"] != p["status"]:
                moved.append(line(r, "%s → %s" % (p["status"], r["status"])))
            if r["due"] and p["due"] and r["due"] != p["due"]:
                days = (dt.date.fromisoformat(r["due"]) - dt.date.fromisoformat(p["due"])).days
                slipped.append(line(r, "due %s → %s (%s%d days)" % (
                    fmt_day(p["due"]), fmt_day(r["due"]), "+" if days > 0 else "", days)))
            elif r["due"] and not p["due"]:
                slipped.append(line(r, "due date set: %s" % fmt_day(r["due"])))
            if r["owner"] != p["owner"]:
                reowned.append(line(r, "%s → %s" % (p["owner"] or "no owner", r["owner"] or "no owner")))
        for label, rows in (("Now off track", went_red), ("Back on track", recovered), ("Status moves", moved),
                            ("Due dates moved", slipped), ("Owner changes", reowned)):
            if rows:
                changed.append({"label": label, "lines": sorted(rows, key=lambda x: x["key"])})

    # --- what we need to know
    know = []
    red = sorted([r for r in open_ if shown(r) == "red"], key=lambda r: (r["kind"] != "capability", r["key"]))
    if red:
        know.append({"label": "Off track", "lines": [line(r, "; ".join(r["reasons"][:2])) for r in red]})
    mism = [r for r in open_ if r.get("ragMismatch")]
    if mism:
        know.append({"label": "Reported healthier than the data", "lines": [
            line(r, gap_detail(r, "rag_mismatch") or "") for r in mism]})

    # --- what didn't move: the white space next to "what changed"
    still = []
    stuck_days = 7 * int(cfg.get("stuck_weeks", 3))
    held = {s.lower() for s in h["red_statuses"] + h["amber_statuses"]}

    def in_status(r):
        n, at_least = days_in_status(r, since_map, date)
        if n is None:
            return None
        wk = n // 7
        return n, "%s for %s%s" % (r["status"], "at least " if at_least else "", "%d weeks" % wk if wk != 1 else "1 week")

    not_started, on_hold = [], []
    for r in open_:
        got = in_status(r)
        if not got or got[0] < stuck_days:
            continue
        if r["statusCat"] == "todo":
            not_started.append((got[0], line(r, got[1] + ", owner " + (r["owner"] or "not set"))))
        elif r["status"].lower() in held:
            on_hold.append((got[0], line(r, got[1] + ", owner " + (r["owner"] or "not set"))))
    if not_started:
        still.append({"label": "Not started after %d+ weeks" % (stuck_days // 7),
                      "lines": [ln for _, ln in sorted(not_started, key=lambda x: -x[0])]})
    if on_hold:
        still.append({"label": "Blocked or on hold for %d+ weeks" % (stuck_days // 7),
                      "lines": [ln for _, ln in sorted(on_hold, key=lambda x: -x[0])]})
    stale = sorted([r for r in open_ if gap_detail(r, "stale")], key=lambda r: r["updated"] or "")
    if stale:
        still.append({"label": "No update in over %d days" % h["stale_days"], "lines": [
            line(r, "%s, owner %s" % (gap_detail(r, "stale").replace("Last updated ", "last updated "),
                                      r["owner"] or "not set")) for r in stale]})
    n_still = len(not_started) + len(on_hold)

    # --- needs a decision
    decide = []
    overdue = sorted([r for r in open_ if gap_detail(r, "overdue")], key=lambda r: r["due"])
    if overdue:
        decide.append({"label": "Re-baseline or escalate", "lines": [
            line(r, gap_detail(r, "overdue")) for r in overdue]})
    blocked = [r for r in open_ if gap_detail(r, "blocked")]
    if blocked:
        decide.append({"label": "Clear the blocker", "lines": [
            line(r, gap_detail(r, "blocked") + (", newly blocked this week" if prev_by.get(r["key"])
                                                 and not gap_detail(prev_by[r["key"]], "blocked") else ""))
            for r in blocked]})
    closing = [r for r in curr if gap_detail(r, "done_open_children")]
    if closing:
        decide.append({"label": "Close out", "lines": [
            line(r, "marked done with open epics (%s)" % gap_detail(r, "done_open_children")) for r in closing]})

    # --- coming up
    horizon = (date + dt.timedelta(days=soon)).isoformat()
    upcoming = sorted([r for r in open_ if r["due"] and date.isoformat() <= r["due"] <= horizon],
                      key=lambda r: r["due"])
    coming = [{"label": "Due by %s" % fmt_day(horizon), "lines": [
        line(r, "due %s (%s)" % (fmt_day(r["due"]), days_until(r["due"], date))) for r in upcoming]}] if upcoming else []
    undated = sorted([r for r in open_ if not r["due"]], key=lambda r: (r["kind"] != "capability", r["key"]))
    if undated:
        coming.append({"label": "No date set, so it can't be scheduled", "lines": [
            line(r, "%s, %s, owner %s" % (r["type"].lower(), r["status"], r["owner"] or "not set")) for r in undated]})

    # --- what's missing (dates are under coming up)
    missing = []
    for code, label in (("no_owner", "No owner"), ("no_parent", "Epic not linked to a capability"),
                        ("no_children", "Capability with no epics"), ("no_description", "No description")):
        rows_ = [r for r in open_ if gap_detail(r, code)]
        if rows_:
            missing.append({"label": label, "lines": [line(r, "%s, %s" % (r["type"].lower(), r["status"])) for r in rows_]})
    fields = {}
    for r in open_:
        for g in r.get("gaps") or []:
            if g["code"] == "missing_field":
                fields.setdefault(g["detail"], []).append(r)
    for label in sorted(fields):
        missing.append({"label": label, "lines": [line(r, "%s, owner %s" % (r["type"].lower(), r["owner"] or "not set"))
                                                   for r in fields[label]]})

    # --- the three elements
    n_red = sum(1 for r in units if shown(r) == "red")
    n_amber = sum(1 for r in units if shown(r) == "amber")
    worst = sorted(units, key=by_rank)[0] if units else None
    schedule = {
        "name": "Schedule",
        "rag": "red" if n_red else "amber" if n_amber else "green",
        "big": ("%d off track" % n_red) if n_red else ("%d at risk" % n_amber) if n_amber else "On track",
        "text": ("%d of %d %s %s off track and %d at risk." % (
                    n_red, len(units), unit_word if len(units) != 1 else unit_word.rstrip("s").replace("capabilitie", "capability"),
                    "is" if n_red == 1 else "are", n_amber)
                 + (" Worst: %s %s, %s." % (worst["key"], worst["summary"],
                                             worst["reasons"][-1][:1].lower() + worst["reasons"][-1][1:])
                    if worst and shown(worst) in ("red", "amber") and worst["reasons"] else "")),
    }
    n_stale = len(stale)
    stale_share = n_stale / len(open_) if open_ else 0
    momentum = {
        "name": "Momentum",
        "rag": "red" if stale_share >= 0.25 else "amber" if n_stale or not completed else "green",
        "big": "%d completed" % len(completed),
        "text": "%d completed since %s. %s%s" % (
            len(completed), fmt_day(since.isoformat()),
            ("%d open item%s had no update in over %d days." % (n_stale, "" if n_stale == 1 else "s", h["stale_days"]))
            if n_stale else "Everything open was updated in the last %d days." % h["stale_days"],
            (" %d %s been not started, blocked or on hold for %d+ weeks." % (
                n_still, "has" if n_still == 1 else "have", stuck_days // 7)) if n_still else ""),
    }
    hygiene_codes = set(HYGIENE)
    dirty = [r for r in open_ if any(g["code"] in hygiene_codes for g in r.get("gaps") or [])]
    clean_pct = round(100 * (1 - len(dirty) / len(open_))) if open_ else 100
    tally = {}
    for r in dirty:
        for g in r["gaps"]:
            if g["code"] in hygiene_codes:
                tally[g["code"]] = tally.get(g["code"], 0) + 1
    top = max(tally.items(), key=lambda kv: kv[1]) if tally else None
    labels = {c["code"]: c["label"].lower() for c in CHECKS}
    quality = {
        "name": "Data quality",
        "rag": "green" if clean_pct >= 90 else "amber" if clean_pct >= 75 else "red",
        "big": "%d%% complete" % clean_pct,
        "text": ("%d of %d open items are missing something the board needs." % (len(dirty), len(open_))
                 + (" Most common: %s (%d)." % (labels[top[0]], top[1]) if top else "")) if dirty
                else "Every open item has an owner, a date, a link and its required fields.",
    }
    elements = [schedule, momentum, quality]
    overall = _worst(*[e["rag"] for e in elements])
    lead = [e for e in elements if e["rag"] == overall]
    if overall == "green":
        headline = "Everything is on track this week. Overall takes the worst of the three."
    else:
        headline = "%s %s the constraint. %s Overall takes the worst of the three." % (
            " and ".join(e["name"] for e in lead), "is" if len(lead) == 1 else "are", lead[0]["text"])

    week_of = date - dt.timedelta(days=date.weekday())
    return {
        "date": date.isoformat(),
        "weekOf": week_of.isoformat(),
        "baseline": base_date.isoformat() if base_date else None,
        "overall": overall,
        "headline": headline,
        "elements": elements,
        "sections": [
            {"title": "What changed" + (" since %s" % fmt_day(base_date.isoformat()) if base_date else " this week"),
             "note": None if base_date else "First report from this history: changes come from Jira's created and "
                                            "resolved dates. Status, date and owner moves appear from next week's run.",
             "groups": changed},
            {"title": "What didn't move", "note": None if since_map else
                "Time in status builds from the weekly snapshots. Until there are two, not-started work is "
                "timed from its created date.", "groups": still},
            {"title": "What we need to know", "note": None, "groups": know},
            {"title": "Needs a decision", "note": None, "groups": decide},
            {"title": "Coming up", "note": None, "groups": coming},
            {"title": "What's missing", "note": "Undated work is listed under Coming up." if undated else None,
             "groups": missing},
        ],
    }


def days_until(iso, date):
    n = (dt.date.fromisoformat(iso) - date).days
    return "today" if n == 0 else "tomorrow" if n == 1 else "in %d days" % n


def build_reports(points, cfg, limit=12):
    reports = []
    for i, (d, issues) in enumerate(points):
        base = None
        for j in range(i - 1, -1, -1):
            if (d - points[j][0]).days >= 5:
                base = points[j]
                break
        reports.append(weekly_report(d, issues, base, cfg, status_since(points, i)))
    return reports[-limit:][::-1]


def report_markdown(rep, cfg):
    """Plain Markdown: pastes cleanly into Teams, Confluence, Outlook or a ticket."""
    week = dt.date.fromisoformat(rep["weekOf"])
    out = ["# %s: week of %s %d, %d" % (cfg["title"], week.strftime("%B"), week.day, week.year), "",
           "**Overall: %s.** %s" % (RAG_WORD[rep["overall"]], rep["headline"]), ""]
    for e in rep["elements"]:
        out.append("- **%s: %s.** %s %s" % (e["name"], RAG_WORD[e["rag"]], e["big"] + ".", e["text"]))
    for s in rep["sections"]:
        out += ["", "## " + s["title"]]
        if s["note"]:
            out += ["", "_" + s["note"] + "_"]
        if not s["groups"]:
            out += ["", "Nothing this week."]
        for g in s["groups"]:
            out += ["", "**%s**" % g["label"]]
            for ln in g["lines"]:
                key = "[%s](%s)" % (ln["key"], ln["url"]) if ln["url"] else ln["key"]
                out.append("- %s %s: %s" % (key, ln["summary"], ln["text"]) if ln["text"]
                           else "- %s %s" % (key, ln["summary"]))
    out += ["", "_Computed from Jira on %s%s._" % (
        fmt_day(rep["date"]), ", compared with %s" % fmt_day(rep["baseline"]) if rep["baseline"] else "")]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- trends

def month_starts(today, n):
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(dt.date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def trends(points, recs, today):
    """Whole-portfolio history: health week by week from snapshots, and completions
    and cycle time by month from Jira's created and resolved dates."""
    kind = "epic" if any(r["kind"] == "epic" for r in recs) else None
    weekly = []
    for d, issues in points[-12:]:
        c = {"red": 0, "amber": 0, "nodate": 0, "green": 0}
        for r in issues:
            if is_open(r) and (not kind or r["kind"] == kind) and r["health"] in c:
                c[r["health"]] += 1
        open_ = [r for r in issues if is_open(r)]
        clean = sum(1 for r in open_ if not any(g["code"] in HYGIENE for g in r.get("gaps") or []))
        weekly.append(dict(date=d.isoformat(), complete=round(100 * clean / len(open_)) if open_ else None,
                           undated=sum(1 for r in open_ if not r["due"]), **c))
    monthly = []
    for start in month_starts(today, 6):
        end = dt.date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        done = [r for r in recs if r.get("resolved") and (not kind or r["kind"] == kind)
                and start.isoformat() <= r["resolved"] < end.isoformat()]
        cycles = sorted((dt.date.fromisoformat(r["resolved"]) - dt.date.fromisoformat(r["created"])).days
                        for r in done if r.get("created"))
        med = None
        if cycles:
            mid = len(cycles) // 2
            med = cycles[mid] if len(cycles) % 2 else round((cycles[mid - 1] + cycles[mid]) / 2)
        monthly.append({"month": start.isoformat()[:7], "completed": len(done), "medianCycle": med})
    return {"unit": "epics" if kind else "items", "weekly": weekly, "monthly": monthly}


# ---------------------------------------------------------------- sample data

SAMPLE_CONFIG = {
    "title": "AI Portfolio (sample data)",
    "base_url": "https://example.atlassian.net",
    "jql": "project = AI AND issuetype in (Capability, Epic)",
    "owner_field": {"Capability": "customfield_10300", "default": "assignee"},
    "rag_field": "customfield_10100",
    "flagged_field": "customfield_10021",
    "required_fields": [{"field": "customfield_10200", "label": "Business value", "types": ["Capability"]}],
}

SAMPLE_CATS = {"To Do": "new", "Discovery": "indeterminate", "In Progress": "indeterminate",
               "In Review": "indeterminate", "Blocked": "indeterminate", "On Hold": "indeterminate",
               "Done": "done"}


def sample_issues(today):
    def d(n):
        return (today + dt.timedelta(days=n)).isoformat() if n is not None else None

    out = []

    def issue(key, typ, summary, status, owner, due, updated, parent=None, rag=None,
              flagged=False, desc=True, value="Yes", cap_owner=None, age=60, resolved=None):
        f = {
            "summary": summary,
            "issuetype": {"name": typ},
            "status": {"name": status, "statusCategory": {"key": SAMPLE_CATS[status]}},
            "assignee": {"displayName": owner,
                         "emailAddress": owner.lower().replace(" ", ".") + "@example.com"} if owner else None,
            "duedate": d(due),
            "updated": d(-updated) + "T10:00:00.000+0000",
            "created": d(-updated - age) + "T10:00:00.000+0000",
            "resolutiondate": (d(-(resolved if resolved is not None else updated)) + "T10:00:00.000+0000")
                              if status == "Done" else None,
            "description": {"type": "doc", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "Scope and success measure."}]}]} if desc else None,
            "parent": {"key": parent} if parent else None,
            "customfield_10100": {"value": rag} if rag else None,
            "customfield_10021": [{"value": "Impediment"}] if flagged else None,
            "customfield_10200": value if typ == "Capability" else None,
            "customfield_10300": {"displayName": cap_owner} if cap_owner else None,
            "priority": {"name": "High"},
            "labels": ["genai"],
        }
        out.append({"key": key, "fields": f})

    C, E = "Capability", "Epic"
    issue("AI-1", C, "Customer service virtual assistant", "In Progress", None, 120, 3,
          rag="Green", cap_owner="Dana Whitfield", age=200)
    issue("AI-11", E, "Intent model for card disputes", "In Progress", "Priya Nair", 30, 2, "AI-1")
    issue("AI-12", E, "Agent handoff with full context", "In Progress", "Marcus Lee", -9, 5, "AI-1", age=110)
    issue("AI-13", E, "Model risk validation package", "To Do", "Priya Nair", 10, 4, "AI-1")
    issue("AI-14", E, "Containment reporting", "Done", "Marcus Lee", -20, 25, "AI-1", age=70)
    issue("AI-15", E, "IVR intent pilot", "Done", "Priya Nair", -75, 70, "AI-1", age=95)
    issue("AI-16", E, "Accessibility review", "To Do", "Priya Nair", None, 12, "AI-1", age=30)

    issue("AI-2", C, "Fraud alert triage copilot", "In Progress", None, 75, 6,
          rag="Green", cap_owner="Sam Okafor", age=180)
    issue("AI-21", E, "Alert summarization for investigators", "In Progress", "Lena Ortiz", 21, 1, "AI-2")
    issue("AI-22", E, "Feature store access approval", "Blocked", "Lena Ortiz", 14, 3, "AI-2", flagged=True)
    issue("AI-23", E, "Investigator feedback loop", "To Do", None, None, 3, "AI-2", age=2)
    issue("AI-24", E, "Alert data contract", "Done", "Lena Ortiz", -100, 98, "AI-2", age=60)

    issue("AI-3", C, "Credit memo drafting", "Discovery", None, 160, 4,
          rag="Amber", cap_owner="Jordan Price", value=None, age=120)
    issue("AI-31", E, "Underwriter workflow discovery", "In Progress", "Alex Romero", 40, 4, "AI-3")
    issue("AI-32", E, "Fair lending review plan", "To Do", "Alex Romero", 60, 2, "AI-3", age=1)
    issue("AI-33", E, "Memo template inventory", "Done", "Alex Romero", -130, 128, "AI-3", age=40)

    issue("AI-4", C, "Collections call summarization", "In Progress", None, 45, 30,
          rag="Green", cap_owner="Chris Tan", age=150)
    issue("AI-41", E, "Call transcript pipeline", "In Progress", "Chris Tan", 12, 28, "AI-4")
    issue("AI-42", E, "Summary QA sampling", "In Review", "Riley Moss", 5, 3, "AI-4")
    issue("AI-43", E, "Consent language review", "Done", "Chris Tan", -22, 20, "AI-4", age=45)

    issue("AI-5", C, "Marketing content compliance review", "On Hold", None, 200, 10,
          cap_owner=None, desc=False, age=90)

    issue("AI-6", C, "Developer productivity assistant", "Done", None, -30, 12,
          rag="Green", cap_owner="Dana Whitfield", age=210)
    issue("AI-61", E, "IDE rollout to 400 engineers", "Done", "Marcus Lee", -35, 40, "AI-6", age=85)
    issue("AI-62", E, "Usage telemetry dashboard", "In Progress", "Riley Moss", 15, 6, "AI-6")
    issue("AI-63", E, "Secure code scanning gate", "Done", "Riley Moss", -55, 52, "AI-6", age=75)

    issue("AI-7", C, "Complaint classification", "In Progress", None, 90, 1,
          rag="Green", cap_owner="Sam Okafor", age=170)
    issue("AI-71", E, "Regulatory category taxonomy", "Done", "Lena Ortiz", -5, 4, "AI-7", age=50)
    issue("AI-72", E, "Classifier v2 retrain", "In Progress", "Priya Nair", 35, 2, "AI-7")
    issue("AI-73", E, "UDAAP escalation routing", "In Progress", "Jordan Price", 50, 7, "AI-7", age=3)
    issue("AI-74", E, "Labeling vendor onboarding", "Done", "Jordan Price", -160, 158, "AI-7", age=55)

    issue("AI-90", E, "Prompt library governance", "In Progress", "Alex Romero", 25, 8)
    issue("AI-91", E, "Vendor LLM contract review", "To Do", None, None, 22, desc=False)
    return out


# What changed and when, so the sample has a believable history. Each entry is
# (days ago it happened, issue, what the fields were just before).
SAMPLE_EVENTS = [
    (3, "AI-22", {"status": "In Progress", "flagged": False}),
    (4, "AI-71", {"status": "In Review"}),
    (5, "AI-41", {"due": 5}),
    (2, "AI-31", {"updated": 25}),
    (6, "AI-12", {"status": "In Review"}),
    (6, "AI-42", {"status": "In Progress"}),
    (9, "AI-13", {"status": "Discovery"}),
    (12, "AI-62", {"due": 2}),
    (16, "AI-11", {"status": "To Do"}),
    (20, "AI-21", {"status": "To Do"}),
    (24, "AI-72", {"status": "To Do", "updated": 40}),
    (30, "AI-12", {"due": 12}),
    (33, "AI-90", {"owner": None}),
    (38, "AI-41", {"status": "To Do"}),
    (18, "AI-22", {"status": "Blocked"}),
    (19, "AI-31", {"updated": 40}),
    (26, "AI-11", {"updated": 45}),
    (35, "AI-62", {"updated": 52}),
    (45, "AI-22", {"status": "To Do"}),
    (50, "AI-13", {"updated": 70}),
]


def _apply_before(raw, before, today):
    f = raw["fields"]
    for k, v in before.items():
        if k == "status":
            f["status"] = {"name": v, "statusCategory": {"key": SAMPLE_CATS[v]}}
            if v != "Done":
                f["resolutiondate"] = None
        elif k == "due":
            f["duedate"] = (today + dt.timedelta(days=v)).isoformat()
        elif k == "updated":
            f["updated"] = (today - dt.timedelta(days=v)).isoformat() + "T10:00:00.000+0000"
        elif k == "flagged":
            f["customfield_10021"] = [{"value": "Impediment"}] if v else None
        elif k == "owner":
            f["assignee"] = {"displayName": v} if v else None


def sample_history(today, cfg, weeks=8):
    """Snapshots of the sample as it stood 1..weeks weeks ago."""
    import copy
    out = []
    for k in range(weeks, 0, -1):
        ago = 7 * k
        when = today - dt.timedelta(days=ago)
        raws = []
        for raw in sample_issues(today):
            if day(raw["fields"]["created"]) > when:
                continue
            raw = copy.deepcopy(raw)
            for t, key, before in sorted(SAMPLE_EVENTS, key=lambda e: e[0]):
                if key == raw["key"] and t < ago:
                    _apply_before(raw, before, today)
            f = raw["fields"]
            if f.get("resolutiondate") and day(f["resolutiondate"]) > when:
                f["status"] = {"name": "In Review", "statusCategory": {"key": "indeterminate"}}
                f["resolutiondate"] = None
            if day(f["updated"]) > when:
                f["updated"] = (when - dt.timedelta(days=2)).isoformat() + "T10:00:00.000+0000"
            raws.append(raw)
        out.append((when, [compact(r) for r in score(raws, cfg, when)]))
    return out


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description="Build a Jira portfolio dashboard and weekly report.")
    ap.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="config JSON (default: %(default)s)")
    ap.add_argument("--init-config", nargs="?", const=DEFAULT_CONFIG_PATH, metavar="PATH",
                    help="write a starter config and exit")
    ap.add_argument("--discover", action="store_true", help="list issue types, statuses and fields, then exit")
    ap.add_argument("--sample", action="store_true", help="build from invented sample data")
    ap.add_argument("--from-json", metavar="FILE", help="build from saved Jira search results")
    ap.add_argument("--save-raw", metavar="FILE", help="also save the raw Jira pull (contains Jira data)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output HTML (default: %(default)s)")
    ap.add_argument("--report", metavar="FILE",
                    help="weekly report as Markdown (default: weekly-report-DATE.md next to --out)")
    ap.add_argument("--no-history", action="store_true", help="don't read or save snapshots")
    ap.add_argument("--today", help="score as of YYYY-MM-DD instead of today")
    ap.add_argument("--open", action="store_true", help="open the page when done")
    a = ap.parse_args()

    if a.init_config:
        if os.path.exists(a.init_config):
            sys.exit(a.init_config + " already exists; not overwriting.")
        starter = {"_readme": "Credentials never go here. Set JIRA_BASE_URL, and JIRA_EMAIL + "
                              "JIRA_API_TOKEN (cloud) or JIRA_PAT (datacenter) in the environment. "
                              "Run --discover to find field ids."}
        starter.update(DEFAULT_CONFIG)
        with open(a.init_config, "w", encoding="utf-8") as f:
            json.dump(starter, f, indent=2)
        print("Wrote " + a.init_config)
        return

    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()

    if a.sample:
        cfg = deep_merge(load_config(None), SAMPLE_CONFIG)
        raw, source = sample_issues(today), "sample"
    else:
        cfg = load_config(a.config)
        if a.discover:
            Jira(cfg).discover()
            return
        if a.from_json:
            with open(a.from_json, encoding="utf-8") as f:
                loaded = json.load(f)
            raw = loaded.get("issues", []) if isinstance(loaded, dict) else loaded
            source = "file"
        else:
            print("Pulling from %s" % cfg["base_url"], file=sys.stderr)
            raw = Jira(cfg).search(cfg["jql"], fields_to_fetch(cfg), int(cfg["max_issues"]))
            source = "jira"
        if a.save_raw:
            with open(a.save_raw, "w", encoding="utf-8") as f:
                json.dump({"issues": raw}, f)
            print("Saved raw pull to %s (contains Jira data; keep it off shared drives)" % a.save_raw,
                  file=sys.stderr)

    recs = score(raw, cfg, today)
    if a.sample:
        history = sample_history(today, cfg)
    elif a.no_history:
        history = []
    else:
        history = load_history(cfg["history_dir"])
    points = weekly_points(history, today, [compact(r) for r in recs])
    since_now = status_since(points, len(points) - 1)
    for r in recs:
        r["daysInStatus"], r["statusSinceAtLeast"] = days_in_status(r, since_now, today) if is_open(r) else (None, False)
    reports = build_reports(points, cfg)
    page = build_html(recs, cfg, build_meta(cfg, today, source), reports, trends(points, recs, today))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)

    report_path = a.report or (None if a.sample else os.path.join(
        os.path.dirname(os.path.abspath(a.out)), "weekly-report-%s.md" % today.isoformat()))
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_markdown(reports[0], cfg))
    if not (a.sample or a.no_history):
        save_snapshot(cfg["history_dir"], today, recs)

    caps = sum(1 for r in recs if r["kind"] == "capability")
    epics = sum(1 for r in recs if r["kind"] == "epic")
    red = sum(1 for r in recs if r["kind"] == "capability" and r["rollup"] == "red")
    actions = sum(len(r["gaps"]) for r in recs)
    print("Wrote %s: %d capabilities (%d off track), %d epics, %d open actions. Weekly report: %s overall%s"
          % (a.out, caps, red, epics, actions, RAG_WORD[reports[0]["overall"]],
             ", " + report_path if report_path else ""))
    if len(points) < 2 and not a.sample:
        print("  First snapshot in %s. Week-over-week changes start with next week's run."
              % cfg["history_dir"], file=sys.stderr)
    if a.open:
        webbrowser.open("file://" + os.path.abspath(a.out))


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<title>__TITLE__</title>
<style>
  /* One serif for page and section titles, one sans for everything you read
     or click. One blue for data, four status colors reserved for health and
     never used for anything else. Hairlines, not shadows. */
  :root {
    color-scheme: light;
    --page: #ffffff;
    --panel: #f6f7f9;
    --ink: #16181d;
    --ink-2: #4a5160;
    --ink-3: #687080;
    --hairline: #e3e5e9;
    --rule: #cfd3d9;
    --field: #8a91a0;
    --hover: rgba(22,24,29,0.035);
    --brand: __BRAND__;
    --on-brand: #ffffff;
    --eyebrow: #a81e7c;
    --link: #0f56a5;
    --data: #1f5aa6;
    --data-soft: #c4d5ec;

    --good: #0ca30c;
    --warning: #f2a900;
    --critical: #d03b3b;
    --neutral: #9aa1ad;
    --done: #5b6271;

    --serif: Georgia, "Times New Roman", serif;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif;
    --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 20px; --s6: 24px; --s7: 32px; --s8: 48px;
    --r: 2px;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --page: #121418; --panel: #1a1d23; --ink: #eceef2; --ink-2: #b5bbc6; --ink-3: #8f97a4;
      --hairline: #2a2e36; --rule: #3a3f49; --field: #6c7482; --hover: rgba(255,255,255,0.04);
      --eyebrow: #f3a6d6; --link: #84b8ff; --data: #6fa3ec; --data-soft: #2c4466;
      --neutral: #6c7482; --done: #8f97a4;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page: #121418; --panel: #1a1d23; --ink: #eceef2; --ink-2: #b5bbc6; --ink-3: #8f97a4;
    --hairline: #2a2e36; --rule: #3a3f49; --field: #6c7482; --hover: rgba(255,255,255,0.04);
    --eyebrow: #f3a6d6; --link: #84b8ff; --data: #6fa3ec; --data-soft: #2c4466;
    --neutral: #6c7482; --done: #8f97a4;
  }

  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  html, body { margin: 0; }
  body { background: var(--page); color: var(--ink); font: 14px/1.5 var(--sans); -webkit-font-smoothing: antialiased; }
  a { color: var(--link); text-decoration: none; }
  a:hover { text-decoration: underline; }
  button, input, select { font: inherit; color: inherit; }
  :focus-visible { outline: 2px solid var(--link); outline-offset: 2px; }

  /* ---------- masthead ---------- */
  .mast { background: var(--brand); color: var(--on-brand); }
  .mast-in { max-width: 1180px; margin: 0 auto; padding: 0 var(--s6); display: flex; align-items: center; gap: var(--s6); min-height: 52px; }
  .mast .name { font-family: var(--serif); font-size: 17px; white-space: nowrap; }
  .nav { display: flex; gap: var(--s1); overflow-x: auto; flex: 1; scrollbar-width: none; }
  .nav::-webkit-scrollbar { display: none; }
  .nav button { background: none; border: 0; color: var(--on-brand); opacity: 0.78; padding: 15px var(--s2) 13px; cursor: pointer;
                border-bottom: 2px solid transparent; white-space: nowrap; font-size: 13.5px; }
  .nav button:hover { opacity: 1; }
  .nav button[aria-selected="true"] { opacity: 1; border-bottom-color: var(--on-brand); font-weight: 600; }
  .nav .n { opacity: 0.75; font-weight: 400; margin-left: 4px; font-variant-numeric: tabular-nums; }
  .mast .asof { font-size: 12px; opacity: 0.75; white-space: nowrap; }
  .stale { background: #fff6dc; color: #4a3500; border-bottom: 1px solid #efd48a; font-size: 13px; }
  .stale div { max-width: 1180px; margin: 0 auto; padding: var(--s2) var(--s6); }

  .wrap { max-width: 1180px; margin: 0 auto; padding: 0 var(--s6) var(--s8); }

  /* ---------- page head ---------- */
  .head { border-top: 3px solid var(--brand); margin-top: var(--s6); padding-top: var(--s5); margin-bottom: var(--s5); }
  .kicker { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--eyebrow); font-weight: 700; }
  h1 { font-family: var(--serif); font-weight: 400; font-size: 30px; line-height: 1.2; margin: var(--s2) 0 var(--s2); }
  .lede { color: var(--ink-2); margin: 0; max-width: 76ch; }
  .note { display: flex; gap: var(--s3); border: 1px solid #e8cf7a; border-left: 3px solid #c9a227; background: #fdf8e4;
          color: #4a3d0a; padding: var(--s3) var(--s4); margin-top: var(--s4); max-width: 76ch; font-size: 13px; }
  .note b { font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; white-space: nowrap; padding-top: 2px; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .note { background: #2a2615; border-color: #6b5a1f; color: #f0e2b0; } }

  /* ---------- controls ---------- */
  .filters { display: flex; flex-wrap: wrap; gap: var(--s2); align-items: center; margin-bottom: var(--s5); }
  .filters select, .filters input[type=search], .toolbar select { height: 36px; border: 1px solid var(--field); border-radius: var(--r);
          background: var(--page); padding: 0 var(--s3); max-width: 220px; }
  .filters input[type=search] { width: 250px; }
  .filters .on { border-color: var(--brand); box-shadow: inset 0 0 0 1px var(--brand); }
  .chk { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-2); font-size: 13px; cursor: pointer; white-space: nowrap; }
  .tlink { background: none; border: 0; padding: 0; color: var(--link); cursor: pointer; font-size: 13px; white-space: nowrap; }
  .tlink:hover { text-decoration: underline; }
  .tlink[disabled] { color: var(--ink-3); cursor: default; text-decoration: none; }
  .fcount { margin-left: auto; color: var(--ink-3); font-size: 12.5px; font-variant-numeric: tabular-nums; }
  .btn { height: 34px; padding: 0 var(--s4); border: 1px solid var(--field); border-radius: var(--r); background: var(--page);
         cursor: pointer; font-size: 13px; display: inline-flex; align-items: center; gap: 6px; color: var(--ink); white-space: nowrap; }
  .btn:hover { background: var(--hover); text-decoration: none; }
  .btn.primary { background: var(--brand); border-color: var(--brand); color: var(--on-brand); }
  .toolbar { display: flex; gap: var(--s3); align-items: center; flex-wrap: wrap; margin-bottom: var(--s5); }
  .toolbar label { font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-2); font-weight: 600; }
  .seg { display: inline-flex; border: 1px solid var(--field); border-radius: var(--r); overflow: hidden; }
  .seg button { border: 0; background: var(--page); padding: 6px var(--s3); cursor: pointer; font-size: 13px; color: var(--ink-2); }
  .seg button + button { border-left: 1px solid var(--field); }
  .seg button[aria-pressed="true"] { background: var(--ink); color: var(--page); }

  /* ---------- health glyph ---------- */
  .g { display: inline-grid; place-items: center; width: 14px; height: 14px; border-radius: 2px; color: #fff; font-size: 9.5px;
       font-weight: 800; line-height: 1; flex: none; vertical-align: -2px; }
  .g.amber { color: #1d1a10; }
  .hb { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
  .c-red { background: var(--critical); } .c-amber { background: var(--warning); } .c-green { background: var(--good); }
  .c-nodate { background: var(--neutral); } .c-done { background: var(--done); } .c-data { background: var(--data); }
  .c-data-soft { background: var(--data-soft); }
  /* White space: anything missing is drawn the same way everywhere, a hatched
     fill in charts and a dashed marker in text, so absence is as visible as
     activity. */
  .c-miss { background: repeating-linear-gradient(135deg, var(--neutral) 0 2px, transparent 2px 6px); box-shadow: inset 0 0 0 1px var(--neutral); }
  .miss { display: inline-block; border: 1px dashed var(--field); color: var(--ink-2); border-radius: 2px; padding: 0 6px;
          font-size: 12px; line-height: 18px; white-space: nowrap; }
  .gaprow { display: grid; grid-template-columns: minmax(90px, 150px) minmax(0, 1fr) 84px; gap: var(--s3); align-items: center;
            font-size: 13px; padding: 5px 0; cursor: pointer; }
  .gaprow:hover .lab { color: var(--link); }
  .gaprow .lab { text-align: right; color: var(--ink-2); }
  .gaprow .val { font-variant-numeric: tabular-nums; }
  .gaprow .val.zero { color: var(--ink-3); }

  /* ---------- stat band ---------- */
  .band { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); border: 1px solid var(--hairline); margin-bottom: var(--s5); }
  .stat { padding: var(--s4) var(--s4) var(--s4); border: 0; border-left: 1px solid var(--hairline); background: none; text-align: left; }
  .stat:first-child { border-left: 0; }
  button.stat { cursor: pointer; }
  button.stat:hover { background: var(--hover); }
  .stat.on { box-shadow: inset 0 -3px 0 var(--brand); }
  .stat .l { font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-2); font-weight: 600; display: flex; gap: 6px; align-items: center; }
  .stat .v { font-size: 30px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.15; margin-top: var(--s2); }
  .stat .s { font-size: 12px; color: var(--ink-3); }

  /* ---------- cards ---------- */
  .grid2 { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: var(--s5); margin-bottom: var(--s5); }
  .grid3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--s5); margin-bottom: var(--s5); }
  .card { border: 1px solid var(--hairline); padding: var(--s5); min-width: 0; }
  .ct { display: flex; justify-content: space-between; align-items: baseline; gap: var(--s3); margin-bottom: var(--s4); flex-wrap: wrap; }
  .ct h2, .ct h3 { font-size: 11.5px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-2); font-weight: 700; margin: 0; }
  .legend { display: flex; gap: var(--s3); flex-wrap: wrap; font-size: 12px; color: var(--ink-2); }
  .legend span { display: inline-flex; gap: 5px; align-items: center; }
  .sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
  .take { border-top: 1px solid var(--hairline); margin-top: var(--s4); padding-top: var(--s3); font-size: 13px; color: var(--ink-2); }
  .section-h { display: flex; align-items: baseline; gap: var(--s4); margin: var(--s7) 0 var(--s4); flex-wrap: wrap; }
  .section-h h2 { font-family: var(--serif); font-weight: 400; font-size: 22px; margin: 0; }
  .section-h p { margin: 0; color: var(--ink-3); font-size: 13px; }
  .empty { color: var(--ink-3); font-size: 13px; padding: var(--s5) 0; text-align: center; }

  /* ---------- charts ---------- */
  .hbars { display: grid; gap: 10px; }
  .hrow { display: grid; grid-template-columns: minmax(90px, 160px) minmax(0, 1fr) 36px; gap: var(--s3); align-items: center; font-size: 13px; }
  .hrow .lab { text-align: right; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hrow .val { font-variant-numeric: tabular-nums; color: var(--ink); }
  .track { display: flex; gap: 2px; height: 18px; }
  .track > span { min-width: 3px; height: 100%; }
  .track > span:first-child { border-radius: 2px 0 0 2px; } .track > span:last-child { border-radius: 0 2px 2px 0; }
  .track > span:only-child { border-radius: 2px; }
  .hrow.click { cursor: pointer; } .hrow.click:hover .lab { color: var(--link); }
  .cols { display: flex; align-items: flex-end; gap: 6px; height: 150px; padding-top: 18px; border-bottom: 1px solid var(--rule); }
  .col { flex: 1; display: flex; flex-direction: column-reverse; align-items: center; height: 100%; position: relative; min-width: 0; }
  .col .stack { display: flex; flex-direction: column-reverse; gap: 2px; width: 70%; max-width: 34px; }
  .col .stack span { display: block; border-radius: 0; }
  .col .stack span:last-child { border-radius: 2px 2px 0 0; }
  .col .top { font-size: 11.5px; color: var(--ink-2); text-align: center; font-variant-numeric: tabular-nums; margin-bottom: 3px; }
  .xl { display: flex; gap: 6px; margin-top: 6px; }
  .xl span { flex: 1; text-align: center; font-size: 11px; color: var(--ink-3); white-space: nowrap; min-width: 0; overflow: visible; }
  svg.line { width: 100%; height: 150px; overflow: visible; display: block; }
  svg.line .axis { stroke: var(--rule); }
  svg.line .ln { fill: none; stroke: var(--data); stroke-width: 2; }
  svg.line .pt { fill: var(--data); stroke: var(--page); stroke-width: 2; }
  svg.line text { font: 11px var(--sans); fill: var(--ink-2); }
  .mini { display: flex; gap: 2px; height: 8px; width: 100%; max-width: 160px; }
  .mini span { height: 100%; }
  .mini span:first-child { border-radius: 2px 0 0 2px; } .mini span:last-child { border-radius: 0 2px 2px 0; }
  .tip { position: fixed; z-index: 60; background: var(--ink); color: var(--page); font-size: 12px; padding: 6px 10px; border-radius: 3px;
         pointer-events: none; max-width: 280px; opacity: 0; transition: opacity .08s; }
  .tip.show { opacity: 1; }

  /* capability health list on the overview */
  .caplist { display: grid; }
  .caprow { display: grid; grid-template-columns: 16px minmax(0, 1fr) 120px 84px; gap: var(--s3); align-items: center; padding: 9px 0;
            border-top: 1px solid var(--hairline); cursor: pointer; font-size: 13px; }
  .caprow:first-child { border-top: 0; padding-top: 0; }
  .caprow:hover .nm { color: var(--link); }
  .caprow .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .caprow .k { color: var(--ink-3); margin-right: 6px; font-variant-numeric: tabular-nums; }
  .caprow .hl { color: var(--ink-2); font-size: 12.5px; }

  /* ---------- tables ---------- */
  .tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
  .tbl th { text-align: left; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-2); font-weight: 700;
            padding: var(--s2) var(--s3); border-bottom: 1px solid var(--rule); white-space: nowrap; background: var(--page); position: sticky; top: 0; z-index: 1; }
  .tbl th button { background: none; border: 0; padding: 0; cursor: pointer; font: inherit; color: inherit; letter-spacing: inherit; text-transform: inherit; display: inline-flex; gap: 4px; }
  .tbl th .ar { color: var(--ink-3); }
  .tbl th[aria-sort] .ar { color: var(--eyebrow); }
  .tbl td { padding: 11px var(--s3); border-bottom: 1px solid var(--hairline); vertical-align: middle; }
  .tbl tbody tr.row { cursor: pointer; }
  .tbl tbody tr.row:hover { background: var(--hover); }
  .tbl .num { text-align: right; font-variant-numeric: tabular-nums; }
  .tbl .nw { white-space: nowrap; }
  .tbl .sub { color: var(--ink-3); font-size: 12px; }
  .tbl .key { white-space: nowrap; font-variant-numeric: tabular-nums; }
  .tbl .ttl { font-weight: 600; }
  .tbl tr.child td { background: var(--panel); }
  .tbl tr.child td:first-child { box-shadow: inset 3px 0 0 var(--rule); }
  .scroll { overflow-x: auto; }
  .more { text-align: center; padding: var(--s4); }
  .tog { background: none; border: 0; cursor: pointer; color: var(--ink-3); width: 20px; padding: 0; font-size: 11px; display: inline-block; }
  .toolbar select { max-width: none; }

  /* ---------- weekly report ---------- */
  .rag { border: 1px solid var(--hairline); border-top: 3px solid var(--neutral); padding: var(--s5); }
  .rag.red { border-top-color: var(--critical); } .rag.amber { border-top-color: var(--warning); } .rag.green { border-top-color: var(--good); }
  .overall { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--s5); align-items: start; margin-bottom: var(--s5); }
  .overall .t { font-family: var(--serif); font-size: 22px; display: flex; gap: var(--s2); align-items: center; white-space: nowrap; }
  .overall p { margin: 4px 0 0; color: var(--ink-2); }
  .elem .t { font-weight: 600; display: flex; gap: var(--s2); align-items: center; }
  .elem .big { font-size: 26px; font-weight: 700; margin: var(--s2) 0 var(--s1); }
  .elem p { margin: 0; color: var(--ink-2); font-size: 13px; }
  .rsec { border: 1px solid var(--hairline); padding: var(--s5); margin-bottom: var(--s4); }
  .rsec > h3 { font-size: 11.5px; letter-spacing: 0.1em; text-transform: uppercase; margin: 0; padding-bottom: var(--s3); border-bottom: 1px solid var(--hairline); }
  .rsec .rnote { font-size: 13px; color: var(--ink-3); font-style: italic; margin: var(--s3) 0 0; }
  .rgrp { padding: var(--s3) 0; border-bottom: 1px solid var(--hairline); }
  .rgrp:last-child { border-bottom: 0; padding-bottom: 0; }
  .rgrp h4 { font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--eyebrow); margin: var(--s1) 0 var(--s2); }
  .rgrp ul { margin: 0; padding: 0; list-style: none; max-width: 92ch; }
  .rgrp li { display: grid; grid-template-columns: 14px minmax(0, 1fr); gap: var(--s2); padding: 4px 0; align-items: baseline; }
  .rgrp li .g { vertical-align: 0; }
  .rgrp .what { color: var(--ink-2); }

  /* ---------- actions ---------- */
  .act { display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: var(--s6); align-items: start; }
  .side { position: sticky; top: var(--s4); }
  .side h4 { font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-3); margin: var(--s4) 0 var(--s1); }
  .side button { display: flex; justify-content: space-between; width: 100%; background: none; border: 0; padding: 7px var(--s2);
                 cursor: pointer; text-align: left; border-radius: var(--r); font-size: 13px; color: var(--ink); gap: var(--s2); }
  .side button:hover { background: var(--hover); }
  .side button[aria-current="true"] { background: var(--panel); font-weight: 600; box-shadow: inset 3px 0 0 var(--brand); }
  .side button .c { font-variant-numeric: tabular-nums; color: var(--ink-2); }
  .side button.zero { color: var(--ink-3); }
  .grp { border: 1px solid var(--hairline); margin-bottom: var(--s4); }
  .grp-h { display: flex; gap: var(--s4); align-items: flex-start; justify-content: space-between; padding: var(--s3) var(--s4);
           border-bottom: 1px solid var(--hairline); background: var(--panel); flex-wrap: wrap; }
  .grp-h .t { font-weight: 600; }
  .grp-h .t .n { color: var(--ink-3); font-weight: 400; }
  .grp-h .hint { font-size: 12.5px; color: var(--ink-2); }
  .grp-h .acts { display: flex; gap: var(--s4); flex-wrap: wrap; padding-top: 2px; }
  .item { display: grid; grid-template-columns: 14px 64px minmax(0, 1.6fr) minmax(0, 0.9fr) minmax(0, 1.3fr) 104px; gap: var(--s3);
          align-items: center; padding: 10px var(--s4); border-top: 1px solid var(--hairline); font-size: 13px; }
  .item:first-of-type { border-top: 0; }
  .item:hover { background: var(--hover); }
  .item.nudged { color: var(--ink-3); }
  .item .sm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .item .o { color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .item .d { color: var(--ink-2); }
  .item .nb { text-align: right; }
  .linkish { background: none; border: 0; padding: 0; color: var(--ink); cursor: pointer; text-align: left; font: inherit; max-width: 100%; }
  .linkish:hover { color: var(--link); text-decoration: underline; }

  /* ---------- drawer ---------- */
  dialog.drawer { margin: 0 0 0 auto; height: 100%; max-height: 100%; width: min(540px, 100vw); border: 0; border-left: 1px solid var(--hairline);
                  padding: 0; background: var(--page); color: var(--ink); }
  dialog.drawer::backdrop { background: rgba(10,12,16,0.35); }
  .dh { display: flex; gap: var(--s3); align-items: center; padding: var(--s3) var(--s5); border-bottom: 1px solid var(--hairline);
        position: sticky; top: 0; background: var(--page); }
  .dh .k { color: var(--ink-3); font-variant-numeric: tabular-nums; }
  .dh .x { margin-left: auto; }
  .db { padding: var(--s5); }
  .db h2 { font-family: var(--serif); font-weight: 400; font-size: 22px; line-height: 1.25; margin: 0 0 var(--s4); }
  .db h3 { font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-2); margin: var(--s6) 0 var(--s2); }
  dl.kv { display: grid; grid-template-columns: 130px minmax(0, 1fr); gap: 6px var(--s3); margin: 0; font-size: 13px; }
  dl.kv dt { color: var(--ink-3); } dl.kv dd { margin: 0; }
  .db ul { margin: 0; padding-left: 18px; font-size: 13px; color: var(--ink-2); }
  .db ul.todo { list-style: none; padding: 0; }
  .db ul.todo li { border-top: 1px solid var(--hairline); padding: var(--s2) 0; display: grid; gap: 2px; }
  .db ul.todo li:first-child { border-top: 0; }
  .db ul.todo b { color: var(--ink); font-weight: 600; }

  /* ---------- method ---------- */
  .prose { max-width: 76ch; }
  .prose h2 { font-family: var(--serif); font-weight: 400; font-size: 21px; margin: var(--s7) 0 var(--s2); }
  .prose p, .prose li { color: var(--ink-2); }
  .prose code { background: var(--panel); padding: 1px 5px; border-radius: 2px; font-size: 12.5px; }

  .toast { position: fixed; bottom: var(--s6); left: 50%; transform: translateX(-50%); background: var(--ink); color: var(--page);
           padding: var(--s2) var(--s4); border-radius: 3px; font-size: 13px; opacity: 0; pointer-events: none; transition: opacity .15s; z-index: 70; }
  .toast.show { opacity: 1; }
  footer { border-top: 1px solid var(--hairline); margin-top: var(--s8); padding-top: var(--s3); color: var(--ink-3); font-size: 12px; }

  @media (max-width: 1000px) {
    .grid3 { grid-template-columns: 1fr; }
    .grid2 { grid-template-columns: 1fr; }
    .band { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .band .stat:nth-child(4) { border-left: 0; }
    .band .stat:nth-child(n+4) { border-top: 1px solid var(--hairline); }
    .act { grid-template-columns: 1fr; }
    .side { position: static; display: flex; flex-wrap: wrap; gap: var(--s1); }
    .side h4 { width: 100%; margin: var(--s2) 0 0; }
    .side button { width: auto; border: 1px solid var(--hairline); }
    .item { grid-template-columns: 14px 64px minmax(0, 1fr) 100px; }
    .item .o { display: none; }
    .item .d { grid-column: 3; }
  }
  @media (max-width: 640px) {
    .mast-in, .wrap { padding-left: var(--s4); padding-right: var(--s4); }
    .mast .asof { display: none; }
    .mast-in { flex-wrap: wrap; gap: 0; padding-top: var(--s2); }
    .nav { width: 100%; flex: none; }
    h1 { font-size: 25px; }
    .band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .band .stat:nth-child(odd) { border-left: 0; }
    .band .stat:nth-child(4) { border-left: 1px solid var(--hairline); }
    .band .stat:nth-child(n+3) { border-top: 1px solid var(--hairline); }
    .filters input[type=search] { width: 100%; }
    .filters select { flex: 1 1 140px; max-width: none; }
    .overall { grid-template-columns: 1fr; gap: var(--s2); }
    .caprow { grid-template-columns: 16px minmax(0, 1fr) 70px; }
    .caprow .hl { display: none; }
    .item { grid-template-columns: 14px minmax(0, 1fr); }
    .item > * { grid-column: 2; }
    .item > .g { grid-column: 1; grid-row: 1; }
    .item .nb { text-align: left; }
    .hrow { grid-template-columns: 90px minmax(0, 1fr) 28px; }
    dl.kv { grid-template-columns: 100px minmax(0, 1fr); }
  }
  @media print {
    .mast .nav, .filters, .toolbar, .stale, .acts, .nb, .tog, .more { display: none !important; }
    .mast { background: none; color: #000; border-bottom: 2px solid #000; }
    .card, .rsec, .rag, .grp { break-inside: avoid; }
  }
</style>
</head>
<body>
<header class="mast">
  <div class="mast-in">
    <span class="name" id="m-title"></span>
    <nav class="nav" role="tablist" aria-label="Views">
      <button role="tab" data-tab="overview" id="t-overview" aria-controls="p-overview">Overview</button>
      <button role="tab" data-tab="report" id="t-report" aria-controls="p-report">Weekly report</button>
      <button role="tab" data-tab="actions" id="t-actions" aria-controls="p-actions">Actions<span class="n" id="n-actions"></span></button>
      <button role="tab" data-tab="caps" id="t-caps" aria-controls="p-caps">Capabilities</button>
      <button role="tab" data-tab="issues" id="t-issues" aria-controls="p-issues">Issues</button>
      <button role="tab" data-tab="method" id="t-method" aria-controls="p-method">Method</button>
    </nav>
    <span class="asof" id="m-asof"></span>
  </div>
</header>
<div class="stale" id="stale" hidden><div id="stale-t"></div></div>

<main class="wrap">
  <div class="head" id="head"></div>

  <div class="filters" id="filters" role="search" aria-label="Filters">
    <input type="search" id="f-q" placeholder="Search key, summary, owner" aria-label="Search">
    <select id="f-owner" aria-label="Owner"></select>
    <select id="f-cap" aria-label="Capability"></select>
    <select id="f-health" aria-label="Health"></select>
    <select id="f-status" aria-label="Jira status"></select>
    <select id="f-type" aria-label="Issue type"></select>
    <label class="chk"><input type="checkbox" id="f-done"> Include done</label>
    <button class="tlink" id="f-reset" type="button">Reset</button>
    <span class="fcount" id="fcount" aria-live="polite"></span>
  </div>

  <section id="p-overview" role="tabpanel" aria-labelledby="t-overview" hidden></section>
  <section id="p-report" role="tabpanel" aria-labelledby="t-report" hidden></section>
  <section id="p-actions" role="tabpanel" aria-labelledby="t-actions" hidden></section>
  <section id="p-caps" role="tabpanel" aria-labelledby="t-caps" hidden></section>
  <section id="p-issues" role="tabpanel" aria-labelledby="t-issues" hidden></section>
  <section id="p-method" role="tabpanel" aria-labelledby="t-method" hidden></section>

  <footer id="footer"></footer>
</main>

<dialog class="drawer" id="drawer" aria-labelledby="d-title">
  <div class="dh">
    <span class="k" id="d-key"></span>
    <a class="btn primary" id="d-open" target="_blank" rel="noopener noreferrer">Open in Jira ↗</a>
    <button class="tlink" id="d-copy" type="button">Copy link</button>
    <button class="btn x" id="d-close" type="button" aria-label="Close">Close</button>
  </div>
  <div class="db" id="d-body"></div>
</dialog>
<div class="tip" id="tip" role="tooltip"></div>
<div class="toast" id="toast" role="status" aria-live="polite"></div>

<script id="portfolio-data" type="application/json">__DATA__</script>
<script>
"use strict";
(function () {
const DATA = JSON.parse(document.getElementById("portfolio-data").textContent);
const META = DATA.meta, CHECKS = DATA.checks, ISSUES = DATA.issues, REPORTS = DATA.reports || [], TRENDS = DATA.trends;
const CHECK = Object.fromEntries(CHECKS.map(c => [c.code, c]));
const BY_KEY = new Map(ISSUES.map(r => [r.key, r]));
const JIRA = /^https?:\/\//i.test(META.jiraBase || "") ? META.jiraBase.replace(/\/+$/, "") : "";
const TABS = ["overview", "report", "actions", "caps", "issues", "method"];

const HEALTH = {
  red:    { label: "Off track",    glyph: "✕", rank: 0 },
  amber:  { label: "At risk",      glyph: "!", rank: 1 },
  nodate: { label: "Not assessed", glyph: "?", rank: 2 },
  green:  { label: "On track",     glyph: "✓", rank: 3 },
  done:   { label: "Done",         glyph: "•", rank: 4 },
};
const OPEN_H = ["red", "amber", "nodate", "green"];
const RAG = { red: "Red", amber: "Amber", green: "Green" };
const KIND = { capability: "Capability", epic: "Epic", other: "Other" };
const NONE = "__none";

/* ---------- helpers ---------- */
function h(tag, props, ...kids) {
  const n = document.createElement(tag);
  if (props) for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) n.append(c instanceof Node ? c : String(c));
  return n;
}
const $ = id => document.getElementById(id);
const plural = (n, one, many) => n + " " + (n === 1 ? one : (many || one + "s"));
const isCap = r => r.kind === "capability";
const isOpen = r => r.statusCat !== "done";
const shown = r => isCap(r) ? r.rollup : r.health;
const capOf = r => isCap(r) ? r.key : (r.parent || NONE);
const safe = u => /^https?:\/\//i.test(u || "") ? u : null;
const byKey = (a, b) => {
  const pa = /^(.*?)-(\d+)$/.exec(a), pb = /^(.*?)-(\d+)$/.exec(b);
  return pa && pb && pa[1] === pb[1] ? pa[2] - pb[2] : String(a).localeCompare(String(b));
};
const worstFirst = (a, b) => HEALTH[shown(a)].rank - HEALTH[shown(b)].rank || byKey(a.key, b.key);
const d8 = s => new Date(s + "T00:00:00");
const fmt = (s, opt) => s ? d8(s).toLocaleDateString(undefined, opt || { month: "short", day: "numeric" }) : "";
const fmtY = s => fmt(s, { month: "short", day: "numeric", year: "numeric" });
const rel = n => n == null ? "" : n === 0 ? "today" : n > 0 ? "in " + plural(n, "day") : plural(-n, "day") + " ago";

const miss = t => h("span", { class: "miss", text: t });
function glyph(hk) { return h("span", { class: "g c-" + hk + " " + hk, "aria-hidden": "true", text: HEALTH[hk].glyph }); }
function badge(hk) { return h("span", { class: "hb" }, glyph(hk), HEALTH[hk].label); }
function keyLink(r) {
  const u = safe(r.url);
  return u ? h("a", { class: "key", href: u, target: "_blank", rel: "noopener noreferrer", title: "Open " + r.key + " in Jira",
    onclick: e => e.stopPropagation(), text: r.key }) : h("span", { class: "key", text: r.key });
}
function jql(keys) {
  if (!JIRA || !keys.length) return null;
  return JIRA + "/issues/?jql=" + encodeURIComponent("key in (" + keys.slice(0, 200).join(",") + ") ORDER BY key");
}
function jiraLink(keys, label) {
  const u = jql(keys);
  return u ? h("a", { href: u, target: "_blank", rel: "noopener noreferrer", class: "tlink",
    title: "Open in Jira's issue navigator, where you can bulk edit", text: (label || "Open " + keys.length + " in Jira") + " ↗" }) : null;
}

let toastT;
function toast(msg) { const t = $("toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 2200); }
async function copy(text, what, html) {
  try {
    if (html && window.ClipboardItem && navigator.clipboard.write) {
      await navigator.clipboard.write([new ClipboardItem({ "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([text], { type: "text/plain" }) })]);
    } else await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = h("textarea", { style: "position:fixed;opacity:0" }); ta.value = text; document.body.append(ta); ta.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch (e2) { ok = false; }
    ta.remove();
    if (!ok) { toast("Couldn't reach the clipboard"); return; }
  }
  toast((what || "Copied") + " to the clipboard");
}
function download(name, text, type) {
  const a = h("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  document.body.append(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

/* tooltip: anything with data-tip */
const tip = $("tip");
function showTip(e) {
  const t = e.target.closest && e.target.closest("[data-tip]");
  if (!t) { tip.classList.remove("show"); return; }
  tip.textContent = t.dataset.tip;
  tip.classList.add("show");
  const r = t.getBoundingClientRect();
  const x = e.clientX != null && e.type === "mousemove" ? e.clientX : r.left + r.width / 2;
  const y = e.type === "mousemove" ? e.clientY : r.top;
  tip.style.left = Math.min(window.innerWidth - tip.offsetWidth - 8, Math.max(8, x - tip.offsetWidth / 2)) + "px";
  tip.style.top = Math.max(8, y - tip.offsetHeight - 12) + "px";
}
document.addEventListener("mousemove", showTip);
document.addEventListener("focusin", showTip);
document.addEventListener("scroll", () => tip.classList.remove("show"), true);

/* ---------- nudges: this browser only ---------- */
const NUDGE_KEY = "jira-portfolio:nudged:" + (META.jiraHost || "local");
let nudged = {};
try { nudged = JSON.parse(localStorage.getItem(NUDGE_KEY) || "{}") || {}; } catch (e) { nudged = {}; }
const nid = (r, g) => r.key + "|" + g.code;
function setNudged(id, on) {
  if (on) nudged[id] = new Date().toISOString().slice(0, 10); else delete nudged[id];
  try { localStorage.setItem(NUDGE_KEY, JSON.stringify(nudged)); } catch (e) { /* lasts this session */ }
}

/* ---------- state lives in the URL, so a view can be shared ---------- */
const DEF = { tab: "overview", q: "", owner: "", cap: "", health: "", status: "", type: "", done: "",
  group: "check", check: "", nudged: "", sort: "health", dir: "asc", week: "" };
const S = Object.assign({}, DEF);
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const k of Object.keys(DEF)) S[k] = p.has(k) ? p.get(k) : DEF[k];
  if (!TABS.includes(S.tab)) S.tab = "overview";
}
function writeHash() {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(S)) if (v !== DEF[k]) p.set(k, v);
  const s = p.toString();
  history.replaceState(null, "", s ? "#" + s : location.pathname + location.search);
}
function set(patch) { Object.assign(S, patch); writeHash(); render(); }

function match(r, o) {
  o = o || {};
  if (!S.done && !o.keepDone && !isOpen(r)) return false;
  if (S.owner && (r.owner || NONE) !== S.owner) return false;
  if (S.cap && capOf(r) !== S.cap) return false;
  if (!o.anyHealth && S.health && shown(r) !== S.health) return false;
  if (S.status && r.status !== S.status) return false;
  if (S.type && r.kind !== S.type) return false;
  if (S.q) {
    const hay = (r.key + " " + r.summary + " " + r.owner + " " + r.status + " " + (r.parentSummary || "")).toLowerCase();
    for (const t of S.q.toLowerCase().split(/\s+/).filter(Boolean)) if (!hay.includes(t)) return false;
  }
  return true;
}
const rows = o => ISSUES.filter(r => match(r, o));

/* ---------- page head per tab ---------- */
function head(kicker, title, lede, extra) {
  $("head").replaceChildren(h("div", { class: "kicker", text: kicker }), h("h1", { text: title }),
    ...[lede ? h("p", { class: "lede", text: lede }) : null, extra].filter(Boolean));
}
const sampleNote = () => META.source === "sample" ? h("div", { class: "note" }, h("b", { text: "Sample data" }),
  h("span", { text: "Invented issues and an invented eight-week history, so every chart and the weekly report have something to show. Point it at Jira for the real thing." })) : null;

/* ---------- charts ---------- */
function hbars(list, opt) {
  opt = opt || {};
  const max = Math.max(1, ...list.map(x => x.total));
  return h("div", { class: "hbars" }, list.map(x => {
    const track = h("div", { class: "track", style: "width:" + (100 * x.total / max) + "%" },
      x.segs.filter(s => s.n).map(s => h("span", { class: "c-" + s.k, style: "flex:" + s.n, "data-tip": s.tip || (s.n + " " + (HEALTH[s.k] ? HEALTH[s.k].label.toLowerCase() : "")) })));
    return h("div", { class: "hrow" + (x.onclick ? " click" : ""), onclick: x.onclick || null, title: x.title || null },
      h("span", { class: "lab", text: x.label }), h("div", null, track), h("span", { class: "val", text: x.total }));
  }));
}
function columns(list) {
  const max = Math.max(1, ...list.map(c => c.total));
  return h("div", null,
    h("div", { class: "cols" }, list.map(c => h("div", { class: "col" },
      h("div", { class: "stack", style: "height:" + (100 * c.total / max) + "%" },
        c.segs.filter(s => s.n).map(s => h("span", { class: "c-" + s.k, style: "flex:" + s.n, "data-tip": c.tipLabel + ": " + s.n + " " + (s.label || "") }))),
      h("div", { class: "top", text: c.total || "" })))),
    h("div", { class: "xl" }, list.map((c, i) => h("span", { text: list.length <= 7 || i === 0 || i === list.length - 1 || (i % 2 === 0 && i < list.length - 2) ? c.label : "" }))));
}
function line(pts, o) {
  o = o || {};
  const unit = o.unit || "d", tipOf = o.tip || (p => p.label + ": median " + p.v + " days (" + plural(p.n, "item") + ")");
  const W = 300, H = 130, P = 16, valid = pts.filter(p => p.v != null);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "line"); svg.setAttribute("viewBox", "0 0 " + W + " " + (H + 18)); svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", pts.map(p => p.label + ": " + (p.v == null ? "none" : p.v + unit)).join(", "));
  const S_ = (t, a, txt) => { const e = document.createElementNS("http://www.w3.org/2000/svg", t); for (const k in a) e.setAttribute(k, a[k]); if (txt != null) e.textContent = txt; svg.append(e); return e; };
  const max = o.max || Math.max(1, ...valid.map(p => p.v)), min = 0;
  const x = i => P + (W - 2 * P) * (pts.length === 1 ? 0.5 : i / (pts.length - 1));
  const y = v => P + (H - 2 * P) * (1 - (v - min) / (max - min || 1));
  S_("line", { class: "axis", x1: 0, x2: W, y1: H, y2: H });
  const seq = pts.map((p, i) => p.v == null ? null : [x(i), y(p.v)]).filter(Boolean);
  if (seq.length > 1) S_("polyline", { class: "ln", points: seq.map(p => p.join(",")).join(" "), "vector-effect": "non-scaling-stroke" });
  pts.forEach((p, i) => {
    S_("text", { x: x(i), y: H + 15, "text-anchor": "middle" }, p.label);
    if (p.v == null) return;
    const c = S_("circle", { class: "pt", cx: x(i), cy: y(p.v), r: 4, "vector-effect": "non-scaling-stroke" });
    c.setAttribute("data-tip", tipOf(p));
    if (i === pts.length - 1 || p === valid[0]) S_("text", { x: x(i), y: y(p.v) - 9, "text-anchor": "middle" }, p.v + unit);
  });
  return svg;
}
function card(title, body, take, legend) {
  return h("section", { class: "card", "aria-label": title },
    h("div", { class: "ct" }, h("h2", { text: title }), legend || null), body, take ? h("div", { class: "take", text: take }) : null);
}
function healthLegend(keys) {
  return h("div", { class: "legend" }, (keys || OPEN_H).map(k => h("span", null, h("span", { class: "sw c-" + k }), HEALTH[k].label)));
}
const segsOf = (list, f) => OPEN_H.map(k => ({ k, n: list.filter(r => (f || shown)(r) === k).length }));
const monthLabel = m => new Date(m + "-01T00:00:00").toLocaleDateString(undefined, { month: "short" });

/* ---------- overview ---------- */
function renderOverview() {
  head("Portfolio overview", "Where the portfolio stands",
    "Every capability and epic in Jira, scored for health on " + fmtY(META.today) + ". Filters below apply to everything on this page except the trends.", sampleNote());
  const all = rows({ anyHealth: true }).filter(isOpen);
  const caps = all.filter(isCap), epics = all.filter(r => r.kind === "epic");
  const cnt = (l, k) => l.filter(r => shown(r) === k).length;
  const stat = (l, v, s, hk) => {
    const n = h(hk ? "button" : "div", { class: "stat" + (hk && S.health === hk ? " on" : ""), type: hk ? "button" : null,
      "aria-pressed": hk ? String(S.health === hk) : null, title: hk ? "Show only " + HEALTH[hk].label.toLowerCase() : null,
      onclick: hk ? () => set({ health: S.health === hk ? "" : hk }) : null },
      h("div", { class: "l" }, hk ? glyph(hk) : null, l), h("div", { class: "v", text: v }), h("div", { class: "s", text: s }));
    return n;
  };
  const band = h("div", { class: "band" },
    stat("Capabilities", caps.length, "open"),
    stat("Epics", epics.length, "open"),
    stat("On track", cnt(all, "green"), "dated, moving, current", "green"),
    stat("At risk", cnt(all, "amber"), "close, stalled or on hold", "amber"),
    stat("Off track", cnt(all, "red"), "late, blocked or flagged", "red"),
    stat("Not assessed", cnt(all, "nodate"), "no due date", "nodate"));

  // capability health
  const capRows = rows().filter(isCap).sort(worstFirst);
  const capBody = capRows.length ? h("div", { class: "caplist" }, capRows.map(c => {
    const kids = c.children.map(k => BY_KEY.get(k)).filter(k => k && isOpen(k));
    const mini = h("div", { class: "mini" }, kids.length ? OPEN_H.filter(k => c.childCounts[k]).map(k =>
      h("span", { class: "c-" + k, style: "flex:" + c.childCounts[k], "data-tip": c.childCounts[k] + " " + HEALTH[k].label.toLowerCase() }))
      : h("span", { class: "c-miss", style: "flex:1", "data-tip": c.children.length ? "No open epics" : "No epics yet" }));
    return h("div", { class: "caprow", tabindex: "0", role: "button", onclick: () => openDrawer(c.key), onkeydown: e => { if (e.key === "Enter") openDrawer(c.key); } },
      glyph(c.rollup), h("span", { class: "nm", title: c.summary }, h("span", { class: "k", text: c.key }), c.summary),
      mini, h("span", { class: "hl", text: HEALTH[c.rollup].label }));
  })) : h("div", { class: "empty", text: "No capabilities match these filters." });
  const capTake = capRows.length ? (cnt(capRows, "red") + " of " + capRows.length + " capabilities are off track and " + cnt(capRows, "amber") +
    " at risk. A capability takes the health of its worst open epic; the bar shows its epics.") : null;

  // pipeline by jira status
  const order = { todo: 0, inprogress: 1, done: 2 };
  const statuses = [...new Set(all.map(r => r.status))].sort((a, b) => {
    const ra = all.find(r => r.status === a), rb = all.find(r => r.status === b);
    return order[ra.statusCat] - order[rb.statusCat] || all.filter(r => r.status === b).length - all.filter(r => r.status === a).length;
  });
  const pipe = statuses.length ? hbars(statuses.map(s => {
    const l = all.filter(r => r.status === s);
    return { label: s, total: l.length, segs: segsOf(l), onclick: () => set({ tab: "issues", status: s }), title: "List the " + l.length + " in " + s };
  })) : h("div", { class: "empty", text: "Nothing open matches these filters." });
  const biggest = statuses.slice().sort((a, b) => all.filter(r => r.status === b).length - all.filter(r => r.status === a).length)[0];
  const redStat = statuses.filter(s => all.some(r => r.status === s && shown(r) === "red"));
  const pipeTake = biggest ? "Most open work sits in " + biggest + " (" + all.filter(r => r.status === biggest).length + ")." +
    (redStat.length ? " Off-track items sit in " + redStat.join(", ") + "." : "") + " Select a status to list it." : null;

  // trends (whole portfolio)
  const W = TRENDS.weekly || [], M = TRENDS.monthly || [], unit = TRENDS.unit;
  const weekCard = W.length > 1 ? card("Health week by week", columns(W.map(w => ({
      label: fmt(w.date), tipLabel: "Week of " + fmt(w.date), total: OPEN_H.reduce((t, k) => t + w[k], 0),
      segs: ["green", "nodate", "amber", "red"].map(k => ({ k, n: w[k], label: HEALTH[k].label.toLowerCase() })) }))),
      (() => { const a = W[0], b = W[W.length - 1]; return "Open " + unit + " off track went from " + a.red + " to " + b.red +
        " and at risk from " + a.amber + " to " + b.amber + " since " + fmt(a.date) + "."; })(), healthLegend())
    : card("Health week by week", h("div", { class: "empty", text: "Builds from the snapshot each run saves. " +
        (W.length ? "One week so far; next week's run adds the second." : "No snapshots yet.") }));
  const doneCard = card(unit[0].toUpperCase() + unit.slice(1) + " completed per month", columns(M.map(m => ({
      label: monthLabel(m.month), tipLabel: monthLabel(m.month), total: m.completed, segs: [{ k: "data", n: m.completed, label: "completed" }] }))),
    (() => { const cur = M[M.length - 1], prev = M[M.length - 2]; const tot = M.reduce((t, m) => t + m.completed, 0);
      return tot ? cur.completed + " in " + monthLabel(cur.month) + " so far, " + (prev ? prev.completed + " in " + monthLabel(prev.month) + ". " : "") +
        tot + " over six months. Counts what your JQL returns, so include recently resolved work." : "Nothing resolved in the last six months is in this pull. Widen the JQL to include resolved work."; })());
  const cyc = M.map(m => ({ label: monthLabel(m.month), v: m.medianCycle, n: m.completed }));
  const cycV = cyc.filter(p => p.v != null);
  const cycleCard = card("Cycle time, created to done", cycV.length ? line(cyc) : h("div", { class: "empty", text: "No resolved work in the pull to time." }),
    cycV.length > 1 ? "Median " + cycV[cycV.length - 1].v + " days in " + cycV[cycV.length - 1].label + ", " +
      (cycV[cycV.length - 1].v <= cycV[cycV.length - 2].v ? "down" : "up") + " from " + cycV[cycV.length - 2].v + " in " + cycV[cycV.length - 2].label + "." : null);

  // due ahead, with the undated work as its own column: what can't be scheduled is as visible as what's coming
  const base = d8(META.today);
  const buckets = [{ label: "Late", test: n => n < 0 }].concat([0, 1, 2, 3, 4, 5, 6, 7].map(i => ({
    label: i === 0 ? "This wk" : fmt(new Date(base.getTime() + 7 * i * 864e5).toISOString().slice(0, 10)), test: n => n >= 7 * i && n < 7 * (i + 1) })));
  const dated = all.filter(r => r.daysToDue != null), undated = all.filter(r => r.daysToDue == null);
  const dueCols = buckets.map(b => { const l = dated.filter(r => b.test(r.daysToDue));
    return { label: b.label, tipLabel: b.label === "Late" ? "Past due" : "Due week of " + b.label, total: l.length,
      segs: ["green", "amber", "red"].map(k => ({ k, n: l.filter(r => shown(r) === k).length, label: HEALTH[k].label.toLowerCase() })) }; });
  dueCols.push({ label: "No date", tipLabel: "No due date", total: undated.length, segs: [{ k: "miss", n: undated.length, label: "with no due date" }] });
  const late = dueCols[0].total, twoWk = dueCols[1].total + dueCols[2].total;
  const dueCard = card("Due in the next eight weeks", columns(dueCols),
    plural(twoWk, "item is", "items are") + " due in the next two weeks" + (late ? " and " + plural(late, "is", "are") + " already late" : "") +
    ". " + (undated.length ? plural(undated.length, "open item has", "open items have") + " no due date at all, so " + (undated.length === 1 ? "it" : "they") + " can't be scheduled."
      : "Every open item has a due date."),
    h("div", { class: "legend" }, ["green", "amber", "red"].map(k => h("span", null, h("span", { class: "sw c-" + k }), HEALTH[k].label)),
      h("span", null, h("span", { class: "sw c-miss" }), "No date")));

  // what's missing: each field the board needs, filled versus empty
  const reqFields = (META.rules.requiredFields || []);
  const gapRows = [
    { label: "Owner", code: "no_owner", of: all },
    { label: "Due date", code: "no_due", of: all },
    { label: "Capability link", code: "no_parent", of: all.filter(r => r.kind === "epic"), unit: "epics" },
    { label: "Epics", code: "no_children", of: caps, unit: "capabilities" },
    { label: "Description", code: "no_description", of: all },
    ...reqFields.map(f => ({ label: f.label, code: "missing_field", detail: "Missing " + f.label,
      of: f.types.length ? all.filter(r => f.types.includes(r.type)) : all })),
    { label: "Update in " + META.rules.staleDays + " days", code: "stale", of: all },
  ].filter(g => CHECK[g.code] && g.of.length);
  const hasGap = (r, g) => r.gaps.some(x => x.code === g.code && (!g.detail || x.detail === g.detail));
  for (const g of gapRows) g.miss = g.of.filter(r => hasGap(r, g)).length;
  const missBody = gapRows.length ? h("div", null, gapRows.map(g => h("div", { class: "gaprow", role: "button", tabindex: "0",
      title: g.miss ? "See the " + g.miss + " in Actions" : null,
      onclick: () => set({ tab: "actions", check: g.code }), onkeydown: e => { if (e.key === "Enter") set({ tab: "actions", check: g.code }); } },
    h("span", { class: "lab", text: g.label }),
    h("div", { class: "track" }, g.of.length - g.miss ? h("span", { class: "c-data", style: "flex:" + (g.of.length - g.miss),
        "data-tip": (g.of.length - g.miss) + " of " + g.of.length + " " + (g.unit || "open items") + " have it" }) : null,
      g.miss ? h("span", { class: "c-miss", style: "flex:" + g.miss, "data-tip": g.miss + " of " + g.of.length + " " + (g.unit || "open items") + " missing it" }) : null),
    h("span", { class: "val" + (g.miss ? "" : " zero"), text: g.miss ? g.miss + " missing" : "complete" }))))
    : h("div", { class: "empty", text: "Nothing open matches these filters." });
  const worstGap = gapRows.filter(g => g.miss).sort((a, b) => b.miss / b.of.length - a.miss / a.of.length)[0];
  const missCard = card("What's missing", missBody, worstGap
    ? "Biggest gap: " + worstGap.label.toLowerCase() + ", missing on " + worstGap.miss + " of " + worstGap.of.length + " " + (worstGap.unit || "open items") + ". Select a row to see which."
    : "Nothing missing. Every open item carries what the board needs.",
    h("div", { class: "legend" }, h("span", null, h("span", { class: "sw c-data" }), "Has it"), h("span", null, h("span", { class: "sw c-miss" }), "Missing")));

  // time in current status: what hasn't moved
  const tb = [["< 1 wk", 0, 7], ["1–2 wks", 7, 14], ["2–4 wks", 14, 28], ["4–8 wks", 28, 56], ["8+ wks", 56, Infinity]];
  const timed = all.filter(r => r.daysInStatus != null), untimed = all.filter(r => r.daysInStatus == null);
  const tCols = tb.map(([label, lo, hi]) => { const l = timed.filter(r => r.daysInStatus >= lo && r.daysInStatus < hi);
    return { label, tipLabel: "In the same status " + label, total: l.length,
      segs: ["green", "nodate", "amber", "red"].map(k => ({ k, n: l.filter(r => shown(r) === k).length, label: HEALTH[k].label.toLowerCase() })) }; });
  if (untimed.length) tCols.push({ label: "Unknown", tipLabel: "No history yet", total: untimed.length, segs: [{ k: "miss", n: untimed.length, label: "not yet timed" }] });
  const sw = META.rules.stuckWeeks || 3;
  const stuck = timed.filter(r => r.daysInStatus >= 7 * sw && (r.statusCat === "todo" || META.rules.redStatuses.concat(META.rules.amberStatuses).map(s => s.toLowerCase()).includes(r.status.toLowerCase())));
  const statusCard = card("Time in current status", columns(tCols),
    (stuck.length ? plural(stuck.length, "open item has", "open items have") + " been not started, blocked or on hold for " + sw + "+ weeks: " +
      stuck.slice(0, 4).map(r => r.key).join(", ") + (stuck.length > 4 ? " and more" : "") + ". " : "Nothing has sat unstarted, blocked or on hold for " + sw + "+ weeks. ") +
    (untimed.length ? plural(untimed.length, "item isn't", "items aren't") + " timed yet; each weekly snapshot adds history." : ""),
    healthLegend());

  // by owner
  const owners = {};
  for (const r of all) (owners[r.owner || "No owner"] = owners[r.owner || "No owner"] || []).push(r);
  const ownList = Object.entries(owners).sort((a, b) => (a[0] === "No owner") - (b[0] === "No owner") || b[1].length - a[1].length || a[0].localeCompare(b[0]));
  const topOwners = ownList.slice(0, 10);
  const ownCard = card("Open work by owner", topOwners.length ? hbars(topOwners.map(([o, l]) => ({ label: o, total: l.length,
      segs: o === "No owner" ? [{ k: "miss", n: l.length, tip: l.length + " with no owner" }] : segsOf(l),
      onclick: () => set({ tab: "issues", owner: o === "No owner" ? NONE : o }), title: "List " + o + "'s open work" })))
    : h("div", { class: "empty", text: "Nothing open matches these filters." }),
    ownList.length ? (() => { const named = ownList.filter(([o]) => o !== "No owner"); const none = owners["No owner"];
      return (named.length ? named[0][0] + " carries the most (" + named[0][1].length + "). " : "") +
        (none ? plural(none.length, "item has", "items have") + " nobody accountable." : "Every open item has an owner.") +
        (ownList.length > 10 ? " Top ten shown." : ""); })() : null,
    h("div", { class: "legend" }, OPEN_H.map(k => h("span", null, h("span", { class: "sw c-" + k }), HEALTH[k].label)),
      h("span", null, h("span", { class: "sw c-miss" }), "No owner")));

  // completeness trend
  const cw = W.filter(w => w.complete != null);
  const compCard = cw.length > 1 ? card("Completeness week by week", line(cw.map(w => ({ label: fmt(w.date), v: w.complete, n: w.undated })),
      { unit: "%", max: 100, tip: p => "Week of " + p.label + ": " + p.v + "% of open items complete, " + p.n + " undated" }),
      "Share of open items with an owner, a date, a link and their required fields: " + cw[0].complete + "% on " + fmt(cw[0].date) +
      ", " + cw[cw.length - 1].complete + "% now. " + (cw[cw.length - 1].complete >= cw[0].complete ? "The white space is shrinking." : "The white space is growing."))
    : card("Completeness week by week", h("div", { class: "empty", text: "Builds from the snapshot each run saves." }));

  $("p-overview").replaceChildren(band,
    h("div", { class: "grid2" }, card("Capability health", capBody, capTake, healthLegend()), card("Pipeline by Jira status", pipe, pipeTake)),
    h("div", { class: "grid2" }, dueCard, missCard),
    h("div", { class: "grid2" }, ownCard, statusCard),
    h("div", { class: "section-h" }, h("h2", { text: "Trends" }), h("p", { text: "Whole portfolio, from the weekly snapshots and Jira's created and resolved dates. Filters don't apply." })),
    h("div", { class: "grid2" }, weekCard, compCard),
    h("div", { class: "grid2" }, doneCard, cycleCard));
}

/* ---------- weekly report ---------- */
function reportHtml(rep) {
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const week = fmtY(rep.weekOf);
  let out = "<h2>" + esc(META.title) + ": week of " + esc(week) + "</h2><p><b>Overall: " + RAG[rep.overall] + ".</b> " + esc(rep.headline) + "</p><ul>";
  for (const e of rep.elements) out += "<li><b>" + esc(e.name) + ": " + RAG[e.rag] + ".</b> " + esc(e.big) + ". " + esc(e.text) + "</li>";
  out += "</ul>";
  for (const s of rep.sections) {
    out += "<h3>" + esc(s.title) + "</h3>";
    if (s.note) out += "<p><i>" + esc(s.note) + "</i></p>";
    if (!s.groups.length) out += "<p>Nothing this week.</p>";
    for (const g of s.groups) {
      out += "<p><b>" + esc(g.label) + "</b></p><ul>";
      for (const l of g.lines) out += "<li>" + (safe(l.url) ? '<a href="' + esc(l.url) + '">' + esc(l.key) + "</a>" : esc(l.key)) + " " + esc(l.summary) + (l.text ? ": " + esc(l.text) : "") + "</li>";
      out += "</ul>";
    }
  }
  return out;
}
function renderReport() {
  if (!REPORTS.length) { head("Weekly report", "No report yet", "Run the build to produce one."); $("p-report").replaceChildren(); return; }
  const rep = REPORTS.find(r => r.date === S.week) || REPORTS[0];
  const isCurrent = rep === REPORTS[0];
  head("Weekly report", "Week of " + d8(rep.weekOf).toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" }),
    "Computed from Jira on " + fmtY(rep.date) + (rep.baseline ? ", compared with the snapshot from " + fmtY(rep.baseline) : "") +
    ". Every line comes from the record; nobody writes it by hand. Filters don't apply here.");
  const pick = h("select", { id: "r-week", "aria-label": "Report week", onchange: e => set({ week: e.target.value === REPORTS[0].date ? "" : e.target.value }) },
    REPORTS.map((r, i) => h("option", { value: r.date, text: "Week of " + fmtY(r.weekOf) + (i === 0 ? " (current)" : "") })));
  pick.value = rep.date;
  const md = rep.markdown || "";
  const bar = h("div", { class: "toolbar" }, h("label", { for: "r-week", text: "Report" }), pick,
    h("button", { class: "btn", type: "button", onclick: () => copy(md, "Report", reportHtml(rep)), title: "Formatted for Outlook and Teams, with links" , text: "Copy for email or Teams" }),
    h("button", { class: "btn", type: "button", onclick: () => download("weekly-report-" + rep.date + ".md", md, "text/markdown"), text: "Download .md" }),
    h("button", { class: "btn", type: "button", onclick: () => window.print(), text: "Print or save PDF" }),
    !isCurrent ? h("span", { class: "fcount", text: "An earlier week, as it was computed then." }) : null);
  const overall = h("div", { class: "rag overall " + rep.overall },
    h("div", { class: "t" }, glyph(rep.overall), "Overall — " + RAG[rep.overall]), h("p", { text: rep.headline }));
  const elems = h("div", { class: "grid3" }, rep.elements.map(e => h("div", { class: "rag elem " + e.rag },
    h("div", { class: "t" }, glyph(e.rag), e.name + " — " + RAG[e.rag]), h("div", { class: "big", text: e.big }), h("p", { text: e.text }))));
  const secs = rep.sections.map(s => h("section", { class: "rsec", "aria-label": s.title }, h("h3", { text: s.title }),
    s.note ? h("p", { class: "rnote", text: s.note }) : null,
    s.groups.length ? s.groups.map(g => h("div", { class: "rgrp" }, h("h4", { text: g.label }),
      h("ul", null, g.lines.map(l => h("li", null, glyph(l.health in HEALTH ? l.health : "nodate"),
        h("span", null, BY_KEY.has(l.key) ? h("button", { class: "linkish", type: "button", onclick: () => openDrawer(l.key), text: l.key + " · " + l.summary })
          : h("span", { text: l.key + " · " + l.summary }), l.text ? h("span", { class: "what", text: " — " + l.text }) : null))))))
      : h("p", { class: "empty", style: "text-align:left;padding:12px 0 0", text: "Nothing this week." })));
  $("p-report").replaceChildren(bar, overall, elems, ...secs);
}

/* ---------- actions ---------- */
function actionItems() {
  const out = [];
  for (const r of rows({ keepDone: true })) for (const g of r.gaps) {
    if (S.nudged === "hide" && nudged[nid(r, g)]) continue;
    out.push({ r, g });
  }
  return out;
}
function ownerMsg(owner, items) {
  const first = owner && owner !== "No owner" ? owner.split(/\s+/)[0] : "team";
  return "Hi " + first + ",\n\nA few items on the " + META.title + " need your attention:\n\n" +
    items.map(({ r, g }) => "- " + r.key + " " + r.summary + ": " + g.detail + ". " + CHECK[g.code].hint + (safe(r.url) ? " " + r.url : "")).join("\n") +
    "\n\nCan you update these in Jira this week?\n\nThanks";
}
function mailto(owner, items) {
  const email = (ISSUES.find(r => r.owner === owner && r.ownerEmail) || {}).ownerEmail || "";
  const to = /^[^\s@?&#,;<>"]+@[^\s@?&#,;<>"]+$/.test(email) ? email : "";
  let body = ownerMsg(owner, items);
  if (body.length > 1800) body = body.slice(0, 1800) + "\n…(list truncated, see the dashboard)";
  return "mailto:" + to + "?subject=" + encodeURIComponent(META.title + ": items that need your update") + "&body=" + encodeURIComponent(body);
}
function renderActions() {
  head("Actions", "What needs attention", "Everything that's late, stuck, or missing what the board needs to read it. Fix it in Jira and the next pull clears it.");
  const all = actionItems();
  const counts = {};
  for (const it of all) counts[it.g.code] = (counts[it.g.code] || 0) + 1;
  const side = h("nav", { class: "side", "aria-label": "Checks" },
    h("button", { type: "button", "aria-current": String(!S.check), onclick: () => set({ check: "" }) }, h("span", { text: "All actions" }), h("span", { class: "c", text: all.length })),
    [...new Set(CHECKS.map(c => c.group))].map(gname => [h("h4", { text: gname }), CHECKS.filter(c => c.group === gname).map(c =>
      h("button", { type: "button", class: counts[c.code] ? "" : "zero", "aria-current": String(S.check === c.code), title: c.hint,
        onclick: () => set({ check: S.check === c.code ? "" : c.code }) }, h("span", { text: c.label }), h("span", { class: "c", text: counts[c.code] || 0 })))]));
  const items = (S.check ? all.filter(i => i.g.code === S.check) : all)
    .sort((a, b) => HEALTH[shown(a.r)].rank - HEALTH[shown(b.r)].rank || byKey(a.r.key, b.r.key));
  const groups = new Map();
  if (S.group === "owner") for (const it of items) { const o = it.r.owner || "No owner"; if (!groups.has(o)) groups.set(o, []); groups.get(o).push(it); }
  else for (const c of CHECKS) { const l = items.filter(i => i.g.code === c.code); if (l.length) groups.set(c.code, l); }
  const keys = [...groups.keys()];
  if (S.group === "owner") keys.sort((a, b) => (a === "No owner") - (b === "No owner") || groups.get(b).length - groups.get(a).length || a.localeCompare(b));

  const bar = h("div", { class: "toolbar" }, h("label", { text: "Group by" }),
    h("span", { class: "seg", role: "group", "aria-label": "Group by" },
      h("button", { type: "button", "aria-pressed": String(S.group === "check"), onclick: () => set({ group: "check" }), text: "Check" }),
      h("button", { type: "button", "aria-pressed": String(S.group === "owner"), onclick: () => set({ group: "owner" }), text: "Owner" })),
    h("label", { class: "chk", style: "text-transform:none;letter-spacing:0;font-weight:400" },
      h("input", { type: "checkbox", id: "f-nudged", checked: S.nudged === "hide" ? true : null, onchange: e => set({ nudged: e.target.checked ? "hide" : "" }) }), "Hide nudged"),
    h("span", { class: "fcount", text: plural(items.length, "action") + " on " + plural(new Set(items.map(i => i.r.key)).size, "issue") }));

  const list = keys.length ? keys.map(k => {
    const l = groups.get(k), ks = [...new Set(l.map(i => i.r.key))];
    let title, hint, acts;
    if (S.group === "owner") {
      title = k; hint = [...new Set(l.map(i => CHECK[i.g.code].label.toLowerCase()))].join(", ");
      acts = [h("a", { class: "tlink", href: mailto(k, l), text: "Email " + (k === "No owner" ? "draft" : k.split(" ")[0]) }),
        h("button", { class: "tlink", type: "button", onclick: () => copy(ownerMsg(k, l), "Message"), text: "Copy message" }), jiraLink(ks)];
    } else {
      title = CHECK[k].label; hint = CHECK[k].hint;
      acts = [h("button", { class: "tlink", type: "button", title: "Tab-separated, pastes into Excel", onclick: () => copy(l.map(({ r, g }) =>
        [r.key, r.summary, r.owner || "No owner", g.detail, r.url || ""].join("\t")).join("\n"), "List"), text: "Copy list" }), jiraLink(ks)];
    }
    return h("section", { class: "grp", "aria-label": title },
      h("div", { class: "grp-h" }, h("div", null, h("div", { class: "t" }, title, h("span", { class: "n", text: "  " + l.length })), h("div", { class: "hint", text: hint })),
        h("div", { class: "acts" }, acts)),
      l.map(({ r, g }) => { const id = nid(r, g), when = nudged[id];
        return h("div", { class: "item" + (when ? " nudged" : "") }, glyph(shown(r)), keyLink(r),
          h("span", { class: "sm" }, h("button", { class: "linkish", type: "button", title: r.summary, onclick: () => openDrawer(r.key), text: r.summary })),
          h("span", { class: "o" }, S.group === "owner" ? CHECK[g.code].label : (r.owner || miss("No owner"))),
          h("span", { class: "d", text: g.detail }),
          h("span", { class: "nb" }, h("button", { class: "tlink", type: "button", "aria-pressed": String(!!when),
            title: when ? "Nudged " + when + ". Select to clear." : "Note that you've followed up (kept in this browser)",
            onclick: () => { setNudged(id, !when); render(); }, text: when ? "✓ Nudged " + fmt(when) : "Mark nudged" }))); }));
  }) : [h("div", { class: "empty" }, all.length ? "Nothing for this check under these filters." : "No open actions under these filters. ",
      h("button", { class: "tlink", type: "button", "data-reset": "", text: "Reset filters" }))];
  $("p-actions").replaceChildren(h("div", { class: "act" }, side, h("div", null, bar, list)));
}

/* ---------- capabilities ---------- */
const capOpen = new Set();
function capRowsList() {
  return ISSUES.filter(isCap).map(c => {
    const kids = c.children.map(k => BY_KEY.get(k)).filter(Boolean);
    const shownKids = kids.filter(k => (S.done || isOpen(k)) && match(k, { anyHealth: true }) && (!S.health || k.health === S.health));
    return { c, kids, shownKids, show: match(c) || shownKids.length > 0 };
  }).filter(x => x.show && (S.done || isOpen(x.c) || x.c.gaps.length)).sort((a, b) => worstFirst(a.c, b.c));
}
function renderCaps() {
  head("Capabilities", "Capability health", "Each capability is as healthy as its worst open epic. Expand one to see its epics.");
  const list = capRowsList();
  const tb = h("tbody");
  for (const { c, kids, shownKids } of list) {
    const open = capOpen.has(c.key) || S.cap === c.key;
    const nOpen = kids.filter(isOpen).length;
    const mini = h("div", { class: "mini" }, nOpen ? OPEN_H.filter(k => c.childCounts[k]).map(k =>
      h("span", { class: "c-" + k, style: "flex:" + c.childCounts[k], "data-tip": c.childCounts[k] + " " + HEALTH[k].label.toLowerCase() })) : null);
    tb.append(h("tr", { class: "row", onclick: () => openDrawer(c.key) },
      h("td", { class: "nw" }, shownKids.length ? h("button", { class: "tog", type: "button", "aria-expanded": String(open),
        "aria-label": (open ? "Hide" : "Show") + " epics of " + c.key, onclick: e => { e.stopPropagation(); open ? capOpen.delete(c.key) : capOpen.add(c.key); if (S.cap === c.key) S.cap = ""; writeHash(); renderCaps(); },
        text: open ? "▾" : "▸" }) : h("span", { class: "tog", "aria-hidden": "true" }), badge(c.rollup)),
      h("td", null, h("div", { class: "ttl" }, keyLink(c), "  ", c.summary), h("div", { class: "sub" }, c.owner || miss("No owner"), " · " + c.status)),
      h("td", null, kids.length ? [mini, h("div", { class: "sub", text: plural(nOpen, "open epic") + (kids.length > nOpen ? " · " + (kids.length - nOpen) + " done" : "") })] : miss("No epics")),
      h("td", { class: "nw" }, c.due ? [fmt(c.due), h("div", { class: "sub", text: rel(c.daysToDue) })] : isOpen(c) ? miss("No date") : "—"),
      h("td", { class: "num" }, c.gaps.length ? h("span", { "data-tip": c.gaps.map(g => CHECK[g.code].label).join(", "), text: c.gaps.length }) : h("span", { class: "sub", text: "0" }))));
    if (open) for (const k of shownKids.sort(worstFirst)) tb.append(h("tr", { class: "row child", onclick: () => openDrawer(k.key) },
      h("td", { class: "nw", style: "padding-left:32px" }, badge(k.health)),
      h("td", null, h("div", null, keyLink(k), "  ", k.summary), h("div", { class: "sub" }, k.owner || miss("No owner"), " · " + k.status)),
      h("td", { class: "sub", text: (k.reasons || [])[0] || "" }),
      h("td", { class: "nw" }, k.due ? [fmt(k.due), h("div", { class: "sub", text: rel(k.daysToDue) })] : isOpen(k) ? miss("No date") : "—"),
      h("td", { class: "num" }, k.gaps.length ? String(k.gaps.length) : h("span", { class: "sub", text: "0" }))));
  }
  const orphans = ISSUES.filter(r => r.kind === "epic" && !(r.parent && BY_KEY.has(r.parent)) && match(r));
  const tbl = h("div", { class: "scroll" }, h("table", { class: "tbl" },
    h("thead", null, h("tr", null, ["Health", "Capability", "Epics", "Due", "Actions"].map((t, i) => h("th", { scope: "col", class: i === 4 ? "num" : null, text: t })))), tb));
  const orphanBlock = orphans.length && (!S.cap || S.cap === NONE) ? h("div", { style: "margin-top:24px" },
    h("div", { class: "ct" }, h("h2", { text: "Epics not linked to a capability (" + orphans.length + ")" }), jiraLink(orphans.map(o => o.key))),
    h("p", { class: "lede", style: "font-size:13px;margin-bottom:8px", text: "These don't roll up into any capability's health until they're linked." }),
    issueTable(orphans, ["key", "summary", "owner", "status", "health", "due"])) : null;
  $("p-caps").replaceChildren(...[list.length ? tbl : h("div", { class: "empty" }, "No capabilities match these filters. ", h("button", { class: "tlink", type: "button", "data-reset": "", text: "Reset filters" })), orphanBlock].filter(Boolean));
}

/* ---------- issues ---------- */
const COLS = {
  key:     { label: "Key", val: r => r.key, cmp: byKey, cell: r => h("td", { class: "key" }, keyLink(r)) },
  type:    { label: "Type", val: r => r.type, cell: r => h("td", { class: "nw", text: r.type }) },
  summary: { label: "Summary", val: r => r.summary.toLowerCase(), cell: r => h("td", { style: "min-width:220px" }, r.summary) },
  cap:     { label: "Capability", val: r => isCap(r) ? "" : r.parent || "~", cmp: byKey, cell: r => h("td", { class: "nw", title: r.parentSummary || "" },
             isCap(r) ? h("span", { class: "sub", text: "—" }) : r.parent ? r.parent : r.kind === "epic" ? miss("Not linked") : h("span", { class: "sub", text: "—" })) },
  owner:   { label: "Owner", val: r => (r.owner || "~").toLowerCase(), cell: r => h("td", { class: "nw" }, r.owner || miss("No owner")) },
  status:  { label: "Status", val: r => r.status.toLowerCase(), cell: r => h("td", { class: "nw", text: r.status }) },
  health:  { label: "Health", val: r => HEALTH[shown(r)].rank, cell: r => h("td", { class: "nw", "data-tip": (r.reasons || []).join(" · ") }, badge(shown(r))) },
  due:     { label: "Due", val: r => r.due || "9999", cell: r => h("td", { class: "nw" }, r.due ? fmt(r.due) : isOpen(r) ? miss("No date") : h("span", { class: "sub", text: "—" }),
             r.due && isOpen(r) ? h("div", { class: "sub", text: rel(r.daysToDue) }) : null) },
  updated: { label: "Updated", val: r => r.updated || "", cell: r => h("td", { class: "nw" }, r.daysSinceUpdate == null ? "—" : rel(-r.daysSinceUpdate)) },
  actions: { label: "Actions", num: true, val: r => r.gaps.length, cell: r => h("td", { class: "num" },
             r.gaps.length ? h("span", { "data-tip": r.gaps.map(g => CHECK[g.code].label).join(", "), text: r.gaps.length }) : h("span", { class: "sub", text: "0" })) },
};
function issueTable(list, cols, sortable) {
  const thead = h("tr", null, cols.map(id => { const c = COLS[id], on = sortable && S.sort === id;
    return h("th", { scope: "col", class: c.num ? "num" : null, "aria-sort": on ? (S.dir === "desc" ? "descending" : "ascending") : null },
      sortable ? h("button", { type: "button", onclick: () => set({ sort: id, dir: on && S.dir === "asc" ? "desc" : "asc" }) }, c.label,
        h("span", { class: "ar", "aria-hidden": "true", text: on ? (S.dir === "desc" ? "↓" : "↑") : "↕" })) : c.label); }));
  const body = h("tbody", null, list.map(r => h("tr", { class: "row", tabindex: "0", onclick: () => openDrawer(r.key),
    onkeydown: e => { if (e.key === "Enter") openDrawer(r.key); } }, cols.map(id => COLS[id].cell(r)))));
  return h("div", { class: "scroll" }, h("table", { class: "tbl" }, h("thead", null, thead), body));
}
function sorted() {
  const c = COLS[S.sort] || COLS.health, dir = S.dir === "desc" ? -1 : 1;
  return rows().sort((a, b) => {
    const va = c.val(a), vb = c.val(b);
    let x = c.cmp ? c.cmp(String(va), String(vb)) : (va < vb ? -1 : va > vb ? 1 : 0);
    if (x === 0 && S.sort !== "key") x = byKey(a.key, b.key) * dir;
    return x * dir;
  });
}
let limit = 250;
function renderIssues() {
  head("Issues", "Every capability and epic", "Select a column to sort, a row for its detail, or a key to open the ticket in Jira.");
  const list = sorted();
  const bar = h("div", { class: "toolbar", style: "justify-content:flex-end;margin-top:-8px" },
    h("button", { class: "btn", type: "button", onclick: exportCsv, text: "Export CSV" }),
    h("button", { class: "btn", type: "button", onclick: () => copy(location.href, "Link to this view"), text: "Copy link to this view" }));
  $("p-issues").replaceChildren(...[bar, list.length ? issueTable(list.slice(0, limit), ["key", "type", "summary", "cap", "owner", "status", "health", "due", "updated", "actions"], true)
    : h("div", { class: "empty" }, "No issues match these filters. ", h("button", { class: "tlink", type: "button", "data-reset": "", text: "Reset filters" })),
    list.length > limit ? h("div", { class: "more" }, h("button", { class: "btn", type: "button", onclick: () => { limit = Infinity; renderIssues(); }, text: "Show all " + list.length })) : null].filter(Boolean));
}
function csvCell(v) {
  let s = v == null ? "" : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
function exportCsv() {
  const list = sorted();
  const head_ = ["Key", "URL", "Type", "Summary", "Capability", "Capability summary", "Owner", "Jira status", "Health", "Why", "Due", "Days to due", "Last updated", "Days since update", "Actions"];
  const lines = [head_.map(csvCell).join(",")].concat(list.map(r => [r.key, r.url, r.type, r.summary, isCap(r) ? "" : r.parent || "", isCap(r) ? "" : r.parentSummary || "",
    r.owner, r.status, HEALTH[shown(r)].label, (r.reasons || []).join("; "), r.due, r.daysToDue, r.updated, r.daysSinceUpdate,
    r.gaps.map(g => CHECK[g.code].label + ": " + g.detail).join("; ")].map(csvCell).join(",")));
  download((META.title || "portfolio").replace(/[^\w-]+/g, "-").toLowerCase() + "-" + META.today + ".csv", "﻿" + lines.join("\r\n"), "text/csv;charset=utf-8");
  toast("Exported " + plural(list.length, "row"));
}

/* ---------- method ---------- */
function renderMethod() {
  head("Method", "How it's scored", "The rules behind every color and every line of the weekly report, so anyone reading a red can see why it's red.");
  const R = META.rules;
  const li = (...k) => h("li", null, ...k);
  $("p-method").replaceChildren(h("div", { class: "prose" },
    h("h2", { text: "Health" }),
    h("p", { text: "Every open capability and epic gets one of four states from its Jira record. The worst rule that applies wins." }),
    h("ul", null,
      li(badge("red"), " — status is " + (R.redStatuses.join(" or ") || "(none set)") + (R.flaggedField ? ", it's flagged," : "") + " or it's past its due date."),
      li(badge("amber"), " — status is " + (R.amberStatuses.join(" or ") || "(none set)") + ", it's due within " + R.atRiskDays + " days and still in a To Do status, or nobody has updated it in over " + R.staleDays + " days."),
      li(badge("nodate"), " — nothing above applies, but it has no due date. With no date there's nothing to judge its schedule against, so it isn't shown as green."),
      li(badge("green"), " — everything else.")),
    R.ragField ? h("p", { text: "Where the owner sets a RAG field, the worse of reported and computed health is shown, and anything reported healthier than its data is raised as an action." }) : null,
    h("p", { text: "A capability takes the health of its worst open epic, or its own record if that's worse. Its detail panel shows both." }),
    h("h2", { text: "Weekly report" }),
    h("p", { text: "Each run saves a snapshot of the scored portfolio. The report compares this week's snapshot with the one from about a week before: what was completed or added, what went off track or recovered, and which statuses, due dates and owners moved. With no earlier snapshot, it falls back to Jira's created and resolved dates." }),
    h("p", { text: "Three elements are rated. Schedule: red if any capability is off track, amber if any is at risk. Momentum: red if a quarter or more of open work has gone stale, amber if anything has or nothing was completed. Data quality: green when 90% or more of open items carry an owner, a date, a link and their required fields; amber from 75%. Overall takes the worst of the three." }),
    h("h2", { text: "What's not there" }),
    h("p", null, "Missing things are shown, not left blank. In charts they're a hatched fill ", h("span", { class: "sw c-miss", style: "vertical-align:-1px" }),
      "; in tables they're a marker like ", miss("No date"), ". The due-dates chart has a No date column, the Overview's What's missing card shows each field filled against empty, and Time in current status shows what hasn't moved."),
    h("p", { text: "The weekly report pairs what was done with what wasn't: What didn't move sits next to What changed, Coming up lists work with no date alongside work that's due, and What's missing names every open item without an owner, a capability, epics, a description or a required field. “Didn't move” means not started, blocked or on hold for " + (R.stuckWeeks || 3) + "+ weeks, timed from the weekly snapshots (or, for not-started work with no history yet, from its created date)." }),
    h("h2", { text: "Actions" }),
    h("table", { class: "tbl" }, h("thead", null, h("tr", null, h("th", { text: "Check" }), h("th", { text: "Group" }), h("th", { text: "What to do" }))),
      h("tbody", null, CHECKS.map(c => h("tr", null, h("td", { text: c.label }), h("td", { text: c.group }), h("td", { text: c.hint }))))),
    h("p", { text: "“Mark nudged” is kept in this browser only. It doesn't change Jira, and nobody else sees it." }),
    h("h2", { text: "Source" }),
    h("dl", { class: "kv" }, h("dt", { text: "Pulled" }), h("dd", { text: new Date(META.pulledAt).toLocaleString() }),
      h("dt", { text: "Jira" }), h("dd", { text: META.jiraHost || "—" }), h("dt", { text: "Query" }), h("dd", null, h("code", { text: META.jql })),
      h("dt", { text: "Issues" }), h("dd", { text: ISSUES.length }), h("dt", { text: "Weekly snapshots" }), h("dd", { text: (TRENDS.weekly || []).length })),
    h("p", { text: "This page is a snapshot. It holds no credentials and makes no network calls; every action opens Jira or your mail client in the usual way." })));
}

/* ---------- drawer ---------- */
let dKey = null;
function openDrawer(key) {
  const r = BY_KEY.get(key); if (!r) return;
  dKey = key;
  $("d-key").textContent = r.key + " · " + r.type;
  const u = safe(r.url); $("d-open").hidden = $("d-copy").hidden = !u; if (u) $("d-open").href = u;
  const p = r.parent ? BY_KEY.get(r.parent) : null;
  const muted = t => h("span", { class: "sub", text: t });
  const kv = [["Status", r.status + (r.daysInStatus != null ? " (" + (r.statusSinceAtLeast ? "at least " : "") + plural(Math.floor(r.daysInStatus / 7), "week") + ")" : "")],
    ["Owner", r.owner || miss("No owner")],
    [isCap(r) ? "Parent" : "Capability", r.parent ? (p ? h("button", { class: "linkish", style: "color:var(--link)", type: "button", onclick: () => openDrawer(p.key), text: p.key + " " + p.summary }) : r.parent) : r.kind === "epic" ? miss("Not linked") : muted("None")],
    ["Due", r.due ? fmtY(r.due) + (isOpen(r) ? " (" + rel(r.daysToDue) + ")" : "") : isOpen(r) ? miss("No date") : muted("Not set")],
    ["Last updated", r.updated ? fmtY(r.updated) + " (" + rel(-r.daysSinceUpdate) + ")" : "—"],
    ["Created", fmtY(r.created) || "—"]];
  if (r.resolved) kv.push(["Resolved", fmtY(r.resolved)]);
  if (r.rag) kv.push(["Reported RAG", RAG[r.rag]]);
  for (const [l, v] of r.extra || []) kv.push([l, v || miss("Empty")]);
  const body = [h("h2", { id: "d-title", text: r.summary }),
    h("dl", { class: "kv" }, kv.flatMap(([k, v]) => [h("dt", { text: k }), h("dd", null, v)])),
    h("h3", { text: "Health" }),
    h("p", { style: "margin:0 0 6px" }, badge(shown(r)), isCap(r) && r.rollup !== r.health ? h("span", { class: "sub", text: "   own record alone: " + HEALTH[r.health].label }) : null),
    h("ul", null, (r.reasons || []).map(x => h("li", { text: x }))),
    h("h3", { text: "What needs doing" }),
    r.gaps.length ? h("ul", { class: "todo" }, r.gaps.map(g => { const id = nid(r, g), when = nudged[id];
      return h("li", null, h("b", { text: CHECK[g.code].label + ": " + g.detail }), h("span", { text: CHECK[g.code].hint }),
        h("span", null, h("button", { class: "tlink", type: "button", onclick: () => { setNudged(id, !when); render(); openDrawer(r.key); },
          text: when ? "✓ Nudged " + fmt(when) + " (clear)" : "Mark nudged" }))); }))
      : h("p", { class: "sub", text: "Nothing outstanding." })];
  if (isCap(r)) {
    const kids = r.children.map(k => BY_KEY.get(k)).filter(Boolean).sort(worstFirst);
    body.push(h("h3", { text: "Epics (" + kids.length + ")" }), kids.length ? issueTable(kids, ["key", "summary", "health"]) : h("p", { class: "sub", text: "No epics in this pull." }));
  }
  $("d-body").replaceChildren(...body);
  if (!$("drawer").open) $("drawer").showModal();
  $("drawer").scrollTop = 0;
}

/* ---------- filters ---------- */
function opts(sel, all, list, val) {
  sel.replaceChildren(h("option", { value: "", text: all }), ...list.map(([v, l]) => h("option", { value: v, text: l })));
  sel.value = list.some(o => o[0] === val) ? val : "";
  sel.classList.toggle("on", !!sel.value);
}
const OPTS = {};
function initFilters() {
  const owners = [...new Set(ISSUES.map(r => r.owner).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  OPTS.owner = [...owners.map(o => [o, o]), [NONE, "No owner"]];
  OPTS.cap = [...ISSUES.filter(isCap).sort((a, b) => byKey(a.key, b.key)).map(c => [c.key, c.key + " " + c.summary]), [NONE, "Not linked to a capability"]];
  OPTS.health = ["red", "amber", "nodate", "green", "done"].map(k => [k, HEALTH[k].label]);
  OPTS.status = [...new Set(ISSUES.map(r => r.status))].sort().map(s => [s, s]);
  OPTS.type = ["capability", "epic", "other"].filter(k => ISSUES.some(r => r.kind === k)).map(k => [k, KIND[k]]);
  for (const k of ["owner", "cap", "health", "status", "type"]) $("f-" + k).addEventListener("change", e => set({ [k]: e.target.value }));
  let qt; $("f-q").addEventListener("input", e => { clearTimeout(qt); qt = setTimeout(() => set({ q: e.target.value.trim() }), 120); });
  $("f-done").addEventListener("change", e => set({ done: e.target.checked ? "1" : "" }));
  $("f-reset").addEventListener("click", reset);
  document.addEventListener("click", e => { if (e.target.closest("[data-reset]")) reset(); });
}
function reset() { $("f-q").value = ""; set({ q: "", owner: "", cap: "", health: "", status: "", type: "", done: "", check: "" }); }
function syncFilters() {
  opts($("f-owner"), "All owners", OPTS.owner, S.owner); opts($("f-cap"), "All capabilities", OPTS.cap, S.cap);
  opts($("f-health"), "All health", OPTS.health, S.health); opts($("f-status"), "All statuses", OPTS.status, S.status);
  opts($("f-type"), "All types", OPTS.type, S.type);
  if (document.activeElement !== $("f-q")) $("f-q").value = S.q;
  $("f-q").classList.toggle("on", !!S.q);
  $("f-done").checked = !!S.done;
  $("f-reset").disabled = !["q", "owner", "cap", "health", "status", "type", "done", "check"].some(k => S[k]);
  const n = rows().length;
  $("fcount").textContent = n === ISSUES.filter(r => S.done || isOpen(r)).length ? plural(n, S.done ? "issue" : "open issue") : n + " of " + ISSUES.filter(r => S.done || isOpen(r)).length + " match";
}

/* ---------- shell ---------- */
function render() {
  for (const t of TABS) { const on = S.tab === t; $("t-" + t).setAttribute("aria-selected", String(on)); $("t-" + t).tabIndex = on ? 0 : -1; $("p-" + t).hidden = !on; }
  $("filters").hidden = S.tab === "report" || S.tab === "method";
  syncFilters();
  $("n-actions").textContent = actionItems().length;
  ({ overview: renderOverview, report: renderReport, actions: renderActions, caps: renderCaps, issues: renderIssues, method: renderMethod })[S.tab]();
}
function init() {
  document.title = META.title;
  $("m-title").textContent = META.title;
  const pulled = new Date(META.pulledAt);
  $("m-asof").textContent = "Data as of " + pulled.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const hrs = (Date.now() - pulled) / 36e5;
  if (hrs > 24) { $("stale").hidden = false; $("stale-t").textContent = "This snapshot is " + plural(Math.floor(hrs / 24), "day") + " old. Re-run the pull before acting on it."; }
  $("footer").textContent = ISSUES.length + " issues from " + (META.jiraHost || "Jira") + ". A snapshot; Jira is the system of record.";
  const tabs = TABS.map(t => $("t-" + t));
  tabs.forEach((b, i) => {
    b.addEventListener("click", () => { limit = 250; set({ tab: b.dataset.tab }); window.scrollTo(0, 0); });
    b.addEventListener("keydown", e => { const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0; if (!d) return;
      const n = tabs[(i + d + tabs.length) % tabs.length]; n.focus(); n.click(); });
  });
  $("d-close").addEventListener("click", () => $("drawer").close());
  $("drawer").addEventListener("click", e => { if (e.target === $("drawer")) $("drawer").close(); });
  $("d-copy").addEventListener("click", () => { const r = BY_KEY.get(dKey); if (r) copy(r.url, "Link"); });
  document.addEventListener("keydown", e => {
    if (e.key === "/" && !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName) && !$("drawer").open && !$("filters").hidden) { e.preventDefault(); $("f-q").focus(); }
  });
  window.addEventListener("hashchange", () => { readHash(); render(); });
  readHash(); initFilters(); render();
}
init();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
