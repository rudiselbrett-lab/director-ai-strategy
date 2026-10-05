#!/usr/bin/env python3
"""Build the AI Operating System workbook for Microsoft 365 Copilot Cowork.

Writes two files into OneDrive/Documents/AI-OS/:

  AI-OS.xlsx         blank, ready to go live
  AI-OS-sample.xlsx  the same workbook filled with illustrative data

and zips the OneDrive folder into ai-os-onedrive.zip for one-step copying.

This script runs here, not in Cowork. Cowork never needs it: every number on
the Dashboard is an Excel formula over the log sheets, so Cowork only ever
appends rows. Run it again only if you change the workbook's structure.

    pip install openpyxl
    python3 build_workbook.py
"""

import datetime as dt
import os
import zipfile

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "OneDrive", "Documents", "AI-OS")
ZIP_PATH = os.path.join(HERE, "ai-os-onedrive.zip")

LOG_ROWS = 1000      # formulas are pre-filled this far, so Cowork only types inputs
JIRA_ROWS = 500
SAMPLE_AS_OF = dt.date(2026, 10, 2)

# ---------------------------------------------------------------- styles
FONT = "Arial"
INK, INK2, INK3 = "16181D", "4A5160", "646C7A"
BRAND = "6B2C91"
SERIES = "2A78D6"
HAIR = "E2E4E8"
INPUT_HEAD = PatternFill("solid", fgColor="E8EEF8")
CALC_HEAD = PatternFill("solid", fgColor="EDEDED")
CALC_CELL = PatternFill("solid", fgColor="F7F7F7")
TILE = PatternFill("solid", fgColor="F5F6F7")
BANNER = PatternFill("solid", fgColor="FFF4D6")
STATUS = {  # fill, text. Reserved for health and never used as a series colour.
    "Critical": ("FBE3E3", "9B1C1C"),
    "Warning": ("FFF1D0", "7A5200"),
    "On track": ("E2F4E2", "1D6B1D"),
}
thin = Side(style="thin", color=HAIR)
BOTTOM = Border(bottom=thin)


def f(size=10, bold=False, color=INK, italic=False):
    return Font(name=FONT, size=size, bold=bold, color=color, italic=italic)


# ---------------------------------------------------------------- sheet specs
# Each log sheet: input columns Cowork writes, then computed columns it never
# touches. Computed formulas use {r} for the row number.
CONFIG_CELLS = {
    # name: (row, label, live default, sample value, note)
    "OwnerName":        (4,  "Your name (as Jira shows it)", "", "Sample PM", "Used to pick out issues assigned to you."),
    "JiraSite":         (5,  "Jira site URL", "https://YOURCOMPANY.atlassian.net", "https://example.atlassian.net", "No trailing slash. Builds the issue links."),
    "JiraProjects":     (6,  "Jira project key(s)", "AIUC", "AIUC", "Comma-separated, e.g. AIUC, GENAI"),
    "JiraScope":        (7,  "Jira scope in plain words", "All issues in the project(s) above that are not Done, plus anything closed in the last 30 days",
                          "All issues in AIUC that are not Done, plus anything closed in the last 30 days", "What Cowork asks the connector for. Plain English, not JQL: the Copilot connector is search, not a query engine."),
    "SampleAsOf":       (8,  "Sample data as-of date", None, SAMPLE_AS_OF, "Leave BLANK for real use. When set, every age is measured from this date so sample data stays coherent."),
    "AsOf":             (9,  "Today (computed)", '=IF(SampleAsOf="",TODAY(),SampleAsOf)', '=IF(SampleAsOf="",TODAY(),SampleAsOf)', "Do not edit."),
    "DecisionWarn":     (11, "Open decision: warning after (days)", 3, 3, ""),
    "DecisionCritical": (12, "Open decision: critical after (days)", 7, 7, ""),
    "UnconfirmedWarn":  (13, "Unconfirmed item: warning after (days)", 5, 5, ""),
    "SnapshotMaxAge":   (14, "Jira snapshot: stale after (days)", 1, 1, ""),
    "SnapshotAt":       (17, "Snapshot pulled at", None, dt.datetime(2026, 10, 2, 8, 41), "Written by Cowork on every Jira refresh."),
    "SnapshotSource":   (18, "Snapshot source", "", "Copilot connector (Jira Cloud)", "Copilot connector, or CSV export + file name."),
    "SnapshotCount":    (19, "Issues in snapshot", "", 16, "Written by Cowork. Compared to the last refresh to catch a short pull."),
}

STAGES = [  # name, stale days, gate owner. Mirrors the operating model's eight stages.
    ("Intake", 7, "Portfolio Lead"), ("Triage", 7, "PM Owner"), ("Discovery", 10, "PM Owner"),
    ("Design", 14, "Model Risk & Monitoring"), ("Approval", 14, "AI Council"), ("Delivery", 14, "Delivery Lead"),
    ("Scale", 14, "Product Owner"), ("Value", 45, "Finance Partner"),
]
STATUS_MAP = [
    ("Backlog", "Intake"), ("To Do", "Intake"), ("Open", "Intake"), ("Intake", "Intake"),
    ("Triage", "Triage"), ("Discovery", "Discovery"), ("Design", "Design"),
    ("In Review", "Approval"), ("Governance Review", "Approval"), ("Approval", "Approval"),
    ("In Progress", "Delivery"), ("In Delivery", "Delivery"), ("Build", "Delivery"),
    ("Scaling", "Scale"), ("Rollout", "Scale"), ("Value Tracking", "Value"), ("Measuring", "Value"),
    ("Done", "Closed"), ("Closed", "Closed"), ("Declined", "Closed"), ("Transferred", "Closed"), ("Won't Do", "Closed"),
]
STAGE_ROW0, MAP_ROW0, MAP_ROWS = 23, 23, 40

INV = "Inventory"
INV_INPUTS = [
    ("ID", 10, "INV-0001, INV-0002 ... next number after the last row."),
    ("Date", 11, "Date the information arrived. YYYY-MM-DD."),
    ("Type", 11, "New = What's New. Know = What We Need to Know. Decision = Decision Needed. Conflict = disagrees with the inventory. Confirmed / Resolved close an earlier row named in Ref."),
    ("Topic", 16, "Topic slug from the Topics sheet."),
    ("Summary", 60, "One sentence. No customer data."),
    ("From", 20, "Person it came from."),
    ("Channel", 11, "Meeting, Email, Teams, Call, Document, Jira, Session."),
    ("Confidence", 12, "Confirmed if first-hand or verified; Unconfirmed if second-hand."),
    ("Ref", 10, "For Confirmed, Resolved or Conflict: the INV ID it refers to."),
    ("Jira", 11, "Related Jira key, if any."),
]
R = LOG_ROWS + 1
INV_CALC = [
    ("State", 12,
     '=IF($A{r}="","",IF(OR($C{r}="Decision",$C{r}="Conflict"),IF(COUNTIFS($I$2:$I$%d,$A{r},$C$2:$C$%d,"Resolved")=0,"Open","Closed"),'
     'IF(AND($H{r}="Unconfirmed",OR($C{r}="New",$C{r}="Know")),IF(COUNTIFS($I$2:$I$%d,$A{r},$C$2:$C$%d,"Confirmed")=0,"Unconfirmed","Confirmed"),"Logged")))' % (R, R, R, R)),
    ("Age (days)", 10, '=IF($A{r}="","",AsOf-$B{r})'),
    ("Severity", 11,
     '=IF($K{r}="Open",IF($C{r}="Conflict","Critical",IF($L{r}>=DecisionCritical,"Critical",IF($L{r}>=DecisionWarn,"Warning","On track"))),'
     'IF($K{r}="Unconfirmed",IF($L{r}>=UnconfirmedWarn,"Warning","On track"),""))'),
    ("Rank key", 10, '=IF($M{r}="","",IF($M{r}="Critical",3000,IF($M{r}="Warning",2000,1000))+$L{r}+ROW()/100000)'),
    ("Say this", 34,
     '=IF($K{r}="Open",IF($C{r}="Conflict","decide "&$A{r}&": <which version stands>","decide "&$A{r}&": <outcome>"),IF($K{r}="Unconfirmed","confirm "&$A{r},""))'),
]

