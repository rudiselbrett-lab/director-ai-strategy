"""Tests for jira_portfolio.py.  Run:  python3 -m unittest -v test_jira_portfolio"""

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jira_portfolio as jp  # noqa: E402

TODAY = dt.date(2026, 10, 14)


def cfg(**over):
    c = jp.deep_merge(jp.DEFAULT_CONFIG, {"base_url": "https://jira.example.com"})
    return jp.deep_merge(c, over)


def issue(key, typ="Epic", status="In Progress", cat="indeterminate", due=None, updated=1,
          parent=None, owner="Pat Lee", desc=True, **fields):
    f = {
        "summary": "Summary " + key,
        "issuetype": {"name": typ},
        "status": {"name": status, "statusCategory": {"key": cat}},
        "assignee": {"displayName": owner, "emailAddress": "pat@example.com"} if owner else None,
        "duedate": (TODAY + dt.timedelta(days=due)).isoformat() if due is not None else None,
        "updated": (TODAY - dt.timedelta(days=updated)).isoformat() + "T09:00:00.000+0000",
        "description": "Scope" if desc else None,
        "parent": {"key": parent, "fields": {"summary": "Cap " + parent}} if parent else None,
    }
    f.update(fields)
    return {"key": key, "fields": f}


def scored(raws, **over):
    return {r["key"]: r for r in jp.score(raws, cfg(**over), TODAY)}


class Normalize(unittest.TestCase):
    def test_cloud_shape(self):
        r = jp.normalize(issue("AI-2", parent="AI-1", due=10), cfg(), TODAY)
        self.assertEqual(r["kind"], "epic")
        self.assertEqual(r["parent"], "AI-1")
        self.assertEqual(r["parentSummary"], "Cap AI-1")
        self.assertEqual(r["owner"], "Pat Lee")
        self.assertEqual(r["ownerEmail"], "pat@example.com")
        self.assertEqual(r["daysToDue"], 10)
        self.assertEqual(r["url"], "https://jira.example.com/browse/AI-2")
        self.assertEqual(r["statusCat"], "inprogress")

    def test_datacenter_parent_link(self):
        raw = issue("AI-2", customfield_1={"hasEpicLinkFieldDependency": False,
                                           "data": {"key": "AI-1", "summary": "Cap one"}})
        r = jp.normalize(raw, cfg(parent_field="customfield_1"), TODAY)
        self.assertEqual((r["parent"], r["parentSummary"]), ("AI-1", "Cap one"))
        raw = issue("AI-3", customfield_1="AI-9")
        self.assertEqual(jp.normalize(raw, cfg(parent_field="customfield_1"), TODAY)["parent"], "AI-9")

    def test_owner_field_by_type(self):
        raw = issue("AI-1", typ="Capability", customfield_7={"displayName": "Cap Owner"})
        c = cfg(owner_field={"Capability": "customfield_7", "default": "assignee"})
        self.assertEqual(jp.normalize(raw, c, TODAY)["owner"], "Cap Owner")
        self.assertEqual(jp.normalize(issue("AI-2"), c, TODAY)["owner"], "Pat Lee")

    def test_adf_description_and_empty_adf(self):
        full = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "x"}]}]}
        empty = {"type": "doc", "content": [{"type": "paragraph", "content": []}]}
        self.assertTrue(jp.normalize(issue("A-1", description=full), cfg(), TODAY)["hasDescription"])
        self.assertFalse(jp.normalize(issue("A-1", description=empty), cfg(), TODAY)["hasDescription"])

    def test_text_of_shapes(self):
        self.assertEqual(jp.text_of([{"value": "A"}, {"name": "B"}]), "A, B")
        self.assertEqual(jp.text_of({"displayName": "Z"}), "Z")
        self.assertEqual(jp.text_of(None), "")
        self.assertEqual(jp.text_of(3), "3")

    def test_rag_values(self):
        self.assertEqual(jp.rag_of({"value": "RED"}), "red")
        self.assertEqual(jp.rag_of("Yellow"), "amber")
        self.assertEqual(jp.rag_of({"value": "On Track"}), "green")
        self.assertIsNone(jp.rag_of({"value": "TBD"}))


