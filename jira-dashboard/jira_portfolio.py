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
               "created", "description", "parent"]


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
        hit(3, "%s past due (%s)" % (n_days(-r["daysToDue"]), r["due"]))
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
            reasons.append("Due in %s, status %s, updated %s" % (
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
        add("overdue", "%s past due (%s)" % (n_days(-r["daysToDue"]), r["due"]))
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

def build_html(recs, cfg, meta):
    payload = {
        "meta": meta,
        "checks": [c for c in CHECKS if c["code"] not in set(cfg.get("disabled_checks") or [])],
        "issues": recs,
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
        },
    }


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


def sample_issues(today):
    def d(n):
        return (today + dt.timedelta(days=n)).isoformat() if n is not None else None

    cats = {"To Do": "new", "Discovery": "indeterminate", "In Progress": "indeterminate",
            "In Review": "indeterminate", "Blocked": "indeterminate", "On Hold": "indeterminate",
            "Done": "done"}
    out = []

    def issue(key, typ, summary, status, owner, due, updated, parent=None, rag=None,
              flagged=False, desc=True, value="Yes", cap_owner=None):
        f = {
            "summary": summary,
            "issuetype": {"name": typ},
            "status": {"name": status, "statusCategory": {"key": cats[status]}},
            "assignee": {"displayName": owner,
                         "emailAddress": owner.lower().replace(" ", ".") + "@example.com"} if owner else None,
            "duedate": d(due),
            "updated": d(-updated) + "T10:00:00.000+0000",
            "created": d(-updated - 60) + "T10:00:00.000+0000",
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

    C = "Capability"
    issue("AI-1", C, "Customer service virtual assistant", "In Progress", None, 120, 3,
          rag="Green", cap_owner="Dana Whitfield")
    issue("AI-11", "Epic", "Intent model for card disputes", "In Progress", "Priya Nair", 30, 2, "AI-1")
    issue("AI-12", "Epic", "Agent handoff with full context", "In Progress", "Marcus Lee", -9, 5, "AI-1")
    issue("AI-13", "Epic", "Model risk validation package", "To Do", "Priya Nair", 10, 4, "AI-1")
    issue("AI-14", "Epic", "Containment reporting", "Done", "Marcus Lee", -20, 25, "AI-1")

    issue("AI-2", C, "Fraud alert triage copilot", "In Progress", None, 75, 6,
          rag="Green", cap_owner="Sam Okafor")
    issue("AI-21", "Epic", "Alert summarization for investigators", "In Progress", "Lena Ortiz", 21, 1, "AI-2")
    issue("AI-22", "Epic", "Feature store access approval", "Blocked", "Lena Ortiz", 14, 9, "AI-2",
          flagged=True)
    issue("AI-23", "Epic", "Investigator feedback loop", "To Do", None, None, 3, "AI-2")

    issue("AI-3", C, "Credit memo drafting", "Discovery", None, 160, 4,
          rag="Amber", cap_owner="Jordan Price", value=None)
    issue("AI-31", "Epic", "Underwriter workflow discovery", "In Progress", "Alex Romero", 40, 4, "AI-3")
    issue("AI-32", "Epic", "Fair lending review plan", "To Do", "Alex Romero", 60, 2, "AI-3")

    issue("AI-4", C, "Collections call summarization", "In Progress", None, 45, 30,
          rag="Green", cap_owner="Chris Tan")
    issue("AI-41", "Epic", "Call transcript pipeline", "In Progress", "Chris Tan", 12, 28, "AI-4")
    issue("AI-42", "Epic", "Summary QA sampling", "In Review", "Riley Moss", 5, 3, "AI-4")

    issue("AI-5", C, "Marketing content compliance review", "On Hold", None, 200, 10,
          cap_owner=None, desc=False)

    issue("AI-6", C, "Developer productivity assistant", "Done", None, -30, 12,
          rag="Green", cap_owner="Dana Whitfield")
    issue("AI-61", "Epic", "IDE rollout to 400 engineers", "Done", "Marcus Lee", -35, 40, "AI-6")
    issue("AI-62", "Epic", "Usage telemetry dashboard", "In Progress", "Riley Moss", 15, 6, "AI-6")

    issue("AI-7", C, "Complaint classification", "In Progress", None, 90, 1,
          rag="Green", cap_owner="Sam Okafor")
    issue("AI-71", "Epic", "Regulatory category taxonomy", "Done", "Lena Ortiz", -5, 4, "AI-7")
    issue("AI-72", "Epic", "Classifier v2 retrain", "In Progress", "Priya Nair", 35, 2, "AI-7")
    issue("AI-73", "Epic", "UDAAP escalation routing", "In Progress", "Jordan Price", 50, 7, "AI-7")

    issue("AI-90", "Epic", "Prompt library governance", "In Progress", "Alex Romero", 25, 8)
    issue("AI-91", "Epic", "Vendor LLM contract review", "To Do", None, None, 22, desc=False)
    return out


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description="Build a Jira portfolio dashboard.")
    ap.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="config JSON (default: %(default)s)")
    ap.add_argument("--init-config", nargs="?", const=DEFAULT_CONFIG_PATH, metavar="PATH",
                    help="write a starter config and exit")
    ap.add_argument("--discover", action="store_true", help="list issue types, statuses and fields, then exit")
    ap.add_argument("--sample", action="store_true", help="build from invented sample data")
    ap.add_argument("--from-json", metavar="FILE", help="build from saved Jira search results")
    ap.add_argument("--save-raw", metavar="FILE", help="also save the raw Jira pull (contains Jira data)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output HTML (default: %(default)s)")
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
        cfg = load_config(None)
        cfg = deep_merge(cfg, SAMPLE_CONFIG)
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
    page = build_html(recs, cfg, build_meta(cfg, today, source))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)

    caps = sum(1 for r in recs if r["kind"] == "capability")
    epics = sum(1 for r in recs if r["kind"] == "epic")
    red = sum(1 for r in recs if r["kind"] == "capability" and r["rollup"] == "red")
    actions = sum(len(r["gaps"]) for r in recs)
    print("Wrote %s: %d capabilities (%d off track), %d epics, %d open actions"
          % (a.out, caps, red, epics, actions))
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
  :root {
    color-scheme: light;
    --page: #ffffff;
    --panel: #f5f6f7;
    --raised: #ffffff;
    --ink: #16181d;
    --ink-2: #4a5160;
    --ink-3: #646c7a;
    --hairline: #e2e4e8;
    --rule: #c9cdd4;
    --field: #8a91a0;
    --hover: rgba(22,24,29,0.04);
    --brand: __BRAND__;
    --on-brand: #ffffff;
    --link: #0f56a5;
    --focus: #0f56a5;

    --good: #0ca30c;
    --warning: #fab219;
    --critical: #d03b3b;
    --neutral: #8a91a0;
    --done: #4a5160;
    --glyph-on-warning: #16181d;

    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif;
    --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    --fs-xs: 11px; --fs-sm: 12.5px; --fs-md: 13.5px; --fs-lg: 15px; --fs-xl: 20px; --fs-2xl: 28px;
    --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 20px; --s6: 24px; --s7: 32px;
    --r: 4px;
    --shadow: 0 1px 2px rgba(0,0,0,0.06), 0 4px 16px rgba(0,0,0,0.06);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --page: #121418; --panel: #1a1d23; --raised: #20242b;
      --ink: #eceef2; --ink-2: #b5bbc6; --ink-3: #8f97a4;
      --hairline: #2c3038; --rule: #3a3f49; --field: #6c7482;
      --hover: rgba(255,255,255,0.05);
      --link: #7cb4ff; --focus: #7cb4ff;
      --neutral: #6c7482; --done: #8f97a4;
      --shadow: 0 1px 2px rgba(0,0,0,0.4), 0 4px 16px rgba(0,0,0,0.3);
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page: #121418; --panel: #1a1d23; --raised: #20242b;
    --ink: #eceef2; --ink-2: #b5bbc6; --ink-3: #8f97a4;
    --hairline: #2c3038; --rule: #3a3f49; --field: #6c7482;
    --hover: rgba(255,255,255,0.05);
    --link: #7cb4ff; --focus: #7cb4ff;
    --neutral: #6c7482; --done: #8f97a4;
    --shadow: 0 1px 2px rgba(0,0,0,0.4), 0 4px 16px rgba(0,0,0,0.3);
  }

  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  html, body { margin: 0; }
  body { background: var(--page); color: var(--ink); font: var(--fs-md)/1.45 var(--sans); }
  a { color: var(--link); }
  button, input, select { font: inherit; color: inherit; }
  :focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

  /* ---------- top bar ---------- */
  .top { background: var(--brand); color: var(--on-brand); }
  .top-in { max-width: 1440px; margin: 0 auto; padding: var(--s3) var(--s4); display: flex; gap: var(--s4);
            align-items: center; flex-wrap: wrap; }
  .top h1 { font-size: var(--fs-lg); margin: 0; font-weight: 650; letter-spacing: 0.01em; }
  .top .asof { font-size: var(--fs-sm); opacity: 0.85; }
  .top .spacer { flex: 1; }
  .top .tbtn { background: rgba(255,255,255,0.14); color: var(--on-brand); border: 1px solid rgba(255,255,255,0.35);
               border-radius: var(--r); padding: var(--s1) var(--s3); cursor: pointer; font-size: var(--fs-sm); }
  .top .tbtn:hover { background: rgba(255,255,255,0.24); }
  .banner { background: #fff4d6; color: #4a3500; border-bottom: 1px solid #f1d27a; }
  .banner .in { max-width: 1440px; margin: 0 auto; padding: var(--s2) var(--s4); font-size: var(--fs-sm); }

  .wrap { max-width: 1440px; margin: 0 auto; padding: 0 var(--s4) var(--s7); }

  /* ---------- tabs ---------- */
  .tabs { display: flex; gap: var(--s1); border-bottom: 1px solid var(--hairline); margin: var(--s4) 0 0;
          overflow-x: auto; }
  .tab { background: none; border: 0; border-bottom: 2px solid transparent; padding: var(--s2) var(--s3);
         cursor: pointer; color: var(--ink-2); font-weight: 550; white-space: nowrap; }
  .tab[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--brand); }
  .tab .n { color: var(--ink-3); font-weight: 400; margin-left: var(--s1); font-variant-numeric: tabular-nums; }

  /* ---------- filters ---------- */
  .filters { display: flex; flex-wrap: wrap; gap: var(--s2); align-items: center; padding: var(--s3) 0;
             position: sticky; top: 0; background: var(--page); z-index: 5; border-bottom: 1px solid var(--hairline); }
  .filters input[type=search], .filters select { height: 32px; border: 1px solid var(--field); border-radius: var(--r);
             background: var(--raised); padding: 0 var(--s2); max-width: 100%; }
  .filters input[type=search] { width: 260px; }
  .filters select { min-width: 0; max-width: 200px; }
  .filters select.on, .filters input.on { border-color: var(--brand); box-shadow: inset 0 0 0 1px var(--brand); }
  .chk { display: inline-flex; gap: var(--s1); align-items: center; font-size: var(--fs-sm); color: var(--ink-2);
         white-space: nowrap; cursor: pointer; }
  .btn { height: 32px; border: 1px solid var(--field); background: var(--raised); border-radius: var(--r);
         padding: 0 var(--s3); cursor: pointer; white-space: nowrap; display: inline-flex; align-items: center;
         gap: var(--s1); text-decoration: none; color: var(--ink); font-size: var(--fs-sm); }
  .btn:hover { background: var(--hover); }
  .btn.sm { height: 26px; padding: 0 var(--s2); font-size: var(--fs-xs); }
  .btn.primary { background: var(--brand); color: var(--on-brand); border-color: var(--brand); }
  .btn.primary:hover { filter: brightness(1.1); }
  .btn[disabled] { opacity: 0.5; cursor: default; }
  .linkbtn { background: none; border: 0; padding: 0; color: var(--link); cursor: pointer; text-align: left;
             text-decoration: underline; text-decoration-color: transparent; }
  .linkbtn:hover { text-decoration-color: currentColor; }
  .fcount { margin-left: auto; color: var(--ink-3); font-size: var(--fs-sm); font-variant-numeric: tabular-nums; }

  /* ---------- KPI + health ---------- */
  .overview { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: var(--s4); margin: var(--s4) 0; }
  .kpis { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--s2); }
  .kpi { background: var(--panel); border: 1px solid transparent; border-radius: var(--r); padding: var(--s3);
         text-align: left; cursor: pointer; display: block; width: 100%; }
  .kpi:hover { border-color: var(--rule); }
  .kpi.on { border-color: var(--brand); }
  .kpi .lab { font-size: var(--fs-xs); color: var(--ink-2); display: flex; gap: var(--s1); align-items: center; }
  .kpi .val { font-size: var(--fs-2xl); font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.2; }
  .kpi .sub { font-size: var(--fs-xs); color: var(--ink-3); }
  .card { background: var(--panel); border-radius: var(--r); padding: var(--s4); }
  .card h2 { font-size: var(--fs-md); margin: 0 0 var(--s3); font-weight: 650; }
  .hrow { display: grid; grid-template-columns: 100px minmax(0,1fr) 40px; gap: var(--s3); align-items: center;
          margin-bottom: var(--s3); }
  .hrow .lab { font-size: var(--fs-sm); color: var(--ink-2); }
  .hrow .tot { font-size: var(--fs-sm); color: var(--ink-3); text-align: right; font-variant-numeric: tabular-nums; }
  .bar { display: flex; gap: 2px; height: 24px; }
  .bar.thin { height: 10px; }
  .seg { border: 0; padding: 0; min-width: 4px; border-radius: 2px; cursor: pointer; color: #fff; font-size: var(--fs-xs);
         font-weight: 650; font-variant-numeric: tabular-nums; overflow: hidden; }
  .seg:hover { filter: brightness(1.1); }
  .seg.empty { background: var(--hairline); cursor: default; width: 100%; }
  .bg-red { background: var(--critical); } .bg-amber { background: var(--warning); color: var(--glyph-on-warning); }
  .bg-green { background: var(--good); } .bg-nodate { background: var(--neutral); } .bg-done { background: var(--done); }
  .legend { display: flex; flex-wrap: wrap; gap: var(--s3); font-size: var(--fs-xs); color: var(--ink-2); }

  .dot { display: inline-grid; place-items: center; width: 16px; height: 16px; border-radius: 50%; color: #fff;
         font-size: 10px; font-weight: 800; line-height: 1; flex: none; }
  .dot.amber { color: var(--glyph-on-warning); }
  .hbadge { display: inline-flex; align-items: center; gap: var(--s1); white-space: nowrap; }

  /* ---------- command center ---------- */
  .ccbar { display: flex; gap: var(--s3); align-items: center; flex-wrap: wrap; margin: var(--s4) 0 var(--s2); }
  .seg-ctl { display: inline-flex; border: 1px solid var(--field); border-radius: var(--r); overflow: hidden; }
  .seg-ctl button { border: 0; background: var(--raised); padding: var(--s1) var(--s3); cursor: pointer;
                    font-size: var(--fs-sm); }
  .seg-ctl button[aria-pressed="true"] { background: var(--brand); color: var(--on-brand); }
  .checks { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: var(--s2);
            margin-bottom: var(--s4); }
  .checks h3 { grid-column: 1 / -1; font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: 0.06em;
               color: var(--ink-3); margin: var(--s2) 0 0; font-weight: 650; }
  .chip { display: flex; justify-content: space-between; align-items: center; gap: var(--s2); text-align: left;
          border: 1px solid var(--hairline); background: var(--raised); border-radius: var(--r); padding: var(--s2) var(--s3);
          cursor: pointer; }
  .chip:hover { border-color: var(--rule); }
  .chip[aria-pressed="true"] { border-color: var(--brand); box-shadow: inset 0 0 0 1px var(--brand); }
  .chip .c { font-weight: 650; font-variant-numeric: tabular-nums; }
  .chip.zero { color: var(--ink-3); }
  .chip.zero .c { font-weight: 400; }

  .group { border: 1px solid var(--hairline); border-radius: var(--r); margin-bottom: var(--s3); background: var(--raised); }
  .ghead { display: flex; gap: var(--s3); align-items: flex-start; padding: var(--s3) var(--s4); border-bottom: 1px solid var(--hairline);
           flex-wrap: wrap; }
  .ghead .t { font-weight: 650; }
  .ghead .t .n { color: var(--ink-3); font-weight: 400; margin-left: var(--s1); }
  .ghead .hint { color: var(--ink-2); font-size: var(--fs-sm); }
  .ghead .acts { margin-left: auto; display: flex; gap: var(--s2); flex-wrap: wrap; }
  .items { list-style: none; margin: 0; padding: 0; }
  .item { display: grid; grid-template-columns: 20px 84px minmax(0, 2.2fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.6fr) 120px;
          gap: var(--s3); align-items: center; padding: var(--s2) var(--s4); border-top: 1px solid var(--hairline); font-size: var(--fs-sm); }
  .item:first-child { border-top: 0; }
  .item:hover { background: var(--hover); }
  .item.nudged { opacity: 0.6; }
  .item .sum { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .item .meta { color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .item .det { color: var(--ink); }
  .key { font-family: var(--mono); font-size: var(--fs-sm); white-space: nowrap; }
  .muted { color: var(--ink-3); }
  .empty { padding: var(--s7) var(--s4); text-align: center; color: var(--ink-2); border: 1px dashed var(--rule); border-radius: var(--r); }

  /* ---------- capabilities ---------- */
  .caps { display: grid; gap: var(--s3); margin-top: var(--s4); }
  .cap { border: 1px solid var(--hairline); border-radius: var(--r); background: var(--raised); }
  .cap-h { display: grid; grid-template-columns: 112px 64px minmax(0, 1fr) auto; gap: var(--s3); align-items: center;
           padding: var(--s3) var(--s4); }
  .cap-h .sum { font-weight: 600; font-size: var(--fs-lg); }
  .cap-h .sub { font-size: var(--fs-sm); color: var(--ink-2); grid-column: 3 / 4; }
  .cap-h .acts { display: flex; gap: var(--s2); grid-row: 1 / span 2; grid-column: 4; }
  .cap-mid { padding: 0 var(--s4) var(--s3); display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--s3);
             align-items: center; }
  .cap-mid .why { font-size: var(--fs-sm); color: var(--ink-2); }
  .cap details > summary { padding: var(--s2) var(--s4); border-top: 1px solid var(--hairline); cursor: pointer;
                           font-size: var(--fs-sm); color: var(--ink-2); }

  /* ---------- table ---------- */
  .tablewrap { overflow-x: auto; border: 1px solid var(--hairline); border-radius: var(--r); margin-top: var(--s4);
               background: var(--raised); }
  table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
  th, td { text-align: left; padding: var(--s2) var(--s3); border-bottom: 1px solid var(--hairline); vertical-align: middle; }
  th { background: var(--panel); position: sticky; top: 0; font-weight: 600; white-space: nowrap; z-index: 1; }
  th button { background: none; border: 0; padding: 0; cursor: pointer; font-weight: 600; display: inline-flex; gap: var(--s1); }
  th .arr { color: var(--ink-3); width: 10px; display: inline-block; }
  th[aria-sort] .arr { color: var(--ink); }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: var(--hover); }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  td.sumcell { min-width: 240px; }
  td.nw { white-space: nowrap; }
  .nested th { position: static; }
  .more { display: flex; justify-content: center; padding: var(--s3); }

  .pill { display: inline-block; border: 1px solid var(--rule); border-radius: 999px; padding: 0 var(--s2);
          font-size: var(--fs-xs); color: var(--ink-2); white-space: nowrap; }
  .pill.todo { border-color: var(--rule); }
  .pill.inprogress { border-color: var(--link); color: var(--link); }
  .pill.done { border-color: var(--good); color: var(--ink-2); }
  .acount { display: inline-block; min-width: 20px; text-align: center; border-radius: 999px; background: var(--panel);
            font-weight: 650; padding: 0 var(--s1); }
  .acount.z { background: none; color: var(--ink-3); font-weight: 400; }

  /* ---------- drawer ---------- */
  dialog.drawer { margin: 0 0 0 auto; height: 100%; max-height: 100%; width: min(560px, 100vw); border: 0; padding: 0;
                  background: var(--page); color: var(--ink); box-shadow: var(--shadow); }
  dialog.drawer::backdrop { background: rgba(0,0,0,0.35); }
  .dh { display: flex; gap: var(--s2); align-items: center; padding: var(--s3) var(--s4); border-bottom: 1px solid var(--hairline);
        position: sticky; top: 0; background: var(--page); }
  .dh .x { margin-left: auto; }
  .db { padding: var(--s4); }
  .db h2 { font-size: var(--fs-xl); margin: 0 0 var(--s3); line-height: 1.3; }
  .db h3 { font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-3); margin: var(--s5) 0 var(--s2); }
  dl.kv { display: grid; grid-template-columns: 140px minmax(0,1fr); gap: var(--s2) var(--s3); margin: 0; font-size: var(--fs-sm); }
  dl.kv dt { color: var(--ink-2); }
  dl.kv dd { margin: 0; }
  ul.reasons { margin: 0; padding-left: var(--s5); font-size: var(--fs-sm); }
  ul.acts { list-style: none; margin: 0; padding: 0; }
  ul.acts li { border: 1px solid var(--hairline); border-radius: var(--r); padding: var(--s2) var(--s3); margin-bottom: var(--s2);
               font-size: var(--fs-sm); display: grid; gap: var(--s1); }
  ul.acts .h { color: var(--ink-2); }

  /* ---------- method ---------- */
  .method { max-width: 820px; margin-top: var(--s4); }
  .method h2 { font-size: var(--fs-lg); margin: var(--s6) 0 var(--s2); }
  .method p, .method li { color: var(--ink-2); }
  .method table { margin-top: var(--s2); }
  .method code { font-family: var(--mono); font-size: var(--fs-sm); background: var(--panel); padding: 0 var(--s1); border-radius: 2px; }

  .toast { position: fixed; bottom: var(--s5); left: 50%; transform: translateX(-50%); background: var(--ink); color: var(--page);
           padding: var(--s2) var(--s4); border-radius: var(--r); font-size: var(--fs-sm); box-shadow: var(--shadow);
           opacity: 0; pointer-events: none; transition: opacity .15s; z-index: 50; }
  .toast.show { opacity: 1; }
  footer { color: var(--ink-3); font-size: var(--fs-xs); margin-top: var(--s7); border-top: 1px solid var(--hairline); padding-top: var(--s3); }

  @media (max-width: 1000px) {
    .overview { grid-template-columns: 1fr; }
    .item { grid-template-columns: 20px 84px minmax(0, 1fr) 110px; }
    .item .meta.o, .item .meta.s { display: none; }
    .item .det { grid-column: 3 / 4; white-space: normal; }
  }
  @media (max-width: 640px) {
    .wrap, .top-in { padding-left: var(--s4); padding-right: var(--s4); }
    .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .filters { position: static; }
    .filters input[type=search] { width: 100%; }
    .filters select { flex: 1 1 140px; max-width: none; }
    .item { grid-template-columns: 20px minmax(0, 1fr); }
    .item > :nth-child(n+3) { grid-column: 2; }
    .item .key { grid-column: 2; }
    .cap-h { grid-template-columns: auto minmax(0, 1fr); }
    .cap-h .sub, .cap-h .acts { grid-column: 1 / -1; grid-row: auto; }
    .hrow { grid-template-columns: 80px minmax(0,1fr) 32px; }
    dl.kv { grid-template-columns: 110px minmax(0,1fr); }
  }
  @media print {
    .filters, .tabs, .top .tbtn, .acts, .btn, .ccbar .seg-ctl, .banner { display: none !important; }
    .top { background: none; color: #000; border-bottom: 2px solid #000; }
    body { background: #fff; color: #000; }
    .group, .cap, .card { break-inside: avoid; }
    details { display: block; }
  }
</style>
</head>
<body>
<header class="top">
  <div class="top-in">
    <h1 id="title"></h1>
    <span class="asof" id="asof"></span>
    <span class="spacer"></span>
    <button class="tbtn" id="btn-csv" type="button" title="Download the filtered issues as CSV">Export CSV</button>
    <button class="tbtn" id="btn-link" type="button" title="Copy a link to this exact view">Copy view link</button>
    <button class="tbtn" id="btn-print" type="button">Print</button>
  </div>
</header>
<div class="banner" id="banner" hidden><div class="in" id="banner-text"></div></div>

<main class="wrap">
  <nav class="tabs" role="tablist" aria-label="Views">
    <button class="tab" role="tab" id="tab-command" aria-controls="panel-command" data-tab="command">Command center<span class="n" id="n-command"></span></button>
    <button class="tab" role="tab" id="tab-caps" aria-controls="panel-caps" data-tab="caps">Capabilities<span class="n" id="n-caps"></span></button>
    <button class="tab" role="tab" id="tab-issues" aria-controls="panel-issues" data-tab="issues">All issues<span class="n" id="n-issues"></span></button>
    <button class="tab" role="tab" id="tab-method" aria-controls="panel-method" data-tab="method">How it's scored</button>
  </nav>

  <div class="filters" id="filters" role="search" aria-label="Filters">
    <input type="search" id="f-q" placeholder="Search key, summary, owner  ( / )" aria-label="Search">
    <select id="f-owner" aria-label="Owner"></select>
    <select id="f-cap" aria-label="Capability"></select>
    <select id="f-health" aria-label="Health"></select>
    <select id="f-status" aria-label="Jira status"></select>
    <select id="f-type" aria-label="Issue type"></select>
    <label class="chk"><input type="checkbox" id="f-done"> Include done</label>
    <button class="btn" id="f-reset" type="button">Reset</button>
    <span class="fcount" id="fcount" aria-live="polite"></span>
  </div>

  <section class="overview" aria-label="Portfolio health">
    <div class="kpis" id="kpis"></div>
    <div class="card">
      <h2>Portfolio health</h2>
      <div id="healthbars"></div>
      <div class="legend" id="legend"></div>
    </div>
  </section>

  <section id="panel-command" role="tabpanel" aria-labelledby="tab-command" hidden>
    <div class="ccbar">
      <span class="seg-ctl" role="group" aria-label="Group by">
        <button type="button" data-group="check">By check</button>
        <button type="button" data-group="owner">By owner</button>
      </span>
      <label class="chk"><input type="checkbox" id="f-nudged"> Hide nudged</label>
      <span class="fcount" id="cc-count"></span>
    </div>
    <div class="checks" id="checks"></div>
    <div id="groups"></div>
  </section>

  <section id="panel-caps" role="tabpanel" aria-labelledby="tab-caps" hidden>
    <div class="caps" id="caps"></div>
  </section>

  <section id="panel-issues" role="tabpanel" aria-labelledby="tab-issues" hidden>
    <div class="tablewrap">
      <table id="table">
        <thead><tr id="thead"></tr></thead>
        <tbody id="tbody"></tbody>
      </table>
      <div class="more" id="more" hidden></div>
    </div>
    <div class="empty" id="table-empty" hidden>No issues match these filters. <button class="linkbtn" type="button" data-reset>Reset filters</button></div>
  </section>

  <section id="panel-method" role="tabpanel" aria-labelledby="tab-method" hidden>
    <div class="method" id="method"></div>
  </section>

  <footer id="footer"></footer>
</main>

<dialog class="drawer" id="drawer" aria-labelledby="d-title">
  <div class="dh">
    <span class="key" id="d-key"></span>
    <a class="btn primary sm" id="d-open" target="_blank" rel="noopener noreferrer">Open in Jira ↗</a>
    <button class="btn sm" id="d-copy" type="button">Copy link</button>
    <button class="btn sm x" id="d-close" type="button" aria-label="Close">Close ✕</button>
  </div>
  <div class="db" id="d-body"></div>
</dialog>
<div class="toast" id="toast" role="status" aria-live="polite"></div>

<script id="portfolio-data" type="application/json">__DATA__</script>
<script>
"use strict";
(function () {
const DATA = JSON.parse(document.getElementById("portfolio-data").textContent);
const META = DATA.meta, CHECKS = DATA.checks, ISSUES = DATA.issues;
const CHECK = Object.fromEntries(CHECKS.map(c => [c.code, c]));
const BY_KEY = new Map(ISSUES.map(r => [r.key, r]));
const JIRA = /^https?:\/\//i.test(META.jiraBase || "") ? META.jiraBase.replace(/\/+$/, "") : "";

const HEALTH = {
  red:    { label: "Off track",    glyph: "✕", rank: 0 },
  amber:  { label: "At risk",      glyph: "!", rank: 1 },
  nodate: { label: "Not assessed", glyph: "?", rank: 2 },
  green:  { label: "On track",     glyph: "✓", rank: 3 },
  done:   { label: "Done",         glyph: "•", rank: 4 },
};
const H_ORDER = ["red", "amber", "nodate", "green", "done"];
const KIND_LABEL = { capability: "Capability", epic: "Epic", other: "Other" };
const NONE = "__none";
const ROW_PAGE = 250;

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
  for (const c of kids.flat()) if (c != null && c !== false) n.append(c instanceof Node ? c : String(c));
  return n;
}
const $ = id => document.getElementById(id);
const plural = (n, one, many) => n + " " + (n === 1 ? one : (many || one + "s"));
const isCap = r => r.kind === "capability";
const shown = r => isCap(r) ? r.rollup : r.health;
const capKeyOf = r => isCap(r) ? r.key : (r.parent || NONE);
const safe = u => /^https?:\/\//i.test(u || "") ? u : null;
const fmtDate = s => {
  if (!s) return "";
  const d = new Date(s + "T00:00:00");
  return isNaN(d) ? s : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
};
const relDays = n => n == null ? "" : n === 0 ? "today" : n > 0 ? "in " + plural(n, "day") : plural(-n, "day") + " ago";

function dot(health) {
  const d = h("span", { class: "dot bg-" + health + " " + health, "aria-hidden": "true", text: HEALTH[health].glyph });
  return d;
}
function badge(health) {
  return h("span", { class: "hbadge" }, dot(health), h("span", { text: HEALTH[health].label }));
}
function keyLink(r, cls) {
  const url = safe(r.url);
  if (!url) return h("span", { class: "key " + (cls || ""), text: r.key });
  return h("a", { class: "key " + (cls || ""), href: url, target: "_blank", rel: "noopener noreferrer",
    title: "Open " + r.key + " in Jira", onclick: e => e.stopPropagation(), text: r.key });
}
function jqlUrl(keys) {
  if (!JIRA || !keys.length) return null;
  const jql = "key in (" + keys.slice(0, 200).join(",") + ") ORDER BY key";
  return JIRA + "/issues/?jql=" + encodeURIComponent(jql);
}
function jiraBulkBtn(keys, label) {
  const url = jqlUrl(keys);
  if (!url) return null;
  return h("a", { class: "btn sm", href: url, target: "_blank", rel: "noopener noreferrer",
    title: "Opens these " + keys.length + " issues in Jira's issue navigator, where you can bulk edit them",
    text: (label || "Open " + keys.length + " in Jira") + " ↗" });
}
function naturalKey(a, b) {
  const pa = /^(.*?)-(\d+)$/.exec(a), pb = /^(.*?)-(\d+)$/.exec(b);
  if (pa && pb && pa[1] === pb[1]) return Number(pa[2]) - Number(pb[2]);
  return a.localeCompare(b);
}

let toastTimer;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
}
async function copy(text, what) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = h("textarea", { style: "position:fixed;opacity:0" });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e2) { ok = false; }
    ta.remove();
    if (!ok) { toast("Couldn't reach the clipboard"); return; }
  }
  toast((what || "Copied") + " to clipboard");
}