JIRA = "Jira"
JIRA_INPUTS = [
    ("Key", 11, "Issue key, e.g. AIUC-104."), ("Summary", 42, ""), ("Status", 16, "Exactly as Jira shows it. Mapped to a stage on the Config sheet."),
    ("Type", 10, ""), ("Priority", 10, ""), ("Assignee", 18, ""), ("Created", 11, "YYYY-MM-DD"),
    ("Updated", 11, "YYYY-MM-DD. Drives staleness."), ("Due", 11, "YYYY-MM-DD or blank."),
    ("Flagged", 9, "Y if flagged / impediment / labelled blocked."), ("Labels", 18, ""), ("Topic", 16, "Topic slug, if it maps to one."),
]
J = JIRA_ROWS + 1
JIRA_CALC = [
    ("Stage", 11, '=IF($A{r}="","",IFERROR(INDEX(MapStage,MATCH($C{r},MapStatus,0)),"Unmapped"))'),
    ("Days idle", 9, '=IF($A{r}="","",AsOf-$H{r})'),
    ("Stale after", 9, '=IF(OR($M{r}="",$M{r}="Closed",$M{r}="Unmapped"),"",INDEX(StageStale,MATCH($M{r},StageName,0)))'),
    ("Health", 10,
     '=IF($A{r}="","",IF($M{r}="Closed","Closed",IF($J{r}="Y","Critical",IF(AND($I{r}<>"",$I{r}<AsOf),"Critical",'
     'IF($M{r}="Unmapped","Warning",IF($N{r}>2*$O{r},"Critical",IF($N{r}>$O{r},"Warning","On track")))))))'),
    ("Why", 34,
     '=IF(OR($P{r}="",$P{r}="Closed",$P{r}="On track"),"",IF($J{r}="Y","Flagged as an impediment",IF(AND($I{r}<>"",$I{r}<AsOf),"Past due since "&TEXT($I{r},"yyyy-mm-dd"),'
     'IF($M{r}="Unmapped","Status \'"&$C{r}&"\' is not in the Config map","No update in "&$N{r}&" days (limit "&$O{r}&")"))))'),
    ("Rank key", 10, '=IF(OR($P{r}="",$P{r}="Closed",$P{r}="On track"),"",IF($P{r}="Critical",3000,2000)+$N{r}+ROW()/100000)'),
    ("Say this", 30, '=IF($R{r}="","","draft Jira update for "&$A{r})'),
    ("Link", 7, '=IF($A{r}="","",HYPERLINK(JiraSite&"/browse/"&$A{r},"open"))'),
]

DONE = "Done"
DONE_INPUTS = [
    ("Date", 11, "Day it was done."), ("Accomplishment", 60, "Outcome, not activity. 'Got MRM sign-off on X', not 'met with MRM'."),
    ("Topic", 16, "Topic slug."), ("Jira", 11, "Related key, if any."),
    ("Source", 11, "Session, Email, Teams, Calendar: where it was found."),
]
DONE_CALC = [
    ("Week of", 11, '=IF($A{r}="","",$A{r}-WEEKDAY($A{r},3))'),
    ("This week", 9, '=IF($A{r}="","",IF($F{r}=AsOf-WEEKDAY(AsOf,3),"Yes",""))'),
    ("Rank key", 10, '=IF($G{r}="Yes",$A{r}+ROW()/100000,"")'),
]

ANS = "Answers"
ANS_INPUTS = [
    ("ID", 9, "Q-0001, Q-0002 ..."), ("Date", 11, ""), ("Question", 44, "As asked, minus anything personal."),
    ("Kind", 9, "Answer = traced to a source. Routed = sent to a person or resource. Reuse = an earlier answer given again (put its ID in Ref)."),
    ("Answer or route", 50, ""), ("Source", 30, "Link or document the answer traces to, or the person routed to."),
    ("Asked by", 16, ""), ("Ref", 9, "For Reuse: the Q ID reused."),
]
ANS_CALC = [("Times reused", 10, '=IF($A{r}="","",COUNTIFS($H$2:$H$%d,$A{r},$D$2:$D$%d,"Reuse"))' % (R, R))]

REV = "Reviews"
REV_INPUTS = [
    ("Date", 11, ""), ("Artifact", 40, "File name or link."), ("Author", 16, ""),
    ("Passed", 8, "Checks passed (of 8)."), ("Failed", 8, "Checks failed."),
    ("Verdict", 12, "Ready, or Fix first."), ("Top fix", 60, "The single most important fix."),
]
CHG = "Changes"
CHG_INPUTS = [
    ("Date", 11, ""), ("What changed", 40, ""), ("From", 36, ""), ("To", 36, ""),
    ("References updated", 30, "Where links were fixed."), ("Approved by", 16, ""),
]
TOP = "Topics"
TOP_INPUTS = [
    ("Topic", 18, "Short slug, lowercase, hyphens. Used everywhere else."), ("Name", 32, ""), ("Owner", 18, ""),
    ("Forum", 13, "Front door, Standup or Council: where its decisions get made."),
    ("Jira label", 14, "Label or key prefix that ties issues to it."), ("Status", 10, "Active, Paused, Closed."),
    ("Notes doc", 40, "OneDrive path to its running notes."),
]
TOP_CALC = [
    ("Open items", 10, '=IF($A{r}="","",COUNTIFS(Inventory!$D:$D,$A{r},Inventory!$K:$K,"Open")+COUNTIFS(Inventory!$D:$D,$A{r},Inventory!$K:$K,"Unconfirmed"))'),
    ("Jira issues", 10, '=IF($A{r}="","",COUNTIFS(Jira!$L:$L,$A{r})-COUNTIFS(Jira!$L:$L,$A{r},Jira!$M:$M,"Closed"))'),
    ("Jira attention", 11, '=IF($A{r}="","",COUNTIFS(Jira!$L:$L,$A{r},Jira!$P:$P,"Critical")+COUNTIFS(Jira!$L:$L,$A{r},Jira!$P:$P,"Warning"))'),
]
PEO = "People"
PEO_INPUTS = [
    ("Name", 20, ""), ("Role", 26, ""), ("Team", 20, ""), ("Works with me on", 30, "Topics, comma-separated. Support Guide routes by this."),
    ("How they work", 40, "Facts only: prefers Teams, wants a one-pager before Council. Nothing evaluative; that goes in Private."),
    ("Source", 18, ""), ("Last updated", 12, ""),
]

