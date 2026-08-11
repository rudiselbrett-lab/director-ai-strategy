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
import pathlib
import sys
import webbrowser
import zlib

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "ai-use-case-portfolio.html"

START = "/* ===== DATA BLOCK START"
END = "/* ===== DATA BLOCK END ===================================================== */"

# Order matters only for readability of the generated file.
CONSTS = ["ANCHOR", "CAPACITY", "TRENDS", "IMPACTS", "RISK_FLAGS", "STATUS_LOG",
          "STATUS_HISTORY", "USE_CASES"]

NOTES = {
    "ANCHOR": "The date this sample was authored. Every date below shifts by\n   (today - ANCHOR) when the page loads, so the demo keeps its shape whenever\n   it is opened. Set it to null for real data, where dates mean what they say.",
    "CAPACITY": "Delivery points available per increment. Work in delivery or\n   realization consumes it; what is left decides how far down the ranked\n   backlog we get.",
    "TRENDS": "Portfolio history for the trend panels. Value figures are $K of annual\n   run-rate.",
    "IMPACTS": "Impact categories, mirroring the intake form's Impact question.",
    "RISK_FLAGS": "Risk flags, mirroring the intake form's routing question.",
    "STATUS_LOG": "The current week's narrative. In production this is the layer Jira\n   comments supply: one entry per material change.",
    "STATUS_HISTORY": "Previously issued weekly reports, kept as they were issued. These are\n   never recomputed — re-deriving last week from this week's data would\n   rewrite history.",
    "USE_CASES": "The portfolio. One entry per use case; one Jira issue per entry.",
}

# Columns for the spreadsheet round-trip. List fields are pipe-separated.
CSV_FIELDS = ["id", "name", "func", "stage", "owner", "sponsor", "wsjf", "est",
              "size", "impact", "metric", "dataReady", "baseline", "risk",
              "waitingOn", "lastUpdate", "target", "next", "closed"]
CSV_LISTS = {"impact", "risk"}
CSV_BOOLS = {"metric", "baseline", "closed"}
CSV_NUMBERS = {"wsjf", "est", "size"}


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
        missing = [k for k in CONSTS if k not in loaded]
        if missing:
            sys.exit("error: %s is missing %s" % (args.data, ", ".join(missing)))
        data = loaded
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
            if not row["closed"]:
                row.pop("closed")
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
            for field in CSV_FIELDS:
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
    ap.add_argument("--open", action="store_true",
                    help="open the result in a browser")
    args = ap.parse_args(argv)

    data = load_data(args)

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
    print("wrote %s — %d use cases, %d KB"
          % (out, len(data["USE_CASES"]), len(page) // 1024))
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
    "uao/hl+4Lvj/83ox//jG/wNHB38q"
)

DATA_B64 = (
    "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"
)


if __name__ == "__main__":
    raise SystemExit(main())