class Health(unittest.TestCase):
    def test_states(self):
        s = scored([
            issue("A-1", due=-3),                                  # overdue
            issue("A-2", status="Blocked", due=40),                 # red status
            issue("A-3", status="To Do", cat="new", due=5),         # near and not started
            issue("A-4", due=40, updated=30),                       # stale
            issue("A-5", due=None),                                 # nothing to judge
            issue("A-6", due=40),                                   # fine
            issue("A-7", status="Done", cat="done", due=-50),       # done wins
            issue("A-8", status="On Hold", due=40),                 # amber status
        ])
        want = {"A-1": "red", "A-2": "red", "A-3": "amber", "A-4": "amber",
                "A-5": "nodate", "A-6": "green", "A-7": "done", "A-8": "amber"}
        self.assertEqual({k: v["health"] for k, v in s.items()}, want)
        self.assertIn("3 days past due", s["A-1"]["reasons"][0])

    def test_one_day_grammar(self):
        s = scored([issue("A-1", due=-1)])
        self.assertIn("1 day past due", s["A-1"]["reasons"][0])

    def test_status_match_is_case_insensitive(self):
        self.assertEqual(scored([issue("A-1", status="BLOCKED", due=40)])["A-1"]["health"], "red")

    def test_flagged(self):
        s = scored([issue("A-1", due=40, customfield_9=[{"value": "Impediment"}])], flagged_field="customfield_9")
        self.assertEqual(s["A-1"]["health"], "red")

    def test_rag_worse_than_data_wins_and_mismatch_flagged(self):
        s = scored([issue("A-1", due=40, cf={"value": "Red"}),
                    issue("A-2", due=-2, cf={"value": "Green"})], rag_field="cf")
        self.assertEqual(s["A-1"]["health"], "red")
        self.assertFalse(s["A-1"]["ragMismatch"])
        self.assertEqual(s["A-2"]["health"], "red")
        self.assertIn("rag_mismatch", [g["code"] for g in s["A-2"]["gaps"]])

    def test_rollup_takes_worst_open_epic(self):
        s = scored([issue("C-1", typ="Capability", due=90),
                    issue("E-1", parent="C-1", due=-5),
                    issue("E-2", parent="C-1", due=30),
                    issue("E-3", parent="C-1", status="Done", cat="done")])
        c = s["C-1"]
        self.assertEqual(c["health"], "green")
        self.assertEqual(c["rollup"], "red")
        self.assertEqual(sorted(c["children"]), ["E-1", "E-2", "E-3"])
        self.assertEqual(c["childCounts"]["red"], 1)
        self.assertEqual(c["reasons"], ["1 of 3 epics off track"])

    def test_done_epics_do_not_drag_rollup(self):
        s = scored([issue("C-1", typ="Capability", due=90),
                    issue("E-1", parent="C-1", status="Done", cat="done", due=-40)])
        self.assertEqual(s["C-1"]["rollup"], "green")


class Gaps(unittest.TestCase):
    def codes(self, r):
        return sorted(g["code"] for g in r["gaps"])

    def test_hygiene(self):
        s = scored([issue("C-1", typ="Capability", owner=None, desc=False),
                    issue("E-1", due=10)],
                   required_fields=[{"field": "cv", "label": "Business value", "types": ["Capability"]}])
        self.assertEqual(self.codes(s["C-1"]), ["missing_field", "no_children", "no_description", "no_due", "no_owner"])
        self.assertEqual(self.codes(s["E-1"]), ["no_parent"])
        self.assertIn("Business value", s["C-1"]["gaps"][-1]["detail"])

    def test_done_capability_with_open_epics(self):
        s = scored([issue("C-1", typ="Capability", status="Done", cat="done"),
                    issue("E-1", parent="C-1", due=10)])
        self.assertEqual(self.codes(s["C-1"]), ["done_open_children"])

    def test_done_issues_raise_nothing_else(self):
        s = scored([issue("E-1", status="Done", cat="done", owner=None, desc=False, updated=200)])
        self.assertEqual(s["E-1"]["gaps"], [])

    def test_disabled_checks(self):
        s = scored([issue("E-1", due=10, desc=False)], disabled_checks=["no_parent", "no_description"])
        self.assertEqual(s["E-1"]["gaps"], [])