COMMANDS = [
    ("start my day", "Refresh Jira if the snapshot is stale, read the Dashboard, sweep yesterday's email, Teams and calendar, and give me the Needs You list plus anything worth logging.", "Daily"),
    ("refresh dashboard", "Pull Jira through the connector (or the newest CSV export), rewrite the Jira sheet, stamp the snapshot.", "Daily"),
    ("log this: <note>", "Capture a note into the Inventory as New, Know or Decision, with source, channel and confidence.", "Inventory"),
    ("add note to <topic>: <note>", "Same as log this, filed against a named topic.", "Inventory"),
    ("confirm <INV-id>", "Append a Confirmed row for a second-hand item.", "Inventory"),
    ("decide <INV-id>: <outcome>", "Close an open decision or conflict by appending a Resolved row.", "Inventory"),
    ("what's open on <topic>", "Open decisions, unconfirmed items, conflicts and Jira issues for one topic.", "Inventory"),
    ("done: <accomplishment>", "Append to the Done log under today.", "Reporting"),
    ("draft weekly report", "Build this week's report from the logs, email, Teams and calendar. Word draft, never sent.", "Reporting"),
    ("prep for <meeting>", "Agenda from open items and Jira issues for the topics that forum owns. Word draft.", "Reporting"),
    ("review this", "Run the Review Gate. Report what passes, what fails and the fix. Never rewrite.", "Quality"),
    ("support: <question>", "Answer from the Answers log or a traceable source, or route to a named person. Log it.", "Quality"),
    ("draft Jira update for <KEY>", "Write a status comment for that issue as a draft. Never posted.", "Jira"),
    ("what's stale in Jira", "Issues past their stage's staleness limit, worst first, with owner.", "Jira"),
    ("move <file> to <folder>", "Move it, fix every reference, log it on Changes.", "Upkeep"),
    ("check integrity", "Scan the workbook for broken refs, duplicate IDs, unmapped statuses, and anything that looks like customer data.", "Upkeep"),
]


# ---------------------------------------------------------------- sample data
def d(offset):
    return SAMPLE_AS_OF + dt.timedelta(days=offset)


SAMPLE_INV = [
    # ID, offset, Type, Topic, Summary, From, Channel, Confidence, Ref, Jira
    ("INV-0001", -24, "New", "council", "AI Council moves to biweekly through Q4; next sitting Oct 8.", "M. Okafor", "Meeting", "Confirmed", "", ""),
    ("INV-0002", -21, "Know", "mrm", "Model Risk now wants a validation plan at Design exit, not Approval.", "R. Chen", "Email", "Confirmed", "", ""),
    ("INV-0003", -19, "Decision", "call-summary", "Go / no-go on expanding call summarization from 40 to 400 agents.", "D. Patel", "Meeting", "Confirmed", "", "AIUC-101"),
    ("INV-0004", -17, "New", "vendor-copilot", "Vendor offering a 90-day no-cost pilot of agent assist for collections.", "S. Ruiz", "Email", "Confirmed", "", ""),
    ("INV-0005", -14, "Know", "genai-policy", "GenAI usage policy v3 heard to ban customer data in prompts outright.", "T. Nguyen", "Teams", "Unconfirmed", "", ""),
    ("INV-0006", -12, "Resolved", "call-summary", "Approved: expand to 400 agents, with weekly QA sampling for 6 weeks.", "AI Council", "Meeting", "Confirmed", "INV-0003", "AIUC-101"),
    ("INV-0007", -11, "Decision", "complaint-triage", "Decide whether complaint triage routes to humans only or auto-closes low-severity.", "L. Brooks", "Meeting", "Confirmed", "", "AIUC-102"),
    ("INV-0008", -10, "Confirmed", "genai-policy", "Policy v3 confirmed by Compliance: no customer data in prompts.", "T. Nguyen", "Email", "Confirmed", "INV-0005", ""),
    ("INV-0009", -9, "Decision", "fraud-alerts", "Fund a second data engineer for fraud alert prioritization, or slip Design by a month.", "K. Ito", "Meeting", "Confirmed", "", "AIUC-103"),
    ("INV-0010", -8, "Know", "kyc-extract", "KYC extraction vendor SOC 2 report expires Nov 30.", "Procurement", "Email", "Confirmed", "", "AIUC-104"),
    ("INV-0011", -7, "New", "council", "Council wants a one-page value tracker for every use case in Scale.", "M. Okafor", "Meeting", "Confirmed", "", ""),
    ("INV-0012", -6, "Know", "mrm", "MRM may add a bias test requirement for any credit-adjacent model.", "R. Chen", "Call", "Unconfirmed", "", ""),
    ("INV-0013", -5, "Conflict", "fraud-alerts", "Jira shows fraud alert model in Design; vendor says build started. Inventory stands until confirmed.", "Vendor PM", "Email", "Unconfirmed", "INV-0009", "AIUC-103"),
    ("INV-0014", -4, "Decision", "vendor-copilot", "Accept the vendor pilot or run a competitive eval first.", "S. Ruiz", "Email", "Confirmed", "", ""),
    ("INV-0015", -3, "New", "chat-deflection", "Chat deflection hit 31% containment in week 2, above the 25% target.", "Digital team", "Teams", "Unconfirmed", "", "AIUC-108"),
    ("INV-0016", -2, "Decision", "council", "Pick the Q1 intake cutoff date so the Council can size capacity.", "M. Okafor", "Meeting", "Confirmed", "", ""),
    ("INV-0017", -1, "Know", "kyc-extract", "KYC extraction accuracy on passports dropped to 91% after the vendor model update.", "QA", "Document", "Confirmed", "", "AIUC-104"),
    ("INV-0018", 0, "New", "complaint-triage", "Complaints team can provide 3 months of labelled data by Oct 15.", "L. Brooks", "Teams", "Unconfirmed", "", "AIUC-102"),
]

SAMPLE_JIRA = [
    # Key, Summary, Status, Type, Priority, Assignee, created, updated, due, flagged, labels, topic
    ("AIUC-101", "Contact center call summarization", "Scaling", "Epic", "High", "D. Patel", -160, -3, 30, "", "genai", "call-summary"),
    ("AIUC-102", "Complaint triage and routing", "Discovery", "Epic", "High", "L. Brooks", -70, -1, 20, "", "nlp", "complaint-triage"),
    ("AIUC-103", "Fraud alert prioritization", "Design", "Epic", "Highest", "K. Ito", -95, -18, -4, "Y", "fraud", "fraud-alerts"),
    ("AIUC-104", "KYC document extraction", "In Delivery", "Epic", "High", "A. Silva", -130, -9, 25, "", "vendor", "kyc-extract"),
    ("AIUC-105", "Collections outreach timing", "Triage", "Epic", "Medium", "Sample PM", -20, -12, None, "", "ml", "vendor-copilot"),
    ("AIUC-106", "Branch staffing forecast", "Value Tracking", "Epic", "Medium", "J. Moore", -300, -20, None, "", "forecast", ""),
    ("AIUC-107", "Marketing copy assistant", "Approval", "Epic", "Medium", "P. Shah", -60, -16, 10, "", "genai", ""),
    ("AIUC-108", "Chat deflection FAQ assistant", "Scaling", "Epic", "High", "Digital team", -200, -2, None, "", "genai", "chat-deflection"),
    ("AIUC-109", "Wire fraud anomaly detection", "Waiting for Vendor", "Epic", "High", "K. Ito", -45, -6, None, "", "fraud", "fraud-alerts"),
    ("AIUC-110", "Statement insight summaries", "Intake", "Story", "Low", "Sample PM", -5, -5, None, "", "genai", ""),
    ("AIUC-111", "Loan document pre-fill", "Design", "Epic", "Medium", "A. Silva", -50, -4, 40, "", "ocr", ""),
    ("AIUC-112", "Teller balancing assistant", "Declined", "Epic", "Low", "J. Moore", -90, -30, None, "", "", ""),
    ("AIUC-113", "ATM cash forecasting", "Value Tracking", "Epic", "Medium", "J. Moore", -400, -10, None, "", "forecast", ""),
    ("AIUC-114", "Dispute intake summarizer", "Triage", "Epic", "High", "L. Brooks", -15, -2, None, "", "genai", "complaint-triage"),
    ("AIUC-115", "RM email auto-drafting", "Discovery", "Epic", "Medium", "Sample PM", -35, -13, None, "", "genai", ""),
    ("AIUC-116", "HR policy chatbot", "In Review", "Epic", "Low", "P. Shah", -40, -8, -1, "", "genai", "genai-policy"),
]

