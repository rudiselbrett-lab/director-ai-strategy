#!/usr/bin/env python3
"""Write Jira search responses built from the sample portfolio.

Shaped like Jira Cloud REST v3 actually answers: option objects for selects,
user objects for people, Atlassian Document Format for rich text, a status
with its category, and a changelog. Two files:

  jira_clean.json  maps back to the sample exactly (the round-trip test)
  jira_messy.json  the same with what real instances do: an unmapped status,
                   a second "Story Points" field, a select option nobody
                   mapped, a missing target date, a dollar figure as text
  jira_generic.json  the sample as a Jira with no portfolio custom fields:
                   generic To Do / In Progress / Done statuses, components,
                   reporter, due date, fix versions, issue links and the
                   labels convention, read by the default JIRA_MAP

jira_clean and jira_messy are read with docs/jira_map.custom-fields.json.

    python3 tests/make_jira_fixture.py
"""
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_portfolio as bp  # noqa: E402

OUT = ROOT / "tests" / "fixtures"

NAMES = {
    "summary": "Summary", "status": "Status", "assignee": "Assignee", "created": "Created",
    "updated": "Updated", "duedate": "Due date", "resolution": "Resolution",
    "resolutiondate": "Resolved", "labels": "Labels", "description": "Description",
    "comment": "Comment",
    "customfield_10101": "Consumer Bank function", "customfield_10102": "Business Sponsor",
    "customfield_10103": "WSJF", "customfield_10104": "Estimated Annual Value",
    "customfield_10016": "Story Points", "customfield_10105": "Impact",
    "customfield_10106": "Data Readiness", "customfield_10107": "Success Metric",
    "customfield_10108": "Baseline Captured", "customfield_10109": "Waiting On",
    "customfield_10110": "Stage Target Date", "customfield_10111": "Next Step",
    "customfield_10112": "Close Reason", "customfield_10021": "Flagged",
    "customfield_10113": "Technology Readiness", "customfield_10114": "AI Pattern",
    "customfield_10115": "Target Go-Live", "customfield_10116": "Realized Annual Value",
    "issuelinks": "Linked Issues",
}
STATUS = {"intake": ("Backlog", "new"), "triage": ("Triage", "new"),
          "discovery": ("In Discovery", "indeterminate"), "design": ("In Design", "indeterminate"),
          "approval": ("Awaiting Approval", "new"), "delivery": ("In Progress", "indeterminate"),
          "scale": ("In Scale", "indeterminate"), "value": ("In Benefits Review", "indeterminate")}
IMPACT = {"revenue": "Revenue / growth", "cost": "Cost / productivity", "cycle": "Cycle time",
          "risk": "Risk / control", "insight": "Decision / insight"}
LABEL = {"NPI": "npi", "Reg report": "reg-report", "No human review": "no-human-review"}
READY = {"ready": "Ready", "partial": "Partial", "unavailable": "Not available"}
TECH = {"ready": "Ready", "partial": "Partial", "unavailable": "Not ready"}


def adf(text):
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def ts(d, hour="09:14"):
    return "%sT%s:00.000-0400" % (d, hour)


def opt(v, i):
    return {"self": "https://example.atlassian.net/rest/api/3/customFieldOption/%d" % i,
            "value": v, "id": str(i)}


def issue(u, n):
    name, cat = STATUS[u["stage"]]
    closed = u.get("closed")
    f = {
        "summary": u["name"],
        "status": {"name": closed["outcome"] if closed else name, "id": str(n),
                   "statusCategory": {"key": "done" if closed else cat, "id": 3}},
        "assignee": {"displayName": u["owner"], "accountId": "5b10ac8d82e05b22cc7d4ef%d" % n,
                     "emailAddress": "someone%d@example.com" % n, "avatarUrls": {"48x48": "x"}},
        "created": ts(u["opened"]), "updated": ts(u["lastUpdate"], "16:02"),
        "duedate": None,
        "resolution": {"name": closed["outcome"], "id": "10"} if closed else None,
        "resolutiondate": ts(closed["date"], "11:00") if closed else None,
        "labels": [LABEL[r] for r in u["risk"]] + ["q3-planning"],
        "customfield_10101": opt(u["func"], 100 + n),
        "customfield_10102": u["sponsor"],
        "customfield_10103": u["wsjf"],
        "customfield_10104": u["est"],
        "customfield_10016": u["size"],
        "customfield_10105": [opt(IMPACT[k], 200 + i) for i, k in enumerate(u["impact"])],
        "customfield_10106": opt(READY[u["dataReady"]], 300) if u["dataReady"] else None,
        "customfield_10107": adf("Defined in the discovery package.") if u["metric"] else None,
        "customfield_10108": [opt("Yes", 400)] if u["baseline"] else None,
        "customfield_10109": u["waitingOn"],
        "customfield_10021": [opt("Impediment", 500)] if u["waitingOn"] else None,
        "customfield_10110": u["target"],
        "customfield_10111": None if u["next"] in (None, "—") else u["next"],
        "customfield_10112": closed["reason"] if closed else None,
        "customfield_10113": opt(TECH[u["techReady"]], 600) if u.get("techReady") else None,
        "customfield_10114": opt(u["pattern"], 700) if u.get("pattern") else None,
        "customfield_10115": u.get("live"),
        "customfield_10116": u.get("realized"),
        "issuelinks": [{"id": "9%d" % n, "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
                        "inwardIssue": {"key": d, "fields": {"summary": "x"}}} for d in u.get("dependsOn", [])]
                      + [{"id": "8%d" % n, "type": {"name": "Relates"}, "outwardIssue": {"key": "AI-001"}}],
        "description": adf("Problem statement for " + u["name"] + "."),
        "comment": {"comments": [{"author": {"displayName": u["owner"], "accountId": "x"},
                                  "created": ts(u["lastUpdate"], "15:00"),
                                  "body": adf("Moved to " + name + ".")}],
                    "total": 1, "maxResults": 1},
    }
    out = {"id": str(10000 + n), "key": u["id"], "self": "https://example.atlassian.net/rest/api/3/issue/%d" % n,
           "fields": f}
    if closed:
        out["changelog"] = {"histories": [
            {"id": "1", "created": ts(u["opened"], "10:00"), "items": [
                {"field": "status", "fromString": "Backlog", "toString": STATUS["triage"][0]}]},
            {"id": "2", "created": ts(closed["date"], "11:00"), "items": [
                {"field": "status", "fromString": name, "toString": closed["outcome"]},
                {"field": "resolution", "fromString": None, "toString": closed["outcome"]}]}]}
    return out


