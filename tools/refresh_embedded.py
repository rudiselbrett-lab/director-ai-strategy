#!/usr/bin/env python3
"""Re-embed the page and sample data into build_portfolio.py.

build_portfolio.py carries a compressed copy of ai-use-case-dashboard.html
and of the sample portfolio so it runs as one file anywhere. Run this after
changing either, or the copied-alone script builds yesterday's page:

    python3 tools/refresh_embedded.py
"""
import base64
import json
import pathlib
import re
import sys
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_portfolio as bp  # noqa: E402

SCRIPT = ROOT / "build_portfolio.py"
PAGE = ROOT / "ai-use-case-dashboard.html"


def pack(text):
    blob = base64.b64encode(zlib.compress(text.encode("utf-8"), 9)).decode()
    return "(\n" + "\n".join('    "%s"' % blob[i:i + 76] for i in range(0, len(blob), 76)) + "\n)"


def main():
    page = PAGE.read_text(encoding="utf-8")
    m = re.search(r"const JIRA_MAP = (\{.*?\n\});", page, re.S)
    if not m:
        sys.exit("error: no JIRA_MAP in the page's data block")
    data = bp.builtin_data()
    data["JIRA_MAP"] = json.loads(m.group(1))
    data["JIRA_SNAPSHOT"] = None
    src = SCRIPT.read_text(encoding="utf-8")
    for name, text in (("TEMPLATE_B64", page),
                       ("DATA_B64", json.dumps(data, ensure_ascii=False))):
        src, n = re.subn(r"^%s = \(\n.*?\n\)" % name, lambda _: "%s = %s" % (name, pack(text)),
                         src, count=1, flags=re.S | re.M)
        if n != 1:
            sys.exit("error: could not find %s in build_portfolio.py" % name)
    SCRIPT.write_text(src, encoding="utf-8")
    print("re-embedded the page (%d KB) and sample data" % (len(page) // 1024))


if __name__ == "__main__":
    main()
