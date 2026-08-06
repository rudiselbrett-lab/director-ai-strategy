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
CONSTS = ["CAPACITY", "TRENDS", "IMPACTS", "RISK_FLAGS", "STATUS_LOG",
          "STATUS_HISTORY", "USE_CASES"]

NOTES = {
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
)

DATA_B64 = (
    "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"
    "ThzJRw=="
)


if __name__ == "__main__":
    raise SystemExit(main())