SAMPLE_DONE = [
    (-38, "Ran first front-door triage; 6 ideas in, 2 declined with reasons logged.", "council", "", "Session"),
    (-36, "Published the eight-stage operating model to the team SharePoint.", "council", "", "Session"),
    (-33, "Closed MRM questions on call summarization validation plan.", "call-summary", "AIUC-101", "Email"),
    (-31, "Set baseline for complaint triage: 4.2 day median time to route.", "complaint-triage", "AIUC-102", "Session"),
    (-27, "Got Procurement to start vendor risk review for KYC extraction.", "kyc-extract", "AIUC-104", "Email"),
    (-25, "Council approved chat deflection scale-up to all web traffic.", "chat-deflection", "AIUC-108", "Calendar"),
    (-24, "Retired the old intake spreadsheet; Jira is now the only intake path.", "council", "", "Session"),
    (-20, "Agreed staleness thresholds per stage with delivery leads.", "council", "", "Teams"),
    (-19, "Drafted the go/no-go memo for call summarization expansion.", "call-summary", "AIUC-101", "Session"),
    (-17, "Mapped GenAI policy v3 controls to every in-flight GenAI use case.", "genai-policy", "", "Session"),
    (-13, "Call summarization expansion approved by Council (INV-0006).", "call-summary", "AIUC-101", "Calendar"),
    (-12, "Declined teller balancing assistant; value case under $50K.", "council", "AIUC-112", "Session"),
    (-11, "Wrote the data request for complaint triage labelled history.", "complaint-triage", "AIUC-102", "Email"),
    (-10, "Ran Review Gate on the Q4 roadmap deck; fixed 3 MECE gaps.", "council", "", "Session"),
    (-6, "Confirmed GenAI policy v3 wording with Compliance (INV-0008).", "genai-policy", "", "Email"),
    (-4, "Unblocked loan pre-fill architecture review with Enterprise Architecture.", "", "AIUC-111", "Teams"),
    (-4, "Built the value tracker template the Council asked for.", "council", "", "Session"),
    (-3, "Escalated fraud alert staffing gap to Council agenda.", "fraud-alerts", "AIUC-103", "Session"),
    (-2, "Chat deflection week-2 readout sent to Digital leadership.", "chat-deflection", "AIUC-108", "Email"),
    (-1, "Logged KYC accuracy regression and opened vendor ticket.", "kyc-extract", "AIUC-104", "Session"),
    (0, "Completed intake review for statement insight summaries.", "", "AIUC-110", "Session"),
]

SAMPLE_ANS = [
    ("Q-0001", -30, "Who approves a new GenAI use case?", "Answer", "The AI Council at the Approval gate; the PM owner brings it.", "Operating model, gate table", "B. Ford", ""),
    ("Q-0002", -26, "Can we use customer emails to fine-tune a model?", "Routed", "Routed to Compliance (T. Nguyen). Not answered here.", "T. Nguyen", "S. Ruiz", ""),
    ("Q-0003", -21, "What does Model Risk need at Design exit?", "Answer", "Validation plan, monitoring design, audit trail spec.", "INV-0002; MRM standard 4.3", "P. Shah", ""),
    ("Q-0004", -15, "Who approves a new GenAI use case?", "Reuse", "Same as Q-0001.", "Q-0001", "A. Silva", "Q-0001"),
    ("Q-0005", -12, "How long should Triage take?", "Answer", "Seven days before it is flagged stale.", "Config sheet, stage table", "L. Brooks", ""),
    ("Q-0006", -8, "Where do I submit a new AI idea?", "Answer", "Jira intake form in project AIUC.", "AIUC intake form", "New hire", ""),
    ("Q-0007", -5, "What does Model Risk need at Design exit?", "Reuse", "Same as Q-0003.", "Q-0003", "K. Ito", "Q-0003"),
    ("Q-0008", -1, "Can a vendor model go to Scale before SOC 2 renewal?", "Routed", "Routed to Procurement / Third-Party Risk.", "Third-Party Risk team", "A. Silva", ""),
]

SAMPLE_REV = [
    (-22, "Q4 AI roadmap deck v2", "Sample PM", 5, 3, "Fix first", "Sections 2 and 4 overlap on capacity; merge them so the asks are MECE."),
    (-10, "Q4 AI roadmap deck v3", "Sample PM", 8, 0, "Ready", ""),
    (-6, "Fraud alert staffing ask", "K. Ito", 6, 2, "Fix first", "The ask has no date or owner; say who decides by when."),
    (-2, "Chat deflection week-2 readout", "Digital team", 7, 1, "Ready", "Containment number needs its source and date."),
]
SAMPLE_CHG = [
    (-24, "Retired old intake tracker", "OneDrive/AI/Intake.xlsx", "Archive/Intake-2026Q3.xlsx", "Topics: council notes doc; Answers Q-0006", "Sample PM"),
    (-9, "Moved fraud notes into topic doc", "Documents/fraud-notes.docx", "AI-OS/Topics/fraud-alerts.docx", "Topics sheet row fraud-alerts", "Sample PM"),
]
SAMPLE_TOP = [
    ("council", "AI Council and portfolio governance", "M. Okafor", "Council", "", "Active", "AI-OS/Topics/council.docx"),
    ("call-summary", "Contact center call summarization", "D. Patel", "Council", "AIUC-101", "Active", "AI-OS/Topics/call-summary.docx"),
    ("complaint-triage", "Complaint triage and routing", "L. Brooks", "Standup", "AIUC-102", "Active", "AI-OS/Topics/complaint-triage.docx"),
    ("fraud-alerts", "Fraud alert prioritization", "K. Ito", "Council", "fraud", "Active", "AI-OS/Topics/fraud-alerts.docx"),
    ("kyc-extract", "KYC document extraction", "A. Silva", "Standup", "AIUC-104", "Active", "AI-OS/Topics/kyc-extract.docx"),
    ("mrm", "Model Risk Management requirements", "R. Chen", "Council", "", "Active", "AI-OS/Topics/mrm.docx"),
    ("genai-policy", "GenAI usage policy", "T. Nguyen", "Council", "", "Active", "AI-OS/Topics/genai-policy.docx"),
    ("vendor-copilot", "Vendor agent-assist pilot", "S. Ruiz", "Front door", "", "Active", "AI-OS/Topics/vendor-copilot.docx"),
    ("chat-deflection", "Chat deflection FAQ assistant", "Digital team", "Standup", "AIUC-108", "Active", "AI-OS/Topics/chat-deflection.docx"),
]
SAMPLE_PEO = [
    ("M. Okafor", "AI Council chair", "Enterprise AI", "council", "Wants decisions framed as options with a recommendation.", "Meeting", -24),
    ("R. Chen", "Model Risk lead", "Model Risk Management", "mrm, fraud-alerts", "Prefers written questions by email; replies in 2 days.", "Email", -21),
    ("D. Patel", "Contact center product owner", "Customer Care", "call-summary", "Teams first; likes a weekly number.", "Teams", -19),
    ("T. Nguyen", "Compliance partner, GenAI", "Compliance", "genai-policy", "Needs the policy clause cited, not paraphrased.", "Email", -10),
    ("K. Ito", "Fraud analytics lead", "Fraud Operations", "fraud-alerts", "", "Meeting", -9),
    ("L. Brooks", "Complaints operations manager", "Customer Care", "complaint-triage", "", "Meeting", -11),
]