class Client(unittest.TestCase):
    def env(self, **kv):
        return mock.patch.dict(os.environ, kv, clear=True)

    def test_cloud_pagination_by_token(self):
        pages = [{"issues": [{"key": "A-1"}], "nextPageToken": "t2", "isLast": False},
                 {"issues": [{"key": "A-2"}], "isLast": True}]
        with self.env(JIRA_EMAIL="a@b.c", JIRA_API_TOKEN="x"):
            j = jp.Jira(cfg())
        with mock.patch.object(j, "call", side_effect=pages) as call:
            got = j.search("project = A", ["summary"], 100)
        self.assertEqual([i["key"] for i in got], ["A-1", "A-2"])
        self.assertEqual(call.call_args_list[0].args[1], "/rest/api/3/search/jql")
        self.assertEqual(call.call_args_list[1].args[2]["nextPageToken"], "t2")
        self.assertTrue(j.auth.startswith("Basic "))

    def test_datacenter_pagination_by_offset(self):
        pages = [{"issues": [{"key": "A-1"}, {"key": "A-2"}], "total": 3},
                 {"issues": [{"key": "A-3"}], "total": 3}]
        with self.env(JIRA_PAT="pat"):
            j = jp.Jira(cfg(deployment="datacenter"))
        with mock.patch.object(j, "call", side_effect=pages) as call:
            got = j.search("x", ["summary"], 100)
        self.assertEqual(len(got), 3)
        self.assertEqual(call.call_args_list[1].args[2]["startAt"], 2)
        self.assertEqual(j.auth, "Bearer pat")

    def test_cap_stops_paging(self):
        page = {"issues": [{"key": "A-%d" % i} for i in range(100)], "nextPageToken": "n", "isLast": False}
        with self.env(JIRA_EMAIL="a", JIRA_API_TOKEN="b"):
            j = jp.Jira(cfg())
        with mock.patch.object(j, "call", return_value=page):
            self.assertEqual(len(j.search("x", [], 150)), 150)

    def test_missing_credentials_exit(self):
        with self.env():
            with self.assertRaises(SystemExit):
                jp.Jira(cfg())

    def test_fields_requested(self):
        c = cfg(owner_field={"Capability": "cf_o", "default": "assignee"}, rag_field="cf_r",
                required_fields=[{"field": "cf_v", "label": "V"}])
        f = jp.fields_to_fetch(c)
        for x in ("summary", "cf_o", "cf_r", "cf_v", "parent", "assignee"):
            self.assertIn(x, f)
        self.assertEqual(len(f), len(set(f)))


class Page(unittest.TestCase):
    def test_hostile_text_cannot_break_out_of_the_data_block(self):
        raw = issue("A-1", due=5)
        raw["fields"]["summary"] = "</script><script>alert(1)</script><!--"
        c = cfg(title="<b>T</b>")
        recs = jp.score([raw], c, TODAY)
        page = jp.build_html(recs, c, jp.build_meta(c, TODAY, "test"))
        self.assertNotIn("<script>alert(1)", page)
        self.assertIn("<title>&lt;b&gt;T&lt;/b&gt;</title>", page)
        block = page.split('type="application/json">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(block)["issues"][0]["summary"], raw["fields"]["summary"])

    def test_base_url_must_be_http(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"base_url": "javascript:alert(1)"}, f)
        try:
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(SystemExit):
                    jp.load_config(f.name)
        finally:
            os.unlink(f.name)

    def test_bad_brand_color_falls_back(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"brand_color": "red;}</style>"}, f)
        try:
            self.assertEqual(jp.load_config(f.name)["brand_color"], jp.DEFAULT_CONFIG["brand_color"])
        finally:
            os.unlink(f.name)


class History(unittest.TestCase):
    def test_snapshot_round_trip_and_bad_files_skipped(self):
        recs = jp.score([issue("A-1", due=5)], cfg(), TODAY)
        with tempfile.TemporaryDirectory() as d:
            jp.save_snapshot(d, TODAY, recs)
            with open(os.path.join(d, "snapshot-2026-01-01.json"), "w") as f:
                f.write("{not json")
            with open(os.path.join(d, "notes.txt"), "w") as f:
                f.write("ignored")
            hist = jp.load_history(d)
        self.assertEqual([h[0] for h in hist], [TODAY])
        self.assertEqual(hist[0][1][0]["key"], "A-1")
        self.assertNotIn("extra", hist[0][1][0])

    def test_weekly_points_keep_latest_per_week_and_today_wins(self):
        a, b = TODAY - dt.timedelta(days=8), TODAY - dt.timedelta(days=7)   # same ISO week
        pts = jp.weekly_points([(a, ["a"]), (b, ["b"]), (TODAY, ["old today"])], TODAY, ["now"])
        self.assertEqual([p[1] for p in pts], [["b"], ["now"]])

    def test_missing_history_dir_is_empty(self):
        self.assertEqual(jp.load_history("/nonexistent/dir"), [])