GENERIC_NAMES = {
    "summary": "Summary", "status": "Status", "assignee": "Assignee", "reporter": "Reporter",
    "created": "Created", "updated": "Updated", "duedate": "Due date", "resolution": "Resolution",
    "resolutiondate": "Resolved", "labels": "Labels", "components": "Components",
    "fixVersions": "Fix versions", "issuelinks": "Linked Issues",
    "customfield_10016": "Story Points", "customfield_10021": "Flagged",
}
SLUG_IMPACT = {"revenue": "revenue", "cost": "cost", "cycle": "cycle-time", "risk": "risk", "insight": "insight"}
SLUG_TECH = {"ready": "ready", "partial": "partial", "unavailable": "not-ready"}


def slug(t):
    return "".join(c if c.isalnum() else "-" for c in t.lower()).replace("&", "").strip("-").replace("---", "-").replace("--", "-")


def generic_issue(u, n):
    """The same use case in a Jira nobody has customised: the workflow is
    To Do / In Progress / Done, and the stage rides on a label."""
    closed = u.get("closed")
    pre = ["intake", "triage", "discovery", "design", "approval"]
    status = ("Done", "done") if closed else ("To Do", "new") if u["stage"] in pre else ("In Progress", "indeterminate")
    labels = [LABEL[r] for r in u["risk"]] + ["impact-" + SLUG_IMPACT[k] for k in u["impact"]]
    labels.append("stage-" + u["stage"])
    if u["dataReady"]:
        labels.append("data-" + u["dataReady"])
    if u.get("techReady"):
        labels.append("tech-" + SLUG_TECH[u["techReady"]])
    if u["metric"]:
        labels.append("metric-defined")
    if u["baseline"]:
        labels.append("baseline-set")
    if u.get("pattern"):
        labels.append("pattern-" + slug(u["pattern"]))
    labels.append("q3-planning")
    f = {
        "summary": u["name"],
        "status": {"name": status[0], "statusCategory": {"key": status[1]}},
        "assignee": {"displayName": u["owner"], "accountId": "x%d" % n},
        "reporter": {"displayName": u["sponsor"], "accountId": "r%d" % n, "emailAddress": "r@example.com"},
        "created": ts(u["opened"]), "updated": ts(u["lastUpdate"], "16:02"),
        "duedate": u["target"],
        "resolution": {"name": closed["outcome"]} if closed else None,
        "resolutiondate": ts(closed["date"], "11:00") if closed else None,
        "labels": labels,
        "components": [{"id": str(n), "name": u["func"], "self": "x"}],
        "fixVersions": [{"id": str(n), "name": "Release " + u["live"][:7], "releaseDate": u["live"],
                         "released": False}] if u.get("live") else [],
        "issuelinks": [{"id": "9%d" % n, "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
                        "inwardIssue": {"key": d}} for d in u.get("dependsOn", [])],
        "customfield_10016": u["size"],
        "customfield_10021": [opt("Impediment", 500)] if u["waitingOn"] else None,
    }
    return {"id": str(10000 + n), "key": u["id"], "fields": f}


def main():
    sample = bp.builtin_data()["USE_CASES"]
    clean = {"isLast": True, "names": NAMES, "issues": [issue(u, i) for i, u in enumerate(sample)]}
    messy = copy.deepcopy(clean)
    iss = {i["key"]: i for i in messy["issues"]}
    iss["AI-002"]["fields"]["status"] = {"name": "Ready for UAT", "statusCategory": {"key": "indeterminate"}}
    iss["AI-005"]["fields"]["customfield_10110"] = None
    iss["AI-001"]["fields"]["customfield_10105"].append(opt("Customer experience", 299))
    iss["AI-003"]["fields"]["customfield_10104"] = "$1,200"
    messy["names"]["customfield_10028"] = "Story Points"   # the classic duplicate, never filled
    for i in messy["issues"]:
        i["fields"]["customfield_10028"] = None
    OUT.mkdir(parents=True, exist_ok=True)
    generic = {"isLast": True, "names": GENERIC_NAMES,
               "issues": [generic_issue(u, i) for i, u in enumerate(sample)]}
    for name, data in (("jira_clean.json", clean), ("jira_messy.json", messy), ("jira_generic.json", generic)):
        (OUT / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote tests/fixtures/%s — %d issues" % (name, len(data["issues"])))


if __name__ == "__main__":
    main()