# ---------------------------------------------------------------- builders
def head_cell(ws, col, title, width, note, computed):
    c = ws.cell(row=1, column=col, value=title)
    c.font = f(10, True, INK if not computed else INK2)
    c.fill = CALC_HEAD if computed else INPUT_HEAD
    c.alignment = Alignment(vertical="center", wrap_text=True)
    c.border = BOTTOM
    if note or computed:
        c.comment = Comment(("Computed. Cowork never writes here. " if computed else "") + (note or ""), "AI-OS")
    ws.column_dimensions[get_column_letter(col)].width = width


def log_sheet(wb, name, inputs, calc, rows, data, date_cols=(), int_cols=()):
    ws = wb.create_sheet(name)
    for i, (t, w, n) in enumerate(inputs, 1):
        head_cell(ws, i, t, w, n, False)
    for j, (t, w, formula) in enumerate(calc, len(inputs) + 1):
        head_cell(ws, j, t, w, "", True)
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "B2"
    last = get_column_letter(len(inputs) + len(calc))
    ws.auto_filter.ref = "A1:%s%d" % (last, rows + 1)
    for r in range(2, rows + 2):
        for j, (t, w, formula) in enumerate(calc, len(inputs) + 1):
            c = ws.cell(row=r, column=j, value=formula.replace("{r}", str(r)))
            c.fill = CALC_CELL
            c.font = f(10, color=INK2)
        for col in date_cols:
            ws.cell(row=r, column=col).number_format = "yyyy-mm-dd"
        for col in range(1, len(inputs) + 1):
            ws.cell(row=r, column=col).font = f(10)
    for r, row in enumerate(data, 2):
        for col, v in enumerate(row, 1):
            if v != "" and v is not None:
                ws.cell(row=r, column=col, value=v)
    return ws


def add_list_validation(ws, col_letter, options, rows):
    dv = DataValidation(type="list", formula1='"%s"' % ",".join(options), allow_blank=True,
                        showErrorMessage=True, errorTitle="Not on the list", error="Pick one of: " + ", ".join(options))
    ws.add_data_validation(dv)
    dv.add("%s2:%s%d" % (col_letter, col_letter, rows + 1))


def status_formatting(ws, rng):
    for label, (fill, text) in STATUS.items():
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"%s"' % label],
                                      fill=PatternFill("solid", fgColor=fill), font=Font(name=FONT, color=text, bold=True)))


def name(wb, nm, ref):
    wb.defined_names[nm] = DefinedName(nm, attr_text=ref)