class Report(unittest.TestCase):
    def pair(self, before, after):
        prev = [jp.compact(r) for r in jp.score(before, cfg(), TODAY - dt.timedelta(days=7))]
        curr = [jp.compact(r) for r in jp.score(after, cfg(), TODAY)]
        return jp.weekly_report(TODAY, curr, (TODAY - dt.timedelta(days=7), prev), cfg())

    def groups(self, rep, title_start):
        sec = next(s for s in rep["sections"] if s["title"].startswith(title_start))
        return {g["label"]: [ln["key"] for ln in g["lines"]] for g in sec["groups"]}

    def test_changes_week_over_week(self):
        before = [issue("C-1", typ="Capability", due=90), issue("E-1", parent="C-1", due=30),
                  issue("E-2", parent="C-1", due=20), issue("E-3", parent="C-1", due=40, updated=30),
                  issue("E-4", parent="C-1", status="In Review", due=50)]
        after = [issue("C-1", typ="Capability", due=90), issue("E-1", parent="C-1", due=-2),
                 issue("E-2", parent="C-1", due=34), issue("E-3", parent="C-1", due=40),
                 issue("E-4", parent="C-1", status="Done", cat="done", due=50),
                 issue("E-5", parent="C-1", due=60, owner=None)]
        ch = self.groups(self.pair(before, after), "What changed")
        self.assertEqual(ch["Completed"], ["E-4"])
        self.assertEqual(ch["New"], ["E-5"])
        self.assertIn("E-1", ch["Now off track"])
        self.assertIn("C-1", ch["Now off track"])
        self.assertEqual(ch["Back on track"], ["E-3"])
        self.assertIn("E-2", ch["Due dates moved"])

    def test_first_report_falls_back_to_jira_dates(self):
        recs = jp.score([issue("E-1", due=10, created=(TODAY - dt.timedelta(days=2)).isoformat()),
                         issue("E-2", status="Done", cat="done",
                               resolutiondate=(TODAY - dt.timedelta(days=3)).isoformat()),
                         issue("E-3", status="Done", cat="done",
                               resolutiondate=(TODAY - dt.timedelta(days=30)).isoformat())], cfg(), TODAY)
        rep = jp.weekly_report(TODAY, [jp.compact(r) for r in recs], None, cfg())
        ch = self.groups(rep, "What changed")
        self.assertEqual(ch["Completed"], ["E-2"])
        self.assertEqual(ch["New"], ["E-1"])
        self.assertIsNone(rep["baseline"])
        self.assertIsNotNone(rep["sections"][0]["note"])

    def test_elements_and_overall(self):
        rep = self.pair([issue("E-1", due=30)], [issue("E-1", due=-1)])
        names = {e["name"]: e["rag"] for e in rep["elements"]}
        self.assertEqual(names["Schedule"], "red")
        self.assertEqual(rep["overall"], "red")
        self.assertTrue(rep["headline"].startswith("Schedule and Data quality are the constraint. 1 of 1 item is off track"))
        self.assertIn("(Oct 13)", rep["headline"])
        self.assertEqual(self.groups(rep, "Needs a decision")["Re-baseline or escalate"], ["E-1"])

    def test_all_green(self):
        rep = self.pair([issue("E-1", due=30, parent="C-1"), issue("C-1", typ="Capability", due=60),
                         issue("E-9", parent="C-1", status="In Progress", due=40)],
                        [issue("E-1", due=30, parent="C-1"), issue("C-1", typ="Capability", due=60),
                         issue("E-9", parent="C-1", status="Done", cat="done", due=40)])
        self.assertEqual(rep["overall"], "green")
        self.assertTrue(rep["headline"].startswith("Everything is on track"))

    def test_coming_up_window(self):
        rep = self.pair([issue("E-1", due=5), issue("E-2", due=30)], [issue("E-1", due=5), issue("E-2", due=30)])
        self.assertEqual(self.groups(rep, "Coming up")["Due by Oct 28"], ["E-1"])

    def test_markdown_has_links_and_every_section(self):
        rep = self.pair([issue("E-1", due=30)], [issue("E-1", due=-1)])
        md = jp.report_markdown(rep, cfg())
        self.assertIn("[E-1](https://jira.example.com/browse/E-1)", md)
        for s in rep["sections"]:
            self.assertIn("## " + s["title"], md)
        self.assertIn("**Overall: Red.**", md)

    def test_reports_built_newest_first_with_baselines(self):
        t = jp.deep_merge(cfg(), jp.SAMPLE_CONFIG)
        recs = jp.score(jp.sample_issues(TODAY), t, TODAY)
        pts = jp.weekly_points(jp.sample_history(TODAY, t), TODAY, [jp.compact(r) for r in recs])
        reps = jp.build_reports(pts, t)
        self.assertEqual(reps[0]["date"], TODAY.isoformat())
        self.assertEqual(reps[0]["baseline"], (TODAY - dt.timedelta(days=7)).isoformat())
        self.assertIsNone(reps[-1]["baseline"])