/* ---------- nudge tracking (per viewer, this browser only) ---------- */
const NUDGE_KEY = "jira-portfolio:nudged:" + (META.jiraHost || "local");
let nudged = {};
try { nudged = JSON.parse(localStorage.getItem(NUDGE_KEY) || "{}") || {}; } catch (e) { nudged = {}; }
const nudgeId = (r, g) => r.key + "|" + g.code;
function setNudged(id, on) {
  if (on) nudged[id] = new Date().toISOString().slice(0, 10); else delete nudged[id];
  try { localStorage.setItem(NUDGE_KEY, JSON.stringify(nudged)); } catch (e) { /* storage blocked: lasts this session */ }
}

/* ---------- state, in the URL hash so a view can be bookmarked or shared ---------- */
const DEFAULTS = { tab: "command", q: "", owner: "", cap: "", health: "", status: "", type: "", done: "",
  group: "check", check: "", nudged: "", sort: "health", dir: "asc" };
const state = Object.assign({}, DEFAULTS);
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const k of Object.keys(DEFAULTS)) state[k] = p.has(k) ? p.get(k) : DEFAULTS[k];
  if (!["command", "caps", "issues", "method"].includes(state.tab)) state.tab = "command";
}
function writeHash() {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) if (v !== DEFAULTS[k]) p.set(k, v);
  const s = p.toString();
  history.replaceState(null, "", s ? "#" + s : location.pathname + location.search);
}
function set(patch) {
  Object.assign(state, patch);
  writeHash();
  render();
}