def build_config(wb, sample):
    ws = wb.create_sheet("Config")
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 44
    ws.column_dimensions["C"].width = 70
    ws["A1"] = "Config"
    ws["A1"].font = f(16, True, BRAND)
    ws["A2"] = "Blue cells are yours to set once. Grey cells are written by Cowork or computed. Nothing here is a secret: no tokens or passwords, ever."
    ws["A2"].font = f(10, color=INK3, italic=True)
    ws["A3"], ws["A10"], ws["A16"] = "Settings", "Thresholds", "Jira snapshot (written by Cowork on every refresh)"
    for c in ("A3", "A10", "A16"):
        ws[c].font = f(11, True)
    for nm, (row, label, live, smp, note) in CONFIG_CELLS.items():
        ws.cell(row=row, column=1, value=label).font = f(10)
        v = smp if sample else live
        c = ws.cell(row=row, column=2, value=v)
        writer = nm.startswith("Snapshot") or nm == "AsOf"
        c.fill = CALC_CELL if writer else INPUT_HEAD
        c.font = f(10, color=INK2 if writer else "1F3FBF")
        if nm in ("SampleAsOf", "AsOf"):
            c.number_format = "yyyy-mm-dd"
        if nm == "SnapshotAt":
            c.number_format = "yyyy-mm-dd hh:mm"
        ws.cell(row=row, column=3, value=note).font = f(9, color=INK3)
        name(wb, nm, "Config!$B$%d" % row)
    ws.cell(row=15, column=1, value="Snapshot age (days)").font = f(10)
    c = ws.cell(row=15, column=2, value='=IF(SnapshotAt="","",ROUND(IF(SampleAsOf="",NOW(),SampleAsOf+TIME(9,0,0))-SnapshotAt,1))')
    c.fill, c.font = CALC_CELL, f(10, color=INK2)
    name(wb, "SnapshotAge", "Config!$B$15")

    ws.cell(row=STAGE_ROW0 - 2, column=1, value="Stages (the operating model's eight)").font = f(11, True)
    for col, t in enumerate(("Stage", "Stale after (days)", "Gate owner"), 1):
        c = ws.cell(row=STAGE_ROW0 - 1, column=col, value=t)
        c.font, c.fill = f(10, True), INPUT_HEAD
    for i, (s, days, owner) in enumerate(STAGES):
        ws.cell(row=STAGE_ROW0 + i, column=1, value=s).font = f(10)
        ws.cell(row=STAGE_ROW0 + i, column=2, value=days).font = f(10, color="1F3FBF")
        ws.cell(row=STAGE_ROW0 + i, column=3, value=owner).font = f(10)
    end = STAGE_ROW0 + len(STAGES) - 1
    name(wb, "StageName", "Config!$A$%d:$A$%d" % (STAGE_ROW0, end))
    name(wb, "StageStale", "Config!$B$%d:$B$%d" % (STAGE_ROW0, end))

    ws.column_dimensions["E"].width = 24
    ws.column_dimensions["F"].width = 14
    ws.cell(row=MAP_ROW0 - 2, column=5, value="Jira status → stage map").font = f(11, True)
    for col, t in ((5, "Jira status (exact)"), (6, "Stage")):
        c = ws.cell(row=MAP_ROW0 - 1, column=col, value=t)
        c.font, c.fill = f(10, True), INPUT_HEAD
    for i, (st, sg) in enumerate(STATUS_MAP):
        ws.cell(row=MAP_ROW0 + i, column=5, value=st).font = f(10, color="1F3FBF")
        ws.cell(row=MAP_ROW0 + i, column=6, value=sg).font = f(10, color="1F3FBF")
    mend = MAP_ROW0 + MAP_ROWS - 1
    name(wb, "MapStatus", "Config!$E$%d:$E$%d" % (MAP_ROW0, mend))
    name(wb, "MapStage", "Config!$F$%d:$F$%d" % (MAP_ROW0, mend))
    ws.cell(row=mend + 1, column=5, value="Add your workflow's statuses in the blank rows. Stage must be one of the eight, or Closed.").font = f(9, color=INK3, italic=True)
    dv = DataValidation(type="list", formula1='"%s"' % ",".join([s for s, _, _ in STAGES] + ["Closed"]), allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("F%d:F%d" % (MAP_ROW0, mend))
    return ws


def tile(ws, row, col, end, label, value_formula, sub_formula, fmt="0"):
    for rr in range(row, row + 3):
        for cc in range(col, end + 1):
            ws.cell(row=rr, column=cc).fill = TILE
        if end > col:
            ws.merge_cells(start_row=rr, start_column=col, end_row=rr, end_column=end)
    a = ws.cell(row=row, column=col, value=label)
    a.font = f(9, True, INK3)
    a.alignment = Alignment(indent=1, vertical="bottom")
    b = ws.cell(row=row + 1, column=col, value=value_formula)
    b.font = f(22, True, INK)
    b.number_format = fmt
    b.alignment = Alignment(indent=1, horizontal="left", vertical="center")
    s = ws.cell(row=row + 2, column=col, value=sub_formula)
    s.font = f(9, color=INK2)
    s.alignment = Alignment(indent=1, vertical="top", wrap_text=True)


def section(ws, row, col, text, sub=None):
    c = ws.cell(row=row, column=col, value=text)
    c.font = f(12, True, INK)
    if sub:
        s = ws.cell(row=row, column=col + 3, value=sub)
        s.font = f(9, color=INK3, italic=True)


def table_head(ws, row, col, titles):
    for i, t in enumerate(titles):
        c = ws.cell(row=row, column=col + i, value=t)
        c.font = f(9, True, INK3)
        c.border = BOTTOM


def value_labels():
    dl = DataLabelList()
    dl.showVal = True
    dl.showSerName = dl.showCatName = dl.showLegendKey = dl.showPercent = False
    return dl


def build_dashboard(wb):
    ws = wb.create_sheet("Dashboard", 0)
    ws.sheet_view.showGridLines = False
    widths = {"A": 2, "B": 4, "C": 11, "D": 11, "E": 13, "F": 46, "G": 12, "H": 10, "I": 11, "J": 32, "K": 30, "L": 2}
    for k, v in widths.items():
        ws.column_dimensions[k].width = v

    ws["B1"] = "AI Operating System"
    ws["B1"].font = f(20, True, BRAND)
    ws.row_dimensions[1].height = 30
    ws["B2"] = '="As of "&TEXT(AsOf,"ddd d mmm yyyy")&IF(OwnerName="","","  ·  "&OwnerName)'
    ws["B2"].font = f(10, color=INK2)
    ws["F2"] = ('=IF(SampleAsOf<>"","SAMPLE DATA. Open AI-OS.xlsx for the blank workbook.",'
                'IF(SnapshotAt="","No Jira snapshot yet. Say: refresh dashboard",'
                'IF(SnapshotAge>SnapshotMaxAge,"Jira snapshot is "&SnapshotAge&" days old. Say: refresh dashboard","Jira snapshot "&TEXT(SnapshotAt,"d mmm hh:mm")&" from "&SnapshotSource)))')
    ws["F2"].font = f(10, True, "7A5200")
    ws.merge_cells("F2:K2")
    ws.conditional_formatting.add("F2:K2", FormulaRule(formula=['OR(SampleAsOf<>"",SnapshotAt="",SnapshotAge>SnapshotMaxAge)'], fill=BANNER))

    INVR, JR, DR = "Inventory!$K:$K", "Jira!$P:$P", "Done!$G:$G"
    r = 4
    tile(ws, r, 3, 5, "OPEN DECISIONS", '=COUNTIFS(Inventory!$K:$K,"Open",Inventory!$C:$C,"Decision")',
         '=COUNTIFS(Inventory!$K:$K,"Open",Inventory!$C:$C,"Decision",Inventory!$M:$M,"Critical")&" past "&DecisionCritical&" days"')
    tile(ws, r, 6, 6, "UNCONFIRMED", '=COUNTIF(%s,"Unconfirmed")' % INVR,
         '=COUNTIFS(Inventory!$K:$K,"Unconfirmed",Inventory!$M:$M,"Warning")&" older than "&UnconfirmedWarn&" days"')
    tile(ws, r, 7, 9, "OPEN CONFLICTS", '=COUNTIFS(Inventory!$K:$K,"Open",Inventory!$C:$C,"Conflict")', '="inventory stands until settled"')
    tile(ws, r, 10, 10, "JIRA NEEDING ATTENTION", '=COUNTIF(%s,"Critical")+COUNTIF(%s,"Warning")' % (JR, JR),
         '="of "&(COUNTA(Jira!$A$2:$A$%d)-COUNTIF(Jira!$P:$P,"Closed"))&" in flight · "&COUNTIF(Jira!$P:$P,"Critical")&" critical"' % J)
    tile(ws, r, 11, 11, "DONE THIS WEEK", '=COUNTIF(Done!$G:$G,"Yes")',
         '=COUNTIF(Done!$F:$F,AsOf-WEEKDAY(AsOf,3)-7)&" last week · "&COUNTIF(Answers!$D:$D,"Reuse")&" answers reused"')
    ws.row_dimensions[r + 1].height = 32

    # Needs you: inventory
    r = 8
    section(ws, r, 2, "Needs you", "Open decisions, conflicts and unconfirmed items, worst first. Paste the last column into Cowork.")
    table_head(ws, r + 1, 2, ["#", "ID", "Type", "Topic", "Summary", "Age (d)", "Severity", "From", "Say this"])
    N = 10
    for k in range(1, N + 1):
        rr = r + 1 + k
        ws.cell(row=rr, column=2, value=k).font = f(9, color=INK3)
        idc = "$C%d" % rr
        ws.cell(row=rr, column=3, value='=IFERROR(INDEX(Inventory!$A$2:$A$%d,MATCH(LARGE(Inventory!$N$2:$N$%d,$B%d),Inventory!$N$2:$N$%d,0)),"")' % (R, R, rr, R))
        for col, src in ((4, "C"), (5, "D"), (6, "E"), (7, "L"), (8, "M"), (9, "F"), (10, "O")):
            txt = "" if src == "L" else '&""'  # &"" keeps a blank source blank instead of 0
            ws.cell(row=rr, column=col, value='=IF(%s="","",INDEX(Inventory!$%s$2:$%s$%d,MATCH(%s,Inventory!$A$2:$A$%d,0))%s)' % (idc, src, src, R, idc, R, txt))
        for col in range(2, 11):
            c = ws.cell(row=rr, column=col)
            c.border = BOTTOM
            if col != 2:
                c.font = f(10, color=INK if col != 10 else BRAND)
            c.alignment = Alignment(vertical="top", wrap_text=(col == 6), horizontal="center" if col == 7 else None)
    ws.cell(row=r + 2, column=11, value='=IF(COUNT(Inventory!$N$2:$N$%d)=0,"Nothing open. Inventory is clear.",IF(COUNT(Inventory!$N$2:$N$%d)>%d,"+"&(COUNT(Inventory!$N$2:$N$%d)-%d)&" more on the Inventory sheet",""))' % (R, R, N, R, N)).font = f(9, color=INK3, italic=True)
    status_formatting(ws, "H%d:H%d" % (r + 2, r + 1 + N))

    # Jira attention
    r = 21
    section(ws, r, 2, "Jira needing attention", "Flagged, past due, unmapped, or idle past the stage limit on the Config sheet.")
    table_head(ws, r + 1, 2, ["#", "Key", "Stage", "Assignee", "Summary", "Idle (d)", "Health", "", "Why", "Say this"])
    for k in range(1, N + 1):
        rr = r + 1 + k
        ws.cell(row=rr, column=2, value=k).font = f(9, color=INK3)
        kc = "$C%d" % rr
        ws.cell(row=rr, column=3, value='=IFERROR(INDEX(Jira!$A$2:$A$%d,MATCH(LARGE(Jira!$R$2:$R$%d,$B%d),Jira!$R$2:$R$%d,0)),"")' % (J, J, rr, J))
        for col, src in ((4, "M"), (5, "F"), (6, "B"), (7, "N"), (8, "P"), (10, "Q"), (11, "S")):
            txt = "" if src == "N" else '&""'
            ws.cell(row=rr, column=col, value='=IF(%s="","",INDEX(Jira!$%s$2:$%s$%d,MATCH(%s,Jira!$A$2:$A$%d,0))%s)' % (kc, src, src, J, kc, J, txt))
        for col in range(2, 12):
            c = ws.cell(row=rr, column=col)
            c.border = BOTTOM
            if col != 2:
                c.font = f(10, color=INK if col != 11 else BRAND)
            c.alignment = Alignment(vertical="top", wrap_text=(col in (6, 10)), horizontal="center" if col == 7 else None)
    status_formatting(ws, "H%d:H%d" % (r + 2, r + 1 + N))

    # Pipeline by stage
    r = 34
    section(ws, r, 2, "Pipeline by stage", "Open Jira issues per stage.")
    table_head(ws, r + 1, 3, ["Stage", "Open", "Attention", "Stale after"])
    stages = [s for s, _, _ in STAGES] + ["Unmapped"]
    for i, s in enumerate(stages):
        rr = r + 2 + i
        ws.cell(row=rr, column=3, value=s).font = f(10)
        ws.cell(row=rr, column=4, value='=COUNTIF(Jira!$M:$M,$C%d)' % rr).font = f(10)
        ws.cell(row=rr, column=5, value='=COUNTIFS(Jira!$M:$M,$C%d,Jira!$P:$P,"Critical")+COUNTIFS(Jira!$M:$M,$C%d,Jira!$P:$P,"Warning")' % (rr, rr)).font = f(10)
        ws.cell(row=rr, column=6, value=('=INDEX(StageStale,MATCH($C%d,StageName,0))&" days"' % rr) if s != "Unmapped" else "add to Config map").font = f(10, color=INK3)
        for col in range(3, 7):
            ws.cell(row=rr, column=col).border = BOTTOM
            if col in (4, 5):
                ws.cell(row=rr, column=col).alignment = Alignment(horizontal="center")
    ch = BarChart()
    ch.type, ch.style = "bar", 1
    ch.title = None
    ch.legend = None
    ch.y_axis.majorGridlines = None
    ch.y_axis.delete = True
    ch.x_axis.scaling.orientation = "maxMin"
    ch.add_data(Reference(ws, min_col=4, min_row=r + 1, max_row=r + 1 + len(stages)), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=3, min_row=r + 2, max_row=r + 1 + len(stages)))
    ch.series[0].graphicalProperties.solidFill = SERIES
    ch.series[0].graphicalProperties.line.noFill = True
    ch.gapWidth = 60
    ch.dataLabels = value_labels()
    ch.height, ch.width = 6.2, 11
    ws.add_chart(ch, "G%d" % (r + 2))

    # Done this week + weekly trend
    r = 47
    section(ws, r, 2, "Done this week", "Feeds the weekly report. Say: done: <what you finished>")
    table_head(ws, r + 1, 3, ["Date", "Topic", "Accomplishment"])
    for k in range(1, 9):
        rr = r + 1 + k
        dc = "$C%d" % rr
        ws.cell(row=rr, column=3, value='=IFERROR(INDEX(Done!$A$2:$A$%d,MATCH(LARGE(Done!$H$2:$H$%d,%d),Done!$H$2:$H$%d,0)),"")' % (R, R, k, R)).number_format = "ddd d mmm"
        ws.cell(row=rr, column=4, value='=IF(%s="","",INDEX(Done!$C$2:$C$%d,MATCH(LARGE(Done!$H$2:$H$%d,%d),Done!$H$2:$H$%d,0))&"")' % (dc, R, R, k, R))
        ws.cell(row=rr, column=5, value='=IF(%s="","",INDEX(Done!$B$2:$B$%d,MATCH(LARGE(Done!$H$2:$H$%d,%d),Done!$H$2:$H$%d,0))&"")' % (dc, R, R, k, R))
        ws.merge_cells(start_row=rr, start_column=5, end_row=rr, end_column=8)
        for col in range(3, 9):
            c = ws.cell(row=rr, column=col)
            c.border = BOTTOM
            c.font = f(10)
            c.alignment = Alignment(vertical="top", horizontal="left")
    ws.cell(row=r + 2, column=10, value='=IF(COUNTIF(Done!$G:$G,"Yes")=0,"Nothing logged this week yet.",IF(COUNTIF(Done!$G:$G,"Yes")>8,"+"&(COUNTIF(Done!$G:$G,"Yes")-8)&" more on the Done sheet",""))').font = f(9, color=INK3, italic=True)

    r = 58
    section(ws, r, 2, "Accomplishments per week", "Last eight weeks.")
    table_head(ws, r + 1, 3, ["Week of", "Done"])
    for i in range(8):
        rr = r + 2 + i
        c = ws.cell(row=rr, column=3, value="=AsOf-WEEKDAY(AsOf,3)-7*%d" % (7 - i))
        c.number_format = "d mmm"
        c.font = f(10)
        c.alignment = Alignment(horizontal="left")
        ws.cell(row=rr, column=4, value="=COUNTIF(Done!$F:$F,$C%d)" % rr).font = f(10)
    ch2 = BarChart()
    ch2.type, ch2.style = "col", 1
    ch2.legend = None
    ch2.y_axis.majorGridlines = None
    ch2.y_axis.delete = True
    ch2.add_data(Reference(ws, min_col=4, min_row=r + 1, max_row=r + 9), titles_from_data=True)
    ch2.set_categories(Reference(ws, min_col=3, min_row=r + 2, max_row=r + 9))
    ch2.series[0].graphicalProperties.solidFill = SERIES
    ch2.series[0].graphicalProperties.line.noFill = True
    ch2.gapWidth = 60
    ch2.dataLabels = value_labels()
    ch2.height, ch2.width = 5.5, 11
    ws.add_chart(ch2, "F%d" % (r + 1))

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return ws