class Trends(unittest.TestCase):
    def test_monthly_completions_and_median_cycle(self):
        def done(key, created_ago, resolved_ago):
            return issue(key, status="Done", cat="done",
                         created=(TODAY - dt.timedelta(days=created_ago)).isoformat(),
                         resolutiondate=(TODAY - dt.timedelta(days=resolved_ago)).isoformat())
        recs = jp.score([done("E-1", 40, 2), done("E-2", 30, 5), done("E-3", 100, 40), issue("E-4", due=5)], cfg(), TODAY)
        tr = jp.trends(jp.weekly_points([], TODAY, [jp.compact(r) for r in recs]), recs, TODAY)
        oct_ = next(m for m in tr["monthly"] if m["month"] == "2026-10")
        self.assertEqual(oct_["completed"], 2)
        self.assertEqual(oct_["medianCycle"], 32)   # 38 and 25 days -> 31.5 rounds to 32
        self.assertEqual(len(tr["monthly"]), 6)
        self.assertEqual(tr["weekly"][-1]["green"], 1)


class Cli(unittest.TestCase):
    def run_cli(self, *args, cwd):
        here = os.path.dirname(os.path.abspath(__file__))
        return subprocess.run([sys.executable, os.path.join(here, "jira_portfolio.py"), *args],
                              cwd=cwd, capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "")})

    def test_sample_and_from_json_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_cli("--sample", "--out", "s.html", "--today", "2026-10-14", cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("capabilities", r.stdout)
            with open(os.path.join(d, "raw.json"), "w") as f:
                json.dump({"issues": jp.sample_issues(TODAY)}, f)
            r = self.run_cli("--from-json", "raw.json", "--out", "f.html", cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.getsize(os.path.join(d, "f.html")) > 10000)

    def test_history_accumulates_and_report_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "raw.json"), "w") as f:
                json.dump({"issues": jp.sample_issues(TODAY)}, f)
            with open(os.path.join(d, "c.json"), "w") as f:
                json.dump({"history_dir": "hist"}, f)
            for day_ in ("2026-10-07", "2026-10-14"):
                r = self.run_cli("--config", "c.json", "--from-json", "raw.json", "--out", "p.html", "--today", day_, cwd=d)
                self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(sorted(os.listdir(os.path.join(d, "hist"))),
                             ["snapshot-2026-10-07.json", "snapshot-2026-10-14.json"])
            with open(os.path.join(d, "weekly-report-2026-10-14.md")) as f:
                self.assertIn("compared with Oct 7", f.read())
            r = self.run_cli("--config", "c.json", "--from-json", "raw.json", "--out", "q.html",
                             "--today", "2026-10-21", "--no-history", cwd=d)
            self.assertEqual(len(os.listdir(os.path.join(d, "hist"))), 2)

    def test_init_config_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_cli("--init-config", cwd=d).returncode, 0)
            with open(os.path.join(d, jp.DEFAULT_CONFIG_PATH)) as f:
                self.assertNotIn("token", json.dumps({k: v for k, v in json.load(f).items() if k != "_readme"}).lower())
            self.assertNotEqual(self.run_cli("--init-config", cwd=d).returncode, 0)


if __name__ == "__main__":
    unittest.main()
