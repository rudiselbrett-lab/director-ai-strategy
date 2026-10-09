"""The live pull, against a stand-in Jira on localhost.

    python3 -m unittest discover tests
"""
import json
import pathlib
import sys
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_portfolio as bp  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "jira_clean.json").read_text(encoding="utf-8"))
FIELDS = [{"id": k, "name": v, "custom": k.startswith("customfield_")} for k, v in FIXTURE["names"].items()]


class FakeJira(BaseHTTPRequestHandler):
    seen = []
    status = 200

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        FakeJira.seen.append((url.path, q, self.headers.get("Authorization")))
        if FakeJira.status != 200:
            return self._send(FakeJira.status, {"errorMessages": ["nope"]})
        issues = FIXTURE["issues"]
        if url.path.endswith("/field"):
            return self._send(200, FIELDS)
        if url.path == "/rest/api/3/search/jql":
            start = int(q.get("nextPageToken") or 0)
            page = issues[start:start + 10]
            more = start + 10 < len(issues)
            body = {"issues": page, "isLast": not more}
            if more:
                body["nextPageToken"] = str(start + 10)
            return self._send(200, body)
        if url.path == "/rest/api/2/search":
            start = int(q.get("startAt", 0))
            return self._send(200, {"issues": issues[start:start + 10], "startAt": start,
                                    "total": len(issues)})
        self._send(404, {"errorMessages": ["no route"]})


class FetchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeJira)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.site = "http://127.0.0.1:%d" % cls.srv.server_port
        cls.jmap = bp.builtin_data()["JIRA_MAP"]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        FakeJira.seen, FakeJira.status = [], 200

    def env(self, **kw):
        return dict({"JIRA_SITE": self.site, "JIRA_ALLOW_HTTP": "1"}, **kw)

    def test_cloud_pages_through_tokens(self):
        snap = bp.fetch_jira(self.jmap, env=self.env(JIRA_EMAIL="a@b.c", JIRA_API_TOKEN="tok"), log=lambda *_: None)
        self.assertEqual(len(snap["issues"]), len(FIXTURE["issues"]))
        searches = [s for s in FakeJira.seen if s[0].endswith("/search/jql")]
        self.assertEqual(len(searches), 2)
        self.assertTrue(all(s[2].startswith("Basic ") for s in FakeJira.seen))
        asked = searches[0][1]["fields"].split(",")
        self.assertIn("customfield_10101", asked)       # resolved from "Consumer Bank function"
        self.assertNotIn("description", asked)          # includeText is off
        self.assertEqual(searches[0][1].get("expand"), "changelog")

    def test_data_center_pages_through_offsets(self):
        snap = bp.fetch_jira(self.jmap, env=self.env(JIRA_PAT="pat"), log=lambda *_: None)
        self.assertEqual(len(snap["issues"]), len(FIXTURE["issues"]))
        self.assertTrue(all(s[2] == "Bearer pat" for s in FakeJira.seen))
        self.assertTrue(any(s[0] == "/rest/api/2/search" for s in FakeJira.seen))

    def test_trims_people_and_keeps_no_secret(self):
        snap = bp.fetch_jira(self.jmap, env=self.env(JIRA_EMAIL="a@b.c", JIRA_API_TOKEN="s3cret"), log=lambda *_: None)
        blob = json.dumps(snap)
        for leak in ("s3cret", "accountId", "emailAddress", "avatarUrls"):
            self.assertNotIn(leak, blob)
        self.assertEqual(snap["issues"][0]["fields"]["assignee"], {"displayName": "M. Alvarez"})

    def test_bad_credentials_say_so(self):
        FakeJira.status = 401
        with self.assertRaises(bp.JiraError) as cm:
            bp.fetch_jira(self.jmap, env=self.env(JIRA_PAT="bad"), log=lambda *_: None)
        self.assertIn("credentials", str(cm.exception))

    def test_refuses_plain_http_and_missing_credentials(self):
        with self.assertRaises(bp.JiraError):
            bp.fetch_jira(self.jmap, env={"JIRA_SITE": self.site, "JIRA_PAT": "x"}, log=lambda *_: None)
        with self.assertRaises(bp.JiraError):
            bp.fetch_jira(self.jmap, env=self.env(), log=lambda *_: None)

    def test_precheck_flags_unmapped_status(self):
        messy = json.loads((ROOT / "tests" / "fixtures" / "jira_messy.json").read_text(encoding="utf-8"))
        snap = bp.snapshot_from(messy["issues"], messy["names"], self.jmap)
        lines, errors = bp.precheck(snap, self.jmap)
        self.assertEqual(errors, 1)
        self.assertTrue(any("Ready for UAT" in ln for ln in lines))


if __name__ == "__main__":
    unittest.main()