def build_commands(wb):
    ws = wb.create_sheet("Commands")
    for i, (t, w) in enumerate((("Say this in Cowork", 30), ("What happens", 90), ("Group", 12)), 1):
        head_cell(ws, i, t, w, "", False)
    for r, row in enumerate(COMMANDS, 2):
        for c, v in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = f(10, bold=(c == 1), color=BRAND if c == 1 else INK)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"


def build_readme(wb, sample):
    ws = wb.create_sheet("Read Me")
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 110
    rows = [
        ("AI Operating System", None),
        ("What this is", "The system of record for your desk. Cowork appends rows to the log sheets; the Dashboard recomputes from them against today's date. Nothing on the Dashboard is typed by hand."),
        ("Which cells", "Blue headers are inputs. Grey headers and grey cells are formulas: never type over them. Add a row by filling the first empty row's blue columns. Never insert, delete or edit rows on a log sheet: append a correction instead."),
        ("Append-only", "Inventory, Done, Answers, Reviews and Changes are logs. A decision is closed by a new Resolved row pointing at it (Ref), a rumour by a Confirmed row. The old row stays. OneDrive version history covers the Jira sheet, the only sheet that is replaced wholesale."),
        ("Privacy", "Nothing from 1:1s, performance or career conversations goes in this workbook. That lives in AI-OS/Private. No customer data anywhere: case or ticket IDs only."),
        ("Sheets", None),
        ("Dashboard", "Needs You, Jira attention, pipeline by stage, this week's accomplishments."),
        ("Inventory", "Example row: INV-0019 | 2026-10-05 | Decision | fraud-alerts | Approve a second data engineer or slip Design a month | K. Ito | Meeting | Confirmed | | AIUC-103"),
        ("Jira", "Snapshot of the issues in scope. Rewritten by 'refresh dashboard'. Example: AIUC-103 | Fraud alert prioritization | Design | Epic | Highest | K. Ito | 2026-06-29 | 2026-09-14 | 2026-09-28 | Y | fraud | fraud-alerts"),
        ("Done", "Example row: 2026-10-05 | Got MRM sign-off on the call summarization validation plan | call-summary | AIUC-101 | Email"),
        ("Answers", "Support Guide log. Example: Q-0009 | 2026-10-05 | Who signs off a vendor model? | Routed | Routed to Third-Party Risk | Third-Party Risk team | A. Silva |"),
        ("Reviews", "One row per Review Gate run."),
        ("Changes", "One row per file move or rename, with the references fixed."),
        ("Topics", "One row per workstream. The slug in column A is the key every other sheet uses."),
        ("People", "Facts about how people work. Nothing evaluative."),
        ("Commands", "The phrases Cowork recognises."),
        ("Config", "Jira site and project, staleness limits, the status → stage map, the snapshot stamp."),
    ]
    if sample:
        rows.insert(1, ("SAMPLE", "This copy holds illustrative data dated around " + SAMPLE_AS_OF.isoformat() + ". Every age is measured from that date (Config › Sample data as-of). Use AI-OS.xlsx for real work."))
    for r, (a, b) in enumerate(rows, 1):
        ca = ws.cell(row=r, column=1, value=a)
        if b is None:
            ca.font = f(16 if r == 1 else 12, True, BRAND if r == 1 else INK)
            continue
        ca.font = f(10, True)
        cb = ws.cell(row=r, column=2, value=b)
        cb.font = f(10)
        cb.alignment = Alignment(wrap_text=True, vertical="top")
        ca.alignment = Alignment(vertical="top")