/* ---------- filtering ---------- */
function matches(r, opts) {
  opts = opts || {};
  if (!state.done && !opts.keepDone && r.statusCat === "done") return false;
  if (state.owner && (r.owner || NONE) !== state.owner) return false;
  if (state.cap && capKeyOf(r) !== state.cap) return false;
  if (!opts.ignoreHealth && state.health && shown(r) !== state.health) return false;
  if (state.status && r.status !== state.status) return false;
  if (state.type && r.kind !== state.type) return false;
  if (state.q) {
    const hay = (r.key + " " + r.summary + " " + r.owner + " " + r.status + " " + (r.parentSummary || "")).toLowerCase();
    for (const term of state.q.toLowerCase().split(/\s+/).filter(Boolean)) if (!hay.includes(term)) return false;
  }
  return true;
}
const filtered = opts => ISSUES.filter(r => matches(r, opts));

/* ---------- filter controls ---------- */
function fillSelect(sel, allLabel, options, value) {
  sel.replaceChildren(h("option", { value: "", text: allLabel }),
    ...options.map(([v, label]) => h("option", { value: v, text: label })));
  sel.value = options.some(o => o[0] === value) ? value : "";
  sel.classList.toggle("on", !!sel.value);
}
function initFilters() {
  const owners = [...new Set(ISSUES.map(r => r.owner).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const caps = ISSUES.filter(isCap).sort((a, b) => naturalKey(a.key, b.key));
  const statuses = [...new Set(ISSUES.map(r => r.status))].sort();
  const kinds = [...new Set(ISSUES.map(r => r.kind))];
  $("f-owner").dataset.opts = JSON.stringify([...owners.map(o => [o, o]), [NONE, "No owner"]]);
  $("f-cap").dataset.opts = JSON.stringify([...caps.map(c => [c.key, c.key + "  " + c.summary]), [NONE, "Not linked to a capability"]]);
  $("f-health").dataset.opts = JSON.stringify(H_ORDER.map(k => [k, HEALTH[k].label]));
  $("f-status").dataset.opts = JSON.stringify(statuses.map(s => [s, s]));
  $("f-type").dataset.opts = JSON.stringify(["capability", "epic", "other"].filter(k => kinds.includes(k)).map(k => [k, KIND_LABEL[k]]));

  const bind = (id, key) => $(id).addEventListener("change", e => set({ [key]: e.target.value }));
  bind("f-owner", "owner"); bind("f-cap", "cap"); bind("f-health", "health"); bind("f-status", "status"); bind("f-type", "type");
  let qTimer;
  $("f-q").addEventListener("input", e => { clearTimeout(qTimer); qTimer = setTimeout(() => set({ q: e.target.value.trim() }), 120); });
  $("f-done").addEventListener("change", e => set({ done: e.target.checked ? "1" : "" }));
  $("f-nudged").addEventListener("change", e => set({ nudged: e.target.checked ? "hide" : "" }));
  $("f-reset").addEventListener("click", resetFilters);
  document.addEventListener("click", e => { if (e.target.closest("[data-reset]")) resetFilters(); });
  document.querySelectorAll("[data-group]").forEach(b => b.addEventListener("click", () => set({ group: b.dataset.group })));
}
function resetFilters() {
  set({ q: "", owner: "", cap: "", health: "", status: "", type: "", done: "", check: "" });
  $("f-q").value = "";
}
function syncFilters() {
  const pairs = [["f-owner", "All owners", "owner"], ["f-cap", "All capabilities", "cap"], ["f-health", "All health", "health"],
                 ["f-status", "All statuses", "status"], ["f-type", "All types", "type"]];
  for (const [id, label, key] of pairs) fillSelect($(id), label, JSON.parse($(id).dataset.opts), state[key]);
  if (document.activeElement !== $("f-q")) $("f-q").value = state.q;
  $("f-q").classList.toggle("on", !!state.q);
  $("f-done").checked = !!state.done;
  $("f-nudged").checked = state.nudged === "hide";
  document.querySelectorAll("[data-group]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.group === state.group)));
  const active = ["q", "owner", "cap", "health", "status", "type"].filter(k => state[k]).length;
  $("f-reset").disabled = !active && !state.done && !state.check;
}

/* ---------- overview ---------- */
function renderOverview() {
  const rows = filtered({ ignoreHealth: true });
  const open = rows.filter(r => r.statusCat !== "done");
  const caps = open.filter(isCap), epics = open.filter(r => r.kind === "epic");
  const count = (list, hk) => list.filter(r => shown(r) === hk).length;
  const actions = ccItems().length;
  const tiles = [
    { lab: "Open capabilities", val: caps.length, sub: plural(count(caps, "red"), "off track", "off track"), go: { tab: "caps" } },
    { lab: "Open epics", val: epics.length, sub: plural(count(epics, "red"), "off track", "off track"), go: { tab: "issues", type: "epic" } },
    { lab: "Open actions", val: actions, sub: "in the command center", go: { tab: "command" } },
    ...["red", "amber", "nodate"].map(k => ({ lab: HEALTH[k].label, h: k, val: count(open, k),
      sub: plural(count(caps, k), "capability", "capabilities") + " · " + plural(count(epics, k), "epic") })),
  ];
  $("kpis").replaceChildren(...tiles.map(t => h("button", {
    type: "button", class: "kpi" + (t.h && state.health === t.h ? " on" : ""),
    "aria-pressed": t.h ? String(state.health === t.h) : null,
    title: t.h ? "Filter to " + HEALTH[t.h].label : null,
    onclick: () => t.h ? set({ health: state.health === t.h ? "" : t.h }) : set(t.go),
  }, h("div", { class: "lab" }, t.h ? dot(t.h) : null, t.lab), h("div", { class: "val", text: t.val }), h("div", { class: "sub", text: t.sub }))));

  const bars = [["Capabilities", rows.filter(isCap), "capability"], ["Epics", rows.filter(r => r.kind === "epic"), "epic"]];
  $("healthbars").replaceChildren(...bars.map(([label, list, kind]) => {
    const total = list.length;
    const bar = h("div", { class: "bar", role: "img",
      "aria-label": label + ": " + H_ORDER.map(k => count(list, k) + " " + HEALTH[k].label).join(", ") });
    if (!total) bar.append(h("span", { class: "muted", style: "font-size:var(--fs-xs)", text: "None under these filters" }));
    for (const k of H_ORDER) {
      const n = count(list, k);
      if (!n) continue;
      bar.append(h("button", { type: "button", class: "seg bg-" + k, style: "flex:" + n,
        title: n + " " + label.toLowerCase() + " " + HEALTH[k].label.toLowerCase() + ". Click to list them.",
        onclick: () => set({ tab: "issues", type: kind, health: k, done: k === "done" ? "1" : state.done }),
        text: n / total > 0.06 ? n : "" }));
    }
    return h("div", { class: "hrow" }, h("span", { class: "lab", text: label }), bar, h("span", { class: "tot", text: total }));
  }));
  $("legend").replaceChildren(...H_ORDER.filter(k => k !== "done" || state.done).map(k => h("span", { class: "hbadge" }, dot(k), HEALTH[k].label)));
}

/* ---------- command center ---------- */
function ccItems() {
  const out = [];
  for (const r of filtered({ keepDone: true })) for (const g of r.gaps) {
    if (state.nudged === "hide" && nudged[nudgeId(r, g)]) continue;
    out.push({ r, g });
  }
  return out;
}
function itemRow(it) {
  const { r, g } = it;
  const id = nudgeId(r, g);
  const when = nudged[id];
  const row = h("li", { class: "item" + (when ? " nudged" : "") },
    dot(shown(r)),
    keyLink(r),
    h("button", { type: "button", class: "linkbtn sum", title: r.summary, onclick: () => openDrawer(r.key), text: r.summary }),
    h("span", { class: "meta o", title: "Owner", text: r.owner || "No owner" }),
    h("span", { class: "meta s", text: KIND_LABEL[r.kind] + " · " + r.status }),
    h("span", { class: "det", text: g.detail }),
    h("button", { type: "button", class: "btn sm", "aria-pressed": String(!!when),
      title: when ? "Nudged " + when + ". Click to clear." : "Mark that you've followed up on this",
      onclick: () => { setNudged(id, !when); render(); },
      text: when ? "✓ Nudged " + fmtDate(when) : "Mark nudged" }));
  return row;
}
function ownerMessage(owner, items) {
  const first = owner && owner !== "No owner" ? owner.split(/\s+/)[0] : "team";
  const lines = items.map(({ r, g }) => "- " + r.key + " " + r.summary + ": " + g.detail + ". " + CHECK[g.code].hint +
    (safe(r.url) ? " " + r.url : ""));
  return "Hi " + first + ",\n\nA few items on the " + META.title + " need your attention:\n\n" + lines.join("\n") +
    "\n\nCan you update these in Jira this week?\n\nThanks";
}
function mailto(owner, items) {
  const email = (ISSUES.find(r => r.owner === owner && r.ownerEmail) || {}).ownerEmail || "";
  let body = ownerMessage(owner, items);
  if (body.length > 1800) body = body.slice(0, 1800) + "\n…(list truncated, see the dashboard)";
  const to = /^[^\s@?&#,;<>"]+@[^\s@?&#,;<>"]+$/.test(email) ? email : "";
  return "mailto:" + to + "?subject=" + encodeURIComponent(META.title + ": items that need your update") +
    "&body=" + encodeURIComponent(body);
}
function renderCommand() {
  const all = ccItems();
  const counts = {};
  for (const it of all) counts[it.g.code] = (counts[it.g.code] || 0) + 1;
  const groupsOf = [...new Set(CHECKS.map(c => c.group))];
  const chips = [];
  for (const grp of groupsOf) {
    chips.push(h("h3", { text: grp }));
    for (const c of CHECKS.filter(c => c.group === grp)) {
      const n = counts[c.code] || 0;
      chips.push(h("button", { type: "button", class: "chip" + (n ? "" : " zero"), "aria-pressed": String(state.check === c.code),
        title: c.hint, onclick: () => set({ check: state.check === c.code ? "" : c.code }) },
        h("span", { text: c.label }), h("span", { class: "c", text: n })));
    }
  }
  $("checks").replaceChildren(...chips);

  const items = state.check ? all.filter(it => it.g.code === state.check) : all;
  items.sort((a, b) => HEALTH[shown(a.r)].rank - HEALTH[shown(b.r)].rank || naturalKey(a.r.key, b.r.key));
  $("cc-count").textContent = plural(items.length, "action") + " · " + plural(new Set(items.map(i => i.r.key)).size, "issue");

  const groups = new Map();
  if (state.group === "owner") {
    for (const it of items) {
      const o = it.r.owner || "No owner";
      if (!groups.has(o)) groups.set(o, []);
      groups.get(o).push(it);
    }
  } else {
    for (const c of CHECKS) {
      const list = items.filter(it => it.g.code === c.code);
      if (list.length) groups.set(c.code, list);
    }
  }
  let order = [...groups.keys()];
  if (state.group === "owner") order.sort((a, b) => (a === "No owner") - (b === "No owner") || groups.get(b).length - groups.get(a).length || a.localeCompare(b));

  if (!order.length) {
    $("groups").replaceChildren(h("div", { class: "empty" },
      all.length ? "Nothing for this check under the current filters. " : "No open actions under the current filters. ",
      h("button", { class: "linkbtn", type: "button", "data-reset": "", text: "Reset filters" })));
    return;
  }
  $("groups").replaceChildren(...order.map(k => {
    const list = groups.get(k);
    const keys = [...new Set(list.map(i => i.r.key))];
    let title, hint, acts;
    if (state.group === "owner") {
      title = k;
      hint = plural(keys.length, "issue") + ", " + [...new Set(list.map(i => CHECK[i.g.code].label.toLowerCase()))].join(", ");
      acts = [
        h("a", { class: "btn sm", href: mailto(k, list), title: "Opens a drafted email in your mail client", text: "Email owner" }),
        h("button", { class: "btn sm", type: "button", title: "A message you can paste into Teams or Slack",
          onclick: () => copy(ownerMessage(k, list), "Message"), text: "Copy message" }),
        jiraBulkBtn(keys),
      ];
    } else {
      const c = CHECK[k];
      title = c.label;
      hint = c.hint;
      acts = [
        h("button", { class: "btn sm", type: "button", onclick: () => copy(list.map(({ r, g }) =>
          r.key + "\t" + r.summary + "\t" + (r.owner || "No owner") + "\t" + g.detail + (safe(r.url) ? "\t" + r.url : "")).join("\n"), "List"),
          title: "Tab-separated, pastes into Excel", text: "Copy list" }),
        jiraBulkBtn(keys),
      ];
    }
    return h("section", { class: "group", "aria-label": title },
      h("div", { class: "ghead" },
        h("div", null, h("div", { class: "t" }, title, h("span", { class: "n", text: "(" + list.length + ")" })), h("div", { class: "hint", text: hint })),
        h("div", { class: "acts" }, ...acts)),
      h("ul", { class: "items" }, ...list.map(itemRow)));
  }));
}

/* ---------- capabilities ---------- */
function capRows() {
  const showDone = !!state.done;
  const childOk = r => matches(r, { ignoreHealth: true });
  const rows = ISSUES.filter(isCap).map(c => {
    const kids = c.children.map(k => BY_KEY.get(k)).filter(Boolean);
    const kidsShown = kids.filter(k => (showDone || k.statusCat !== "done") && childOk(k) && (!state.health || k.health === state.health));
    const selfOk = matches(c);
    return { c, kids, kidsShown, show: selfOk || kidsShown.length > 0 };
  }).filter(x => x.show && (showDone || x.c.statusCat !== "done" || x.c.gaps.length));
  rows.sort((a, b) => HEALTH[a.c.rollup].rank - HEALTH[b.c.rollup].rank || naturalKey(a.c.key, b.c.key));
  return rows;
}
function renderCaps() {
  const rows = capRows();
  const cards = rows.map(({ c, kids, kidsShown }) => capCard(c, kids, kidsShown));

  const orphans = ISSUES.filter(r => r.kind === "epic" && !(r.parent && BY_KEY.has(r.parent)) && matches(r));
  if (orphans.length && (!state.cap || state.cap === NONE || orphans.some(o => o.parent === state.cap))) {
    cards.push(h("article", { class: "cap" },
      h("div", { class: "cap-h" }, h("span", null, ""), h("span", { class: "muted", text: "—" }),
        h("div", { class: "sum", text: "Epics not linked to a capability" }),
        h("div", { class: "acts" }, jiraBulkBtn(orphans.map(o => o.key)))),
      h("div", { class: "cap-mid" }, h("div", { class: "why", text: "These won't roll up into any capability's health until they are linked." })),
      epicTable(orphans)));
  }
  $("caps").replaceChildren(...(cards.length ? cards : [h("div", { class: "empty" }, "No capabilities match these filters. ",
    h("button", { class: "linkbtn", type: "button", "data-reset": "", text: "Reset filters" }))]));
}
function capCard(c, kids, kidsShown) {
  const open = kids.filter(k => k.statusCat !== "done").length;
  const bar = h("div", { class: "bar thin", role: "img",
    "aria-label": H_ORDER.filter(k => c.childCounts[k]).map(k => c.childCounts[k] + " " + HEALTH[k].label).join(", ") || "No epics" });
  for (const k of H_ORDER) if (c.childCounts[k]) bar.append(h("span", { class: "seg bg-" + k, style: "flex:" + c.childCounts[k] + ";cursor:default",
    title: c.childCounts[k] + " " + HEALTH[k].label }));
  const sub = [c.owner ? "Owner: " + c.owner : "No owner", c.status, c.due ? "Due " + fmtDate(c.due) : "No due date",
    plural(kids.length, "epic") + (kids.length ? " (" + open + " open)" : "")].join("  ·  ");
  const mix = H_ORDER.filter(k => c.childCounts[k]).map(k => c.childCounts[k] + " " + HEALTH[k].label.toLowerCase()).join(", ");
  const card = h("article", { class: "cap", "aria-label": c.key + " " + c.summary },
    h("div", { class: "cap-h" },
      badge(c.rollup), keyLink(c),
      h("button", { type: "button", class: "linkbtn sum", style: "color:var(--ink)", onclick: () => openDrawer(c.key), text: c.summary }),
      h("div", { class: "acts" },
        h("button", { class: "btn sm", type: "button", onclick: () => set({ tab: "issues", cap: c.key }), text: "List" }),
        jiraBulkBtn([c.key, ...kids.map(k => k.key)], "Open in Jira")),
      h("div", { class: "sub", text: sub })),
    h("div", { class: "cap-mid" },
      h("div", { class: "why", text: (c.reasons || []).join(" · ") + (mix ? "  —  epics: " + mix : "") }),
      h("span", { class: "muted", style: "font-size:var(--fs-xs)", text: c.gaps.length ? plural(c.gaps.length, "action") : "" })),
    h("div", { style: "padding:0 var(--s4) var(--s3)" }, kids.length ? bar
      : h("span", { class: "muted", style: "font-size:var(--fs-xs)", text: "No epics linked yet" })));
  if (kidsShown.length) {
    const det = h("details", null, h("summary", null, kidsShown.length === kids.length ? "Show " + plural(kids.length, "epic")
      : "Show " + kidsShown.length + " of " + plural(kids.length, "epic")), epicTable(kidsShown));
    if (state.cap === c.key || capOpen.has(c.key)) det.open = true;
    det.addEventListener("toggle", () => det.open ? capOpen.add(c.key) : capOpen.delete(c.key));
    card.append(det);
  }
  return card;
}
const capOpen = new Set();
function epicTable(list, compact) {
  list = list.slice().sort((a, b) => HEALTH[a.health].rank - HEALTH[b.health].rank || naturalKey(a.key, b.key));
  const cols = compact
    ? [["Key", r => h("td", { class: "nw" }, keyLink(r))],
       ["Summary", r => h("td", null, r.summary, h("div", { class: "muted", text: (r.owner || "No owner") + " · " + r.status }))],
       ["Health", r => h("td", { class: "nw" }, badge(r.health))]]
    : [["Key", r => h("td", { class: "nw" }, keyLink(r))], ["Summary", r => h("td", { class: "sumcell", text: r.summary })],
       ["Owner", r => h("td", { text: r.owner || "—" })], ["Status", r => h("td", null, h("span", { class: "pill " + r.statusCat, text: r.status }))],
       ["Health", r => h("td", { class: "nw" }, badge(r.health))], ["Due", r => h("td", { class: "nw", text: fmtDate(r.due) || "—" })],
       ["Actions", r => h("td", null, actCount(r))]];
  return h("div", { style: "overflow-x:auto" }, h("table", { class: "nested" },
    h("thead", null, h("tr", null, ...cols.map(([t]) => h("th", { scope: "col", text: t })))),
    h("tbody", null, ...list.map(r => h("tr", { tabindex: "0", onclick: () => openDrawer(r.key), onkeydown: e => { if (e.key === "Enter") openDrawer(r.key); } },
      ...cols.map(([, cell]) => cell(r)))))));
}
function actCount(r) {
  const n = r.gaps.length;
  return h("span", { class: "acount" + (n ? "" : " z"), title: r.gaps.map(g => CHECK[g.code] ? CHECK[g.code].label : g.code).join(", "), text: n });
}

/* ---------- all issues ---------- */
const COLS = [
  { id: "key", label: "Key", val: r => r.key, cmp: naturalKey, cell: r => h("td", { class: "nw" }, keyLink(r)) },
  { id: "type", label: "Type", val: r => KIND_LABEL[r.kind] || r.type, cell: r => h("td", { class: "nw", text: r.type }) },
  { id: "summary", label: "Summary", val: r => r.summary.toLowerCase(), cell: r => h("td", { class: "sumcell", text: r.summary }) },
  { id: "cap", label: "Capability", val: r => isCap(r) ? "" : (r.parent || "~"), cmp: naturalKey,
    cell: r => h("td", { class: "nw", title: r.parentSummary || "" }, isCap(r) ? h("span", { class: "muted", text: "—" })
      : r.parent ? (BY_KEY.has(r.parent) ? h("button", { class: "linkbtn key", type: "button", onclick: e => { e.stopPropagation(); openDrawer(r.parent); }, text: r.parent }) : h("span", { class: "key", text: r.parent }))
      : h("span", { class: "muted", text: "None" })) },
  { id: "owner", label: "Owner", val: r => (r.owner || "~").toLowerCase(), cell: r => h("td", { class: "nw", text: r.owner || "—" }) },
  { id: "status", label: "Status", val: r => r.status.toLowerCase(), cell: r => h("td", { class: "nw" }, h("span", { class: "pill " + r.statusCat, text: r.status })) },
  { id: "health", label: "Health", val: r => HEALTH[shown(r)].rank, cell: r => h("td", { class: "nw", title: (r.reasons || []).join("\n") }, badge(shown(r))) },
  { id: "due", label: "Due", val: r => r.due || "9999", cell: r => h("td", { class: "nw", title: relDays(r.daysToDue) }, fmtDate(r.due) || h("span", { class: "muted", text: "—" })) },
  { id: "updated", label: "Updated", val: r => r.updated || "", cell: r => h("td", { class: "nw", title: fmtDate(r.updated) }, r.daysSinceUpdate == null ? "—" : relDays(-r.daysSinceUpdate)) },
  { id: "actions", label: "Actions", val: r => r.gaps.length, num: true, cell: r => h("td", { class: "num" }, actCount(r)) },
];
let rowLimit = ROW_PAGE;
function sortedRows() {
  const col = COLS.find(c => c.id === state.sort) || COLS[6];
  const dir = state.dir === "desc" ? -1 : 1;
  const rows = filtered();
  rows.sort((a, b) => {
    const va = col.val(a), vb = col.val(b);
    let c = col.cmp ? col.cmp(String(va), String(vb)) : (va < vb ? -1 : va > vb ? 1 : 0);
    if (c === 0 && col.id !== "key") c = naturalKey(a.key, b.key) * dir;
    return c * dir;
  });
  return rows;
}
function renderIssues() {
  $("thead").replaceChildren(...COLS.map(c => {
    const on = state.sort === c.id;
    return h("th", { scope: "col", "aria-sort": on ? (state.dir === "desc" ? "descending" : "ascending") : null },
      h("button", { type: "button", onclick: () => set({ sort: c.id, dir: on && state.dir === "asc" ? "desc" : "asc" }) },
        c.label, h("span", { class: "arr", "aria-hidden": "true", text: on ? (state.dir === "desc" ? "▼" : "▲") : "↕" })));
  }));
  const rows = sortedRows();
  $("table-empty").hidden = rows.length > 0;
  $("table").hidden = rows.length === 0;
  $("tbody").replaceChildren(...rows.slice(0, rowLimit).map(r => h("tr", {
    tabindex: "0", onclick: () => openDrawer(r.key), onkeydown: e => { if (e.key === "Enter") openDrawer(r.key); },
  }, ...COLS.map(c => c.cell(r)))));
  const more = $("more");
  more.hidden = rows.length <= rowLimit;
  more.replaceChildren(h("button", { class: "btn", type: "button", onclick: () => { rowLimit = Infinity; renderIssues(); },
    text: "Show all " + rows.length + " (" + (rows.length - rowLimit) + " more)" }));
}

/* ---------- drawer ---------- */
let drawerKey = null;
function openDrawer(key) {
  const r = BY_KEY.get(key);
  if (!r) return;
  drawerKey = key;
  const dlg = $("drawer");
  $("d-key").textContent = r.key;
  const url = safe(r.url);
  $("d-open").hidden = !url;
  $("d-copy").hidden = !url;
  if (url) $("d-open").href = url;
  const parent = r.parent ? BY_KEY.get(r.parent) : null;
  const kv = [
    ["Type", r.type], ["Jira status", h("span", { class: "pill " + r.statusCat, text: r.status })],
    ["Owner", r.owner || h("span", { class: "muted", text: "Not set" })],
    [isCap(r) ? "Parent" : "Capability", r.parent ? (parent
      ? h("button", { class: "linkbtn", type: "button", onclick: () => openDrawer(parent.key), text: parent.key + "  " + parent.summary })
      : r.parent + (r.parentSummary ? "  " + r.parentSummary : "")) : h("span", { class: "muted", text: "None" })],
    ["Due", r.due ? fmtDate(r.due) + "  (" + relDays(r.daysToDue) + ")" : h("span", { class: "muted", text: "Not set" })],
    ["Last updated", r.updated ? fmtDate(r.updated) + "  (" + relDays(-r.daysSinceUpdate) + ")" : "—"],
    ["Created", fmtDate(r.created) || "—"],
  ];
  if (r.rag) kv.push(["Reported RAG", r.rag[0].toUpperCase() + r.rag.slice(1)]);
  for (const [label, val] of r.extra || []) kv.push([label, val || h("span", { class: "muted", text: "—" })]);

  const body = [
    h("h2", { id: "d-title", text: r.summary }),
    h("dl", { class: "kv" }, ...kv.flatMap(([k, v]) => [h("dt", { text: k }), h("dd", null, v)])),
    h("h3", { text: "Health" }),
    h("p", { style: "margin:0 0 var(--s2)" }, badge(shown(r)), isCap(r) && r.rollup !== r.health ? h("span", { class: "muted", text: "  (own status alone: " + HEALTH[r.health].label + ")" }) : null),
    h("ul", { class: "reasons" }, ...(r.reasons || []).map(x => h("li", { text: x }))),
    h("h3", { text: r.gaps.length ? "What needs doing (" + r.gaps.length + ")" : "What needs doing" }),
    r.gaps.length ? h("ul", { class: "acts" }, ...r.gaps.map(g => {
      const id = nudgeId(r, g), when = nudged[id];
      return h("li", null, h("strong", { text: (CHECK[g.code] || { label: g.code }).label + ": " + g.detail }),
        h("span", { class: "h", text: (CHECK[g.code] || {}).hint || "" }),
        h("span", null, h("button", { class: "btn sm", type: "button", onclick: () => { setNudged(id, !when); render(); openDrawer(r.key); },
          text: when ? "✓ Nudged " + fmtDate(when) + " (clear)" : "Mark nudged" })));
    })) : h("p", { class: "muted", text: "Nothing outstanding." }),
  ];
  if (isCap(r)) {
    const kids = r.children.map(k => BY_KEY.get(k)).filter(Boolean);
    body.push(h("h3", { text: "Epics (" + kids.length + ")" }));
    body.push(kids.length ? epicTable(kids, true) : h("p", { class: "muted", text: "No epics in this pull." }));
  }
  if (url) body.push(h("p", { style: "margin-top:var(--s5)" }, h("a", { class: "btn primary", href: url, target: "_blank", rel: "noopener noreferrer", text: "Edit " + r.key + " in Jira ↗" })));
  $("d-body").replaceChildren(...body);
  if (!dlg.open) dlg.showModal();
  $("d-body").scrollTop = 0;
}
function initDrawer() {
  const dlg = $("drawer");
  $("d-close").addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener("close", () => { drawerKey = null; });
  $("d-copy").addEventListener("click", () => { const r = BY_KEY.get(drawerKey); if (r) copy(r.url, "Link"); });
}

/* ---------- method ---------- */
function renderMethod() {
  const R = META.rules;
  const list = items => h("ul", null, ...items.map(x => h("li", null, x)));
  const tbl = h("table", null, h("thead", null, h("tr", null, h("th", { text: "Check" }), h("th", { text: "Group" }), h("th", { text: "What to do" }))),
    h("tbody", null, ...CHECKS.map(c => h("tr", { style: "cursor:default" }, h("td", { text: c.label }), h("td", { text: c.group }), h("td", { text: c.hint })))));
  $("method").replaceChildren(
    h("h2", { text: "Health" }),
    h("p", { text: "Every open capability and epic gets one of four health states, scored from its Jira record when the data was pulled. The worst rule that applies wins." }),
    list([
      h("span", null, badge("red"), " if its status is " + (R.redStatuses.join(" or ") || "(none configured)") + (R.flaggedField ? ", it is flagged," : "") + " or it is past its due date."),
      h("span", null, badge("amber"), " if its status is " + (R.amberStatuses.join(" or ") || "(none configured)") + ", it is due within " + R.atRiskDays + " days and still in a To Do status, or nobody has updated it in more than " + R.staleDays + " days."),
      h("span", null, badge("nodate"), " if none of the above applies but it has no due date. Without a date there is nothing to judge schedule against, so it is not shown as green."),
      h("span", null, badge("green"), " otherwise."),
    ]),
    R.ragField ? h("p", { text: "Where the owner has set a RAG field, the worse of the reported and the computed health is shown, and any item reported healthier than its data is raised in the command center." }) : null,
    h("p", { text: "A capability's health rolls up: it is as healthy as its worst open epic, or its own record, whichever is worse. Its detail panel shows both." }),
    h("h2", { text: "Command center checks" }),
    tbl,
    h("p", { text: "“Mark nudged” is kept in this browser only. It does not change Jira, and other people won't see it." }),
    h("h2", { text: "Source" }),
    h("dl", { class: "kv" },
      h("dt", { text: "Pulled" }), h("dd", { text: new Date(META.pulledAt).toLocaleString() }),
      h("dt", { text: "Scored as of" }), h("dd", { text: fmtDate(META.today) }),
      h("dt", { text: "Jira" }), h("dd", { text: META.jiraHost || "(none)" }),
      h("dt", { text: "Query" }), h("dd", null, h("code", { text: META.jql })),
      h("dt", { text: "Issues" }), h("dd", { text: ISSUES.length })),
    h("p", { text: "This page is a snapshot. It holds no credentials and makes no network calls; every action opens Jira or your mail client in the normal way. Re-run the pull for current data." }));
}

/* ---------- CSV ---------- */
function csvCell(v) {
  let s = v == null ? "" : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;  // keep spreadsheet formulas from executing
  return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
function exportCsv() {
  const rows = sortedRows();
  const head = ["Key", "URL", "Type", "Summary", "Capability", "Capability summary", "Owner", "Jira status", "Health",
    "Why", "Due", "Days to due", "Last updated", "Days since update", "Actions"];
  const lines = [head.map(csvCell).join(",")].concat(rows.map(r => [
    r.key, r.url, r.type, r.summary, isCap(r) ? "" : r.parent || "", isCap(r) ? "" : r.parentSummary || "", r.owner, r.status,
    HEALTH[shown(r)].label, (r.reasons || []).join("; "), r.due, r.daysToDue, r.updated, r.daysSinceUpdate,
    r.gaps.map(g => (CHECK[g.code] || { label: g.code }).label + ": " + g.detail).join("; "),
  ].map(csvCell).join(",")));
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = h("a", { href: URL.createObjectURL(blob), download: (META.title || "portfolio").replace(/[^\w-]+/g, "-").toLowerCase() + "-" + META.today + ".csv" });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  toast("Exported " + plural(rows.length, "row"));
}

/* ---------- shell ---------- */
function renderHeader() {
  document.title = META.title;
  $("title").textContent = META.title;
  const pulled = new Date(META.pulledAt);
  $("asof").textContent = (META.source === "sample" ? "Sample data · " : "") + "Data as of " + pulled.toLocaleString(undefined,
    { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + (META.jiraHost ? " · " + META.jiraHost : "");
  const hours = (Date.now() - pulled.getTime()) / 36e5;
  if (hours > 24) {
    $("banner").hidden = false;
    $("banner-text").textContent = "This snapshot is " + plural(Math.floor(hours / 24), "day") +
      " old. Health and staleness were scored on " + fmtDate(META.today) + ". Re-run the pull before acting on it.";
  }
  $("footer").textContent = ISSUES.length + " issues · " + (META.jql || "") + " · Snapshot only; Jira is the system of record.";
}
function render() {
  syncFilters();
  for (const t of ["command", "caps", "issues", "method"]) {
    const on = state.tab === t;
    $("tab-" + t).setAttribute("aria-selected", String(on));
    $("tab-" + t).tabIndex = on ? 0 : -1;
    $("panel-" + t).hidden = !on;
  }
  const nonMethod = state.tab !== "method";
  $("filters").hidden = !nonMethod;
  document.querySelector(".overview").hidden = !nonMethod;
  renderOverview();
  const ccN = ccItems().length;
  $("n-command").textContent = ccN;
  $("n-issues").textContent = filtered().length;
  $("fcount").textContent = plural(filtered().length, "issue") + " of " + ISSUES.length;
  if (state.tab === "command") renderCommand();
  $("n-caps").textContent = capRows().length;
  if (state.tab === "caps") renderCaps();
  if (state.tab === "issues") renderIssues();
  if (state.tab === "method") renderMethod();
}
function initTabs() {
  const tabs = [...document.querySelectorAll("[data-tab]")];
  tabs.forEach((b, i) => {
    b.addEventListener("click", () => { rowLimit = ROW_PAGE; set({ tab: b.dataset.tab }); });
    b.addEventListener("keydown", e => {
      const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!d) return;
      const n = tabs[(i + d + tabs.length) % tabs.length];
      n.focus(); n.click();
    });
  });
}

readHash();
renderHeader();
initFilters();
initTabs();
initDrawer();
$("btn-csv").addEventListener("click", exportCsv);
$("btn-print").addEventListener("click", () => window.print());
$("btn-link").addEventListener("click", () => copy(location.href, "View link"));
window.addEventListener("hashchange", () => { readHash(); render(); });
document.addEventListener("keydown", e => {
  if (e.key === "/" && !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName) && !$("drawer").open) {
    e.preventDefault();
    $("f-q").focus();
  }
});
render();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