def build(sample):
    wb = Workbook()
    wb.remove(wb.active)
    inv = [(i, d(o), t, tp, s, fr, ch, cf, rf, jk) for i, o, t, tp, s, fr, ch, cf, rf, jk in SAMPLE_INV] if sample else []
    ws = log_sheet(wb, INV, INV_INPUTS, INV_CALC, LOG_ROWS, inv, date_cols=(2,))
    add_list_validation(ws, "C", ["New", "Know", "Decision", "Conflict", "Confirmed", "Resolved"], LOG_ROWS)
    add_list_validation(ws, "G", ["Meeting", "Email", "Teams", "Call", "Document", "Jira", "Session"], LOG_ROWS)
    add_list_validation(ws, "H", ["Confirmed", "Unconfirmed"], LOG_ROWS)
    status_formatting(ws, "M2:M%d" % (LOG_ROWS + 1))

    jira = [(k, s, st, ty, p, a, d(c), d(u), d(du) if du is not None else None, fl, lb, tp)
            for k, s, st, ty, p, a, c, u, du, fl, lb, tp in SAMPLE_JIRA] if sample else []
    ws = log_sheet(wb, JIRA, JIRA_INPUTS, JIRA_CALC, JIRA_ROWS, jira, date_cols=(7, 8, 9))
    status_formatting(ws, "P2:P%d" % (JIRA_ROWS + 1))

    done = [(d(o), a, t, j, s) for o, a, t, j, s in SAMPLE_DONE] if sample else []
    ws = log_sheet(wb, DONE, DONE_INPUTS, DONE_CALC, LOG_ROWS, done, date_cols=(1, 6))
    add_list_validation(ws, "E", ["Session", "Email", "Teams", "Calendar"], LOG_ROWS)

    ans = [(i, d(o), q, k, a, s, b, rf) for i, o, q, k, a, s, b, rf in SAMPLE_ANS] if sample else []
    ws = log_sheet(wb, ANS, ANS_INPUTS, ANS_CALC, LOG_ROWS, ans, date_cols=(2,))
    add_list_validation(ws, "D", ["Answer", "Routed", "Reuse"], LOG_ROWS)

    rev = [(d(x[0]),) + tuple(x[1:]) for x in SAMPLE_REV] if sample else []
    ws = log_sheet(wb, REV, REV_INPUTS, [], LOG_ROWS, rev, date_cols=(1,))
    add_list_validation(ws, "F", ["Ready", "Fix first"], LOG_ROWS)
    chg = [(d(x[0]),) + tuple(x[1:]) for x in SAMPLE_CHG] if sample else []
    log_sheet(wb, CHG, CHG_INPUTS, [], LOG_ROWS, chg, date_cols=(1,))
    log_sheet(wb, TOP, TOP_INPUTS, TOP_CALC, 200, SAMPLE_TOP if sample else [])
    peo = [x[:6] + (d(x[6]),) for x in SAMPLE_PEO] if sample else []
    log_sheet(wb, PEO, PEO_INPUTS, [], 500, peo, date_cols=(7,))
    build_commands(wb)
    build_config(wb, sample)
    build_readme(wb, sample)
    build_dashboard(wb)
    wb.active = 0
    wb.calculation.fullCalcOnLoad = True  # Excel recomputes on open; no stale cached values
    for w in wb.worksheets:
        w.sheet_properties.tabColor = {"Dashboard": BRAND, "Config": "8A91A0", "Read Me": "8A91A0", "Commands": "8A91A0"}.get(w.title, SERIES)
    path = os.path.join(OUT_DIR, "AI-OS-sample.xlsx" if sample else "AI-OS.xlsx")
    wb.save(path)
    return path


def zip_onedrive():
    root = os.path.join(HERE, "OneDrive")
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _, files in os.walk(root):
            for fn in sorted(files):
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, HERE))
    return ZIP_PATH


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    for s in (False, True):
        print("wrote", os.path.relpath(build(s), HERE))
    print("wrote", os.path.relpath(zip_onedrive(), HERE))
