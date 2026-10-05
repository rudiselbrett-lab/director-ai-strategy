#!/usr/bin/env python3
"""Build the AI Operating System workbook for Microsoft 365 Copilot Cowork.

Writes two files into OneDrive/Documents/AI-OS/:

  AI-OS.xlsx         blank, ready to go live
  AI-OS-sample.xlsx  the same workbook filled with illustrative data

and zips the OneDrive folder into ai-os-onedrive.zip for one-step copying.

Five dashboard tabs, linked to each other:

  Home           my desk: what needs me, what needs attention, what I did
  Portfolio      health, freshness, pipeline, WSJF against capacity, mix
  Weekly Status  RAG, then the three sittings: Intake, Standup, Council
  Gates          the eight stages, the tier clock, gate exceptions
  Use Case       one use case end to end, picked from a list

Every number on them is an Excel formula over the data sheets, so Cowork only
ever appends rows (or replaces the Use Cases snapshot). This script runs here,
not in Cowork. Run it again only if you change the workbook's structure.

    pip install openpyxl
    python3 build_workbook.py
"""

import datetime as dt
import os
import re
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

SAMPLE_AS_OF = dt.date(2026, 10, 2)   # a Friday, so the sample week is full
SITE_ANCHOR = dt.date(2026, 8, 11)    # the site's ANCHOR; its dates shift by the difference
SHIFT = (SAMPLE_AS_OF - SITE_ANCHOR).days

# ---------------------------------------------------------------- styles
FONT = "Arial"
INK, INK2, INK3 = "16181D", "4A5160", "646C7A"
BRAND = "6B2C91"
LINK = "0F56A5"
SERIES1, SERIES2 = "2A78D6", "EB6834"
HAIR = "E2E4E8"
INPUT_HEAD = PatternFill("solid", fgColor="E8EEF8")
CALC_HEAD = PatternFill("solid", fgColor="EDEDED")
CALC_CELL = PatternFill("solid", fgColor="F7F7F7")
TILE = PatternFill("solid", fgColor="F5F6F7")
NAV_ON = PatternFill("solid", fgColor=BRAND)
BANNER = PatternFill("solid", fgColor="FFF4D6")
# Reserved for state. Never used as a series colour.
RED, AMBER, GREEN, GREY = ("FBE3E3", "9B1C1C"), ("FFF1D0", "7A5200"), ("E2F4E2", "1D6B1D"), ("EDEDED", "4A5160")
STATE = {
    "Critical": RED, "Overdue": RED, "Red": RED, "Stale": RED,
    "Warning": AMBER, "At risk": AMBER, "Amber": AMBER, "Aging": AMBER, "Over": AMBER, "Unmapped": AMBER, "Below line": AMBER,
    "On track": GREEN, "Good": GREEN, "Green": GREEN, "Fresh": GREEN, "Fits": GREEN, "Passed": GREEN, "Inside": GREEN,
    "Pending": GREY, "Closed": GREY, "Committed": GREY,
}
BAR_GREEN, BAR_AMBER, BAR_RED = "3A9E4A", "E8A317", "D03B3B"
thin = Side(style="thin", color=HAIR)
BOTTOM = Border(bottom=thin)


def f(size=10, bold=False, color=INK, italic=False, underline=None):
    return Font(name=FONT, size=size, bold=bold, color=color, italic=italic, underline=underline)


def q(name):
    return "'%s'" % name


# ---------------------------------------------------------------- sheet specs
class Spec:
    """A data sheet: named columns, inputs first, then formulas.

    Formulas are templates: [Key] is this row's cell in column Key, and
    [[Key]] is the whole data range of column Key. Letters are worked out
    here, so a formula can never point at the wrong column."""

    def __init__(self, name, rows, inputs, calc=()):
        self.name, self.rows = name, rows
        self.cols = [(k, h, w, n, None) for k, h, w, n in inputs] + [(k, h, w, "", fm) for k, h, w, fm in calc]
        self.n_inputs = len(inputs)
        self.letter = {c[0]: get_column_letter(i) for i, c in enumerate(self.cols, 1)}
        self.last = rows + 1

    def L(self, key):
        return self.letter[key]

    def rng(self, key, local=False):
        r = "$%s$2:$%s$%d" % (self.L(key), self.L(key), self.last)
        return r if local else "%s!%s" % (q(self.name), r)

    def expand(self, tmpl, r):
        tmpl = re.sub(r"\[\[(\w+)\]\]", lambda m: self.rng(m.group(1), local=True), tmpl)
        return re.sub(r"\[(\w+)\]", lambda m: "$%s%d" % (self.L(m.group(1)), r), tmpl)


# ---- Use Cases: the Jira snapshot, one row per use case ----
UC = Spec("Use Cases", 500, [
    ("Key", "Key", 9, "Jira issue key, e.g. AI-003."),
    ("Name", "Use case", 30, "Jira summary."),
    ("Status", "Status", 15, "Exactly as Jira shows it. Mapped to a stage on Config."),
    ("Func", "Function", 15, "Business function. Payments, Collections, Consumer Lending and Fraud Operations make it high tier."),
    ("Owner", "Owner", 13, "PM owner (Jira assignee)."),
    ("Sponsor", "Sponsor", 18, "Named business sponsor accountable for the value."),
    ("Opened", "Opened", 10, "Jira Created. Starts the tier clock."),
    ("Updated", "Updated", 10, "Jira Updated. Drives freshness."),
    ("Target", "Target", 10, "Expected exit date of the CURRENT stage. Drives health."),
    ("Risk", "Risk flags", 14, "Pipe-separated: NPI | Reg report | No human review."),
    ("Impact", "Impact", 16, "Pipe-separated: revenue | cost | cycle | risk | insight."),
    ("Value", "Value $K", 8, "Estimated annual value, $K. Blank until sized."),
    ("Size", "Size", 6, "Job size in delivery points."),
    ("WSJF", "WSJF", 6, "WSJF score. Blank until scored."),
    ("Metric", "Metric", 7, "Y if a success metric and stop condition are set."),
    ("Data", "Data ready", 9, "ready, partial, none, or blank if not assessed."),
    ("Baseline", "Baseline", 8, "Y if a baseline is measured."),
    ("Waiting", "Waiting on", 22, "What it is blocked on, if anything."),
    ("Decided", "Decided", 10, "Date of the triage decision."),
    ("Outcome", "Outcome", 10, "Declined or Transferred, if closed that way."),
    ("ClosedOn", "Closed", 10, "Date closed."),
    ("Flagged", "Flagged", 7, "Y if flagged in Jira."),
    ("Topic", "Topic", 14, "Topic slug, if it maps to one."),
], [
    ("Stage", "Stage", 10, '=IF([Key]="","",IF(OR([Outcome]<>"",[ClosedOn]<>""),"Closed",IFERROR(INDEX(MapStage,MATCH([Status],MapStatus,0)),"Unmapped")))'),
    ("StageN", "Stage #", 7, '=IF(OR([Stage]="",[Stage]="Closed",[Stage]="Unmapped"),"",MATCH([Stage],StageName,0))'),
    ("DaysTo", "Days to target", 8, '=IF(OR([StageN]="",[Target]=""),"",[Target]-AsOf)'),
    ("Since", "Since update", 8, '=IF([Key]="","",AsOf-[Updated])'),
    ("Health", "Health", 9, '=IF([Key]="","",IF([Stage]="Closed","Closed",IF([Stage]="Unmapped","Unmapped",IF([Target]="","No target",IF([DaysTo]<0,"Overdue",IF([DaysTo]<=INDEX(StageWindow,[StageN]),"At risk","On track"))))))'),
    ("Fresh", "Freshness", 9, '=IF([StageN]="","",IF([Since]>2*INDEX(StageStale,[StageN]),"Stale",IF([Since]>INDEX(StageStale,[StageN]),"Aging","Fresh")))'),
    ("Tier", "Tier", 8, '=IF([Key]="","",IF(OR(ISNUMBER(SEARCH("Reg report",[Risk])),ISNUMBER(SEARCH("No human review",[Risk])),COUNTIF(TierFuncs,[Func])>0),"High",IF(OR(TRIM([Risk])<>"",ISNUMBER(SEARCH("revenue",[Impact]))),"Medium","Low")))'),
    ("TierDays", "Tier days", 7, '=IF([Key]="","",INDEX(TierDays,MATCH([Tier],TierName,0)))'),
    ("Age", "Age", 6, '=IF([Key]="","",AsOf-[Opened])'),
    ("Clock", "Tier clock", 10, '=IF([StageN]="","",IF([StageN]<=5,IF([Age]>[TierDays],"Over","Inside"),"Past approval"))'),
    ("Gate", "Gate", 9, '=IF([StageN]="","",CHOOSE([StageN],'
        'IF(OR(TRIM([Sponsor])="",ISNUMBER(SEARCH("not named",[Sponsor]))),"Critical","Good"),'
        'IF([Metric]<>"Y","Critical",IF([Baseline]<>"Y","Warning","Good")),'
        'IF([Data]="","Critical",IF([Data]="partial","Warning",IF([Data]="ready","Good","Critical"))),'
        'IF([Waiting]<>"","Critical","Warning"),'
        'IF([Value]="","Critical",IF([WSJF]="","Warning","Good")),'
        'IF([Waiting]<>"","Critical","Warning"),'
        'IF([Waiting]<>"","Critical","Warning"),'
        'IF([Baseline]="Y","Good","Critical")))'),
    ("Need", "What the gate needs", 34, '=IF([StageN]="","",CHOOSE([StageN],'
        'IF(OR(TRIM([Sponsor])="",ISNUMBER(SEARCH("not named",[Sponsor]))),"Name a sponsor accountable for the value",""),'
        'IF([Metric]<>"Y","State the success metric and the stop condition",IF([Baseline]<>"Y","Set the baseline the benefit will be measured against","")),'
        'IF([Data]="","Assess data readiness and regulatory impact",IF([Data]="partial","Close the known data gaps",IF([Data]="ready","","Data is not available; reshape or park"))),'
        'IF([Waiting]<>"",IF(OR(ISNUMBER(SEARCH("mrm",[Waiting])),ISNUMBER(SEARCH("model",[Waiting])),ISNUMBER(SEARCH("risk",[Waiting])),ISNUMBER(SEARCH("legal",[Waiting])),ISNUMBER(SEARCH("complian",[Waiting]))),"Awaiting ","Held at the design gate: ")&[Waiting],"Map the governance framework for its tier"),'
        'IF([Value]="","Size the annual benefit",IF([WSJF]="","Score it so it can be ranked against capacity","")),'
        'IF([Waiting]<>"","Build held: "&[Waiting],"In build, not yet through test"),'
        'IF([Waiting]<>"","Not ready to scale: "&[Waiting],"Monitoring and third-party review not yet signed off"),'
        'IF([Baseline]="Y","","Live without a measured baseline to judge it against")))'),
    ("Forum", "Next forum", 14, '=IF([StageN]="","",INDEX(StageForum,[StageN]))'),
    ("Cap", "Capacity", 10, '=IF([StageN]="","",IF(OR([Stage]="Delivery",[Stage]="Value"),"Committed",IF([WSJF]<>"","Candidate","")))'),
    ("Rank", "WSJF rank", 7, '=IF([Cap]<>"Candidate","",COUNTIFS([[Cap]],"Candidate",[[WSJF]],">"&[WSJF])+COUNTIFS([[Cap]],"Candidate",[[WSJF]],[WSJF],[[Key]],"<"&[Key])+1)'),
    ("Cum", "Cum. points", 8, '=IF([Rank]="","",SUMIFS([[Size]],[[Cap]],"Candidate",[[Rank]],"<="&[Rank]))'),
    ("Line", "Capacity line", 10, '=IF([Rank]="","",IF([Cum]<=CapacityOpen,"Fits","Below line"))'),
    ("Sev", "Attention", 9, '=IF([Key]="","",IF([Stage]="Closed","",IF([Stage]="Unmapped","Warning",IF(OR([Health]="Overdue",[Flagged]="Y",[Gate]="Critical"),"Critical",IF(OR([Health]="At risk",[Fresh]="Stale",[Clock]="Over"),"Warning","")))))'),
    ("SevKey", "Attention key", 9, '=IF([Sev]="","",IF([Sev]="Critical",3000,2000)-IF([DaysTo]="",0,[DaysTo])+ROW()/100000)'),
    ("Why", "Why", 34, '=IF([Sev]="","",IF([Stage]="Unmapped","Status \'"&[Status]&"\' is not in the Config map",IF([Flagged]="Y","Flagged in Jira",IF([Health]="Overdue",-[DaysTo]&" days past its "&[Stage]&" target",IF([Gate]="Critical",[Need],IF([Health]="At risk","Target in "&[DaysTo]&" days",IF([Fresh]="Stale","No update in "&[Since]&" days","Past its "&[TierDays]&"-day tier window")))))))'),
    ("Say", "Say this", 26, '=IF([Sev]="","","draft Jira update for "&[Key])'),
    ("Link", "Jira", 6, '=IF([Key]="","",HYPERLINK(JiraSite&"/browse/"&[Key],"open"))'),
    ("Order", "Board order", 8, '=IF([StageN]="","",[StageN]*1000+ROW())'),
    ("NewWk", "In this week", 8, '=IF(AND([Key]<>"",[Opened]>=WeekStart),[Opened]+ROW()/100000,"")'),
    ("DecWk", "Decided this week", 8, '=IF([Key]="","",IF(OR(AND([Decided]<>"",[Decided]>=WeekStart),AND([ClosedOn]<>"",[ClosedOn]>=WeekStart)),MAX([Decided],[ClosedOn])+ROW()/100000,""))'),
    ("DecText", "Decision", 18, '=IF([DecWk]="","",IF([Outcome]<>"",[Outcome],IF([Stage]="Closed","Closed","Accepted to "&[Stage])))'),
    ("Block", "Blocker key", 8, '=IF(AND([StageN]<>"",[Waiting]<>""),[Age]+ROW()/100000,"")'),
    ("Council", "Council key", 8, '=IF(AND([StageN]<>"",OR([Health]="Overdue",AND([Gate]="Critical",[Waiting]<>""))),[Age]+ROW()/100000,"")'),
    ("GateKey", "Gate key", 8, '=IF([Gate]="Critical",[Age]+ROW()/100000,"")'),
])

# ---- Inventory: append-only ----
INV = Spec("Inventory", 1000, [
    ("ID", "ID", 10, "INV-0001, INV-0002 ... next number after the last row."),
    ("Date", "Date", 10, "Date the information arrived."),
    ("Type", "Type", 10, "New = what's new. Know = what we need to know. Decision = decision needed. Conflict = disagrees with the inventory. Confirmed / Resolved close an earlier row named in Ref."),
    ("Topic", "Topic", 15, "Topic slug from the Topics sheet."),
    ("Summary", "Summary", 56, "One sentence. No customer data."),
    ("From", "From", 16, "Person it came from."),
    ("Channel", "Channel", 10, "Meeting, Email, Teams, Call, Document, Jira, Session."),
    ("Conf", "Confidence", 11, "Confirmed if first-hand or verified; Unconfirmed if second-hand."),
    ("Ref", "Ref", 10, "For Confirmed, Resolved or Conflict: the INV ID it refers to."),
    ("Jira", "Use case", 9, "Related use case key, if any."),
], [
    ("State", "State", 11, '=IF([ID]="","",IF(OR([Type]="Decision",[Type]="Conflict"),IF(COUNTIFS([[Ref]],[ID],[[Type]],"Resolved")=0,"Open","Closed"),IF(AND([Conf]="Unconfirmed",OR([Type]="New",[Type]="Know")),IF(COUNTIFS([[Ref]],[ID],[[Type]],"Confirmed")=0,"Unconfirmed","Confirmed"),"Logged")))'),
    ("Age", "Age (days)", 8, '=IF([ID]="","",AsOf-[Date])'),
    ("Sev", "Severity", 9, '=IF([State]="Open",IF([Type]="Conflict","Critical",IF([Age]>=DecisionCritical,"Critical",IF([Age]>=DecisionWarn,"Warning","On track"))),IF([State]="Unconfirmed",IF([Age]>=UnconfirmedWarn,"Warning","On track"),""))'),
    ("Key", "Rank key", 9, '=IF([Sev]="","",IF([Sev]="Critical",3000,IF([Sev]="Warning",2000,1000))+[Age]+ROW()/100000)'),
    ("Say", "Say this", 30, '=IF([State]="Open",IF([Type]="Conflict","decide "&[ID]&": <which version stands>","decide "&[ID]&": <outcome>"),IF([State]="Unconfirmed","confirm "&[ID],""))'),
    ("NewWk", "New this week", 8, '=IF(AND([Type]="New",[Date]>=WeekStart),[Date]+ROW()/100000,"")'),
    ("KnowWk", "Know this week", 8, '=IF(AND([Type]="Know",[Date]>=WeekStart),[Date]+ROW()/100000,"")'),
    ("OpenDec", "Open decision key", 8, '=IF(AND([State]="Open",[Type]="Decision"),[Age]+ROW()/100000,"")'),
    ("Sel", "Selected use case", 8, '=IF(AND([Jira]<>"",[Jira]=UCSel),[Date]+ROW()/100000,"")'),
])

DONE = Spec("Done", 1000, [
    ("Date", "Date", 10, "Day it was done."),
    ("What", "Accomplishment", 58, "Outcome, not activity. 'Got MRM sign-off on X', not 'met with MRM'."),
    ("Topic", "Topic", 15, "Topic slug."),
    ("Jira", "Use case", 9, "Related use case key, if any."),
    ("Source", "Source", 10, "Session, Email, Teams, Calendar: where it was found."),
], [
    ("Week", "Week of", 10, '=IF([Date]="","",[Date]-WEEKDAY([Date],3))'),
    ("ThisWk", "This week", 8, '=IF([Date]="","",IF([Week]=WeekStart,"Yes",""))'),
    ("Key", "Rank key", 9, '=IF([ThisWk]="Yes",[Date]+ROW()/100000,"")'),
    ("Sel", "Selected use case", 8, '=IF(AND([Jira]<>"",[Jira]=UCSel),[Date]+ROW()/100000,"")'),
])

VAL = Spec("Value", 40, [
    ("Q", "Quarter", 10, "e.g. Q3 '26"),
    ("Proj", "Projected $K", 12, "Projected annual run-rate value, $K."),
    ("Real", "Realized $K", 12, "Realized, as measured at the Portfolio Council."),
    ("Done", "Complete", 9, "Y once the quarter is closed and measured."),
], [
    ("Pct", "Realized %", 10, '=IF(OR([Q]="",[Proj]=0),"",[Real]/[Proj])'),
])

ANS = Spec("Answers", 1000, [
    ("ID", "ID", 8, "Q-0001, Q-0002 ..."), ("Date", "Date", 10, ""), ("Question", "Question", 40, "As asked, minus anything personal."),
    ("Kind", "Kind", 8, "Answer = traced to a source. Routed = sent to a person or resource. Reuse = an earlier answer given again (its ID in Ref)."),
    ("Answer", "Answer or route", 46, ""), ("Source", "Source", 28, "Link or document it traces to, or the person routed to."),
    ("By", "Asked by", 14, ""), ("Ref", "Ref", 8, "For Reuse: the Q ID reused."),
], [
    ("Reused", "Times reused", 9, '=IF([ID]="","",COUNTIFS([[Ref]],[ID],[[Kind]],"Reuse"))'),
])

REV = Spec("Reviews", 1000, [
    ("Date", "Date", 10, ""), ("Artifact", "Artifact", 36, "File name or link."), ("Author", "Author", 14, ""),
    ("Pass", "Passed", 7, "Checks passed (of 8)."), ("Fail", "Failed", 7, "Checks failed."),
    ("Verdict", "Verdict", 10, "Ready, or Fix first."), ("Fix", "Top fix", 60, "The single most important fix."),
])
CHG = Spec("Changes", 1000, [
    ("Date", "Date", 10, ""), ("What", "What changed", 36, ""), ("From", "From", 34, ""), ("To", "To", 34, ""),
    ("Refs", "References updated", 30, "Where links were fixed."), ("By", "Approved by", 14, ""),
])
TOP = Spec("Topics", 200, [
    ("Topic", "Topic", 16, "Short slug, lowercase, hyphens. Used everywhere else."), ("Name", "Name", 30, ""), ("Owner", "Owner", 16, ""),
    ("Forum", "Forum", 16, "Weekly Intake, Tactical Standup or Portfolio Council."),
    ("Jira", "Use cases", 16, "Use case keys or a label that ties them to it."), ("Status", "Status", 9, "Active, Paused, Closed."),
    ("Notes", "Notes doc", 34, "OneDrive path to its running notes."),
], [
    ("Open", "Open items", 9, '=IF([Topic]="","",COUNTIFS(Inventory!$D:$D,[Topic],Inventory!$K:$K,"Open")+COUNTIFS(Inventory!$D:$D,[Topic],Inventory!$K:$K,"Unconfirmed"))'),
    ("UCs", "Use cases", 9, '=IF([Topic]="","",COUNTIFS(' + UC.rng("Topic") + ',[Topic])-COUNTIFS(' + UC.rng("Topic") + ',[Topic],' + UC.rng("Stage") + ',"Closed"))'),
    ("Att", "Attention", 9, '=IF([Topic]="","",COUNTIFS(' + UC.rng("Topic") + ',[Topic],' + UC.rng("Sev") + ',"Critical")+COUNTIFS(' + UC.rng("Topic") + ',[Topic],' + UC.rng("Sev") + ',"Warning"))'),
])
PEO = Spec("People", 500, [
    ("Name", "Name", 18, ""), ("Role", "Role", 24, ""), ("Team", "Team", 18, ""),
    ("Topics", "Works with me on", 26, "Topics, comma-separated. The Support Guide routes by this."),
    ("How", "How they work", 40, "Facts only. Nothing evaluative; that goes in Private."),
    ("Source", "Source", 14, ""), ("Updated", "Last updated", 11, ""),
])

STAGES = [  # name, stale after, at-risk window, gate owner, next forum. Mirrors the site.
    ("Intake", 7, 2, "Portfolio Lead", "Weekly Intake"),
    ("Triage", 7, 2, "PM Owner", "Weekly Intake"),
    ("Discovery", 10, 5, "PM Owner", "Tactical Standup"),
    ("Design", 14, 7, "Model Risk & Monitoring", "Portfolio Council"),
    ("Approval", 14, 7, "Director / Portfolio Council", "Portfolio Council"),
    ("Delivery", 14, 14, "Tech Lead", "Tactical Standup"),
    ("Scale", 14, 7, "Model Risk & Monitoring", "Tactical Standup"),
    ("Value", 45, 14, "Governance & Audit", "Portfolio Council"),
]
TIERS = [
    ("Low", 21, "Internal tools, employee-only access, minimal regulatory exposure."),
    ("Medium", 45, "Revenue impact, internal process, regulatory review required."),
    ("High", 70, "Customer-facing, credit decisions, compliance-critical, regulatory gated."),
]
TIER_FUNCS = ["Consumer Lending", "Collections", "Payments", "Fraud Operations"]
STATUS_MAP = [
    ("Backlog", "Intake"), ("To Do", "Intake"), ("Open", "Intake"), ("Intake", "Intake"),
    ("Triage", "Triage"), ("Discovery", "Discovery"), ("Design", "Design"),
    ("In Review", "Approval"), ("Governance Review", "Approval"), ("Approval", "Approval"),
    ("In Progress", "Delivery"), ("In Delivery", "Delivery"), ("Build", "Delivery"),
    ("Scaling", "Scale"), ("Rollout", "Scale"), ("Value Tracking", "Value"), ("Measuring", "Value"),
    ("Done", "Closed"), ("Closed", "Closed"), ("Declined", "Closed"), ("Transferred", "Closed"), ("Won't Do", "Closed"),
]
FIELD_MAP = [  # workbook column, Jira field, note
    ("Key", "Issue key", ""), ("Use case", "Summary", ""), ("Status", "Status", "Mapped to a stage below"),
    ("Function", "Business Function", "Custom field. Or a component"), ("Owner", "Assignee", ""),
    ("Sponsor", "Business Sponsor", "Custom field"), ("Opened", "Created", ""), ("Updated", "Updated", ""),
    ("Target", "Stage Target Date", "Custom field. Or Due date"), ("Risk flags", "Risk Flags", "Custom multi-select"),
    ("Impact", "Impact", "Custom multi-select"), ("Value $K", "Estimated Annual Value", "Custom number, $K"),
    ("Size", "Job Size", "Or Story points"), ("WSJF", "WSJF Score", "Custom number"),
    ("Metric", "Success Metric Defined", "Custom yes/no"), ("Data ready", "Data Readiness", "Custom select"),
    ("Baseline", "Baseline Measured", "Custom yes/no"), ("Waiting on", "Waiting On", "Custom text. Or the flag comment"),
    ("Decided", "Triage Decision Date", "Custom date"), ("Outcome", "Resolution", "Declined / Transferred"),
    ("Closed", "Resolved", ""), ("Flagged", "Flagged", ""), ("Topic", "Labels", "The label that matches a Topics slug"),
]

COMMANDS = [
    ("start my day", "Refresh Jira if the snapshot is stale, read Home, sweep yesterday's email, Teams and calendar, and give me the Needs You list plus anything worth logging.", "Daily"),
    ("refresh dashboard", "Pull the use cases from Jira (connector or newest CSV export), rewrite the Use Cases sheet, stamp the snapshot.", "Daily"),
    ("log this: <note>", "Capture a note into the Inventory as New, Know or Decision, with source, channel and confidence.", "Inventory"),
    ("add note to <topic>: <note>", "Same as log this, filed against a named topic.", "Inventory"),
    ("confirm <INV-id>", "Append a Confirmed row for a second-hand item.", "Inventory"),
    ("decide <INV-id>: <outcome>", "Close an open decision or conflict by appending a Resolved row.", "Inventory"),
    ("what's open on <topic>", "Open decisions, unconfirmed items, conflicts and use cases for one topic.", "Inventory"),
    ("show <KEY>", "Set the Use Case tab to that use case and summarise it: stage, health, gate, capacity, history.", "Portfolio"),
    ("what fits this quarter", "The WSJF-ranked backlog against open capacity, from the Portfolio tab.", "Portfolio"),
    ("done: <accomplishment>", "Append to the Done log under today.", "Reporting"),
    ("draft weekly report", "Write this week's report from the Weekly Status tab plus a sweep of email, Teams and calendar. Word draft, never sent.", "Reporting"),
    ("prep for <meeting>", "Agenda for that sitting from the Weekly Status tab and the open Inventory. Word draft.", "Reporting"),
    ("review this", "Run the Review Gate. Report what passes, what fails and the fix. Never rewrite.", "Quality"),
    ("support: <question>", "Answer from the Answers log or a traceable source, or route to a named person. Log it.", "Quality"),
    ("draft Jira update for <KEY>", "Write a status comment for that issue as a draft. Never posted.", "Jira"),
    ("what's stale in Jira", "Use cases past their stage's staleness limit, worst first, with owner.", "Jira"),
    ("move <file> to <folder>", "Move it, fix every reference, log it on Changes.", "Upkeep"),
    ("check integrity", "Scan the workbook for broken refs, duplicate IDs, unmapped statuses, and anything that looks like customer data.", "Upkeep"),
]

DASHBOARDS = ["Home", "Portfolio", "Weekly Status", "Gates", "Use Case"]


# ---------------------------------------------------------------- sample data
def d(offset):
    return SAMPLE_AS_OF + dt.timedelta(days=offset)


def s(iso):
    """A date from the site's sample, shifted to this sample's as-of date."""
    return dt.date.fromisoformat(iso) + dt.timedelta(days=SHIFT)


# The site's sixteen use cases, same facts, dates shifted. Two dates are moved
# into the current week so the Weekly Intake sitting has something to report.
SAMPLE_UC = [
    # key, name, status, func, owner, sponsor, opened, updated, target, risk, impact, value, size, wsjf, metric, data, baseline, waiting, decided, outcome, closed, flagged, topic
    ("AI-001", "Contact center call summarization", "Scaling", "Contact Center", "M. Alvarez", "Contact Center Ops", s("2026-02-10"), s("2026-08-07"), s("2026-09-25"), "NPI", "cost | cycle", 850, 8, 4.2, "Y", "ready", "Y", "", s("2026-03-20"), "", None, "", "call-summary"),
    ("AI-002", "Complaint triage and routing", "Discovery", "Customer Care", "J. Whitfield", "Head of Customer Care", s("2026-07-05"), s("2026-08-08"), s("2026-08-23"), "NPI", "cycle | risk", None, 5, None, "Y", "partial", "", "", s("2026-07-20"), "", None, "", "complaint-triage"),
    ("AI-003", "Fraud alert prioritization", "Design", "Fraud Operations", "S. Okafor", "Fraud Ops Director", s("2026-06-10"), s("2026-08-09"), s("2026-08-08"), "NPI", "risk | insight", 1200, 8, 6.8, "Y", "ready", "Y", "MRM model designation", s("2026-07-01"), "", None, "Y", "fraud-alerts"),
    ("AI-004", "KYC document extraction", "Discovery", "Onboarding", "R. Patel", "Deposits Operations", s("2026-05-20"), s("2026-08-05"), s("2026-08-15"), "NPI | Reg report", "cost | cycle | risk", None, 13, None, "Y", "", "", "Data access approval for KYC repository", s("2026-06-15"), "", None, "", "kyc-extract"),
    ("AI-005", "Collections outreach timing", "Governance Review", "Collections", "D. Kim", "Collections VP", s("2026-06-25"), s("2026-08-08"), s("2026-08-27"), "", "revenue | insight | cost", 950, 5, 7.5, "Y", "ready", "Y", "", s("2026-07-10"), "", None, "", "vendor-copilot"),
    ("AI-006", "Branch staffing forecast", "Governance Review", "Branch Network", "L. Nguyen", "Retail Distribution", s("2026-06-30"), s("2026-07-30"), s("2026-08-20"), "", "cost | insight", 400, 8, 5.1, "Y", "partial", "Y", "", s("2026-07-14"), "", None, "", ""),
    ("AI-007", "Marketing copy assistant", "Triage", "Marketing", "Intake team", "Consumer Marketing", s("2026-08-01"), s("2026-08-09"), s("2026-08-16"), "", "revenue | cost", None, 2, None, "", "", "", "", None, "", None, "", ""),
    ("AI-008", "Chat deflection FAQ assistant", "In Delivery", "Digital Banking", "M. Alvarez", "Digital Channels", s("2026-03-15"), s("2026-08-06"), s("2026-09-01"), "No human review", "cost | cycle", 600, 5, 5.9, "Y", "ready", "Y", "", s("2026-04-20"), "", None, "", "chat-deflection"),
    ("AI-009", "Wire fraud anomaly detection", "Intake", "Payments", "Intake team", "Payments Risk", s("2026-08-08"), s("2026-08-10"), s("2026-08-17"), "NPI", "risk | insight", None, 8, None, "", "partial", "", "", None, "", None, "", "fraud-alerts"),
    ("AI-010", "Statement insight summaries", "Intake", "Digital Banking", "Intake team", "(sponsor not named)", s("2026-07-21"), s("2026-08-02"), s("2026-08-13"), "", "insight", None, 3, None, "", "", "", "Named business sponsor", None, "", None, "", ""),
    ("AI-011", "Loan document pre-fill", "Value Tracking", "Consumer Lending", "T. Brooks", "Lending Operations", s("2026-01-20"), s("2026-08-01"), s("2026-09-30"), "NPI", "revenue | cycle | cost", 1400, 3, 8.9, "Y", "ready", "Y", "", s("2026-02-25"), "", None, "", ""),
    ("AI-012", "Teller balancing assistant", "Triage", "Branch Network", "Intake team", "Branch Operations", s("2026-07-24"), s("2026-08-03"), s("2026-08-19"), "", "cost", None, 3, None, "", "", "", "Prep incomplete, deferred one cycle", None, "", None, "", ""),
    ("AI-013", "ATM cash forecasting", "Discovery", "Branch Network", "R. Patel", "Treasury Services", s("2026-07-28"), s("2026-08-07"), s("2026-08-29"), "", "cost | insight", None, 5, None, "Y", "partial", "", "", s("2026-08-08"), "", None, "", ""),
    ("AI-014", "Dispute intake summarizer", "Governance Review", "Customer Care", "D. Kim", "Card Services", s("2026-06-20"), s("2026-08-05"), s("2026-09-04"), "NPI", "cycle | cost", 300, 8, 3.4, "Y", "ready", "Y", "", s("2026-07-08"), "", None, "", "complaint-triage"),
    ("AI-015", "RM email auto-drafting", "Declined", "Small Business", "Intake team", "Small Business Banking", s("2026-07-08"), s("2026-07-24"), s("2026-07-22"), "", "cost", None, 2, None, "", "", "", "", s("2026-07-22"), "Declined", s("2026-07-22"), "", ""),
    ("AI-016", "HR policy chatbot", "Transferred", "Human Resources", "Intake team", "HR Shared Services", s("2026-07-01"), s("2026-07-15"), s("2026-07-15"), "", "cost", None, 3, None, "", "", "", "", s("2026-07-15"), "Transferred", s("2026-07-15"), "", "genai-policy"),
]

SAMPLE_INV = [
    ("INV-0001", -24, "New", "council", "Portfolio Council keeps its Thursday 75-minute slot through Q4.", "M. Okafor", "Meeting", "Confirmed", "", ""),
    ("INV-0002", -21, "Know", "mrm", "MRM wants the validation plan at Design exit, not at Approval.", "R. Chen", "Email", "Confirmed", "", ""),
    ("INV-0003", -19, "Decision", "call-summary", "Confirm the value baseline with the sponsor before benefits reporting starts.", "M. Alvarez", "Meeting", "Confirmed", "", "AI-001"),
    ("INV-0004", -17, "New", "vendor-copilot", "Vendor offering a 90-day no-cost agent-assist pilot for Collections.", "D. Kim", "Email", "Confirmed", "", "AI-005"),
    ("INV-0005", -14, "Know", "genai-policy", "GenAI policy v3 heard to ban NPI in prompts outright.", "T. Nguyen", "Teams", "Unconfirmed", "", ""),
    ("INV-0006", -12, "Resolved", "call-summary", "Baseline agreed: 6.1 minutes after-call work, measured on Q2 calls.", "Contact Center Ops", "Meeting", "Confirmed", "INV-0003", "AI-001"),
    ("INV-0007", -11, "Decision", "council", "Find a sponsor for AI-010 or decline it.", "Portfolio Council", "Meeting", "Confirmed", "", "AI-010"),
    ("INV-0008", -10, "Confirmed", "genai-policy", "Compliance confirmed policy v3: no NPI in prompts.", "T. Nguyen", "Email", "Confirmed", "INV-0005", ""),
    ("INV-0009", -9, "Decision", "fraud-alerts", "Chase the MRM model designation for AI-003 or re-plan Design.", "S. Okafor", "Meeting", "Confirmed", "", "AI-003"),
    ("INV-0010", -8, "Know", "kyc-extract", "KYC repository access for AI-004 still unapproved; the discovery timebox closes next week.", "R. Patel", "Email", "Confirmed", "", "AI-004"),
    ("INV-0011", -7, "New", "council", "Council wants a one-page value tracker for every use case in Value.", "M. Okafor", "Meeting", "Confirmed", "", ""),
    ("INV-0012", -6, "Know", "mrm", "MRM may add a bias test for any credit-adjacent model.", "R. Chen", "Call", "Unconfirmed", "", ""),
    ("INV-0013", -5, "Conflict", "fraud-alerts", "Vendor says AI-003 build has started; Jira shows Design. Inventory stands until confirmed.", "Vendor PM", "Email", "Unconfirmed", "INV-0009", "AI-003"),
    ("INV-0014", -4, "Decision", "council", "AI-012 returns to triage a second time: force a decision.", "Intake team", "Meeting", "Confirmed", "", "AI-012"),
    ("INV-0015", -3, "New", "chat-deflection", "Chat deflection pilot hit 31% containment in week 2, above the 25% target.", "Digital Channels", "Teams", "Unconfirmed", "", "AI-008"),
    ("INV-0016", -2, "Decision", "vendor-copilot", "Accept the vendor pilot or run a competitive eval first.", "D. Kim", "Email", "Confirmed", "", "AI-005"),
    ("INV-0017", -1, "Know", "council", "Three of the last four intake submissions arrived with no success metric.", "Intake team", "Document", "Confirmed", "", ""),
    ("INV-0018", 0, "New", "fraud-alerts", "Payments Risk submitted wire fraud anomaly detection (AI-009).", "Payments Risk", "Jira", "Confirmed", "", "AI-009"),
]

SAMPLE_DONE = [
    (-38, "Ran the first front-door triage: 6 ideas in, 2 declined with reasons logged.", "council", "", "Session"),
    (-36, "Published the eight-stage operating model to the team SharePoint.", "council", "", "Session"),
    (-33, "Closed MRM's questions on the call summarization validation plan.", "call-summary", "AI-001", "Email"),
    (-31, "Set the complaint triage baseline: 4.2-day median time to route.", "complaint-triage", "AI-002", "Session"),
    (-27, "Got Procurement to start the vendor risk review for KYC extraction.", "kyc-extract", "AI-004", "Email"),
    (-25, "Council approved chat deflection into delivery.", "chat-deflection", "AI-008", "Calendar"),
    (-24, "Retired the old intake spreadsheet; Jira is now the only intake path.", "council", "", "Session"),
    (-20, "Agreed staleness thresholds per stage with the delivery leads.", "council", "", "Teams"),
    (-17, "Mapped GenAI policy v3 controls to every in-flight GenAI use case.", "genai-policy", "", "Session"),
    (-13, "Agreed the call summarization baseline with Contact Center Ops (INV-0006).", "call-summary", "AI-001", "Calendar"),
    (-12, "Declined RM email auto-drafting; duplicates the enterprise CRM assistant.", "council", "AI-015", "Session"),
    (-11, "Wrote the data request for complaint triage labelled history.", "complaint-triage", "AI-002", "Email"),
    (-10, "Ran the Review Gate on the Q4 roadmap deck; fixed 3 MECE gaps.", "council", "", "Session"),
    (-6, "Confirmed GenAI policy v3 wording with Compliance (INV-0008).", "genai-policy", "", "Email"),
    (-4, "Escalated the AI-003 MRM designation to the Council agenda.", "fraud-alerts", "AI-003", "Session"),
    (-4, "Built the value tracker template the Council asked for.", "council", "", "Session"),
    (-3, "Moved ATM cash forecasting into discovery with a four-week timebox.", "", "AI-013", "Session"),
    (-2, "Sent the chat deflection week-2 readout to Digital leadership.", "chat-deflection", "AI-008", "Email"),
    (-1, "Logged wire fraud anomaly detection at intake and assigned the high tier.", "fraud-alerts", "AI-009", "Session"),
    (0, "Drafted the sponsor ask for statement insight summaries.", "", "AI-010", "Session"),
]
SAMPLE_VAL = [("Q4 '25", 1800, 1650, "Y"), ("Q1 '26", 2600, 2400, "Y"), ("Q2 '26", 4200, 3900, "Y"), ("Q3 '26", 5700, 3600, "")]
SAMPLE_ANS = [
    ("Q-0001", -30, "Who approves a new GenAI use case?", "Answer", "The Portfolio Council at the Approval gate; the PM owner brings it.", "Operating model, gate table", "B. Ford", ""),
    ("Q-0002", -26, "Can we use customer emails to fine-tune a model?", "Routed", "Routed to Compliance (T. Nguyen). Not answered here.", "T. Nguyen", "D. Kim", ""),
    ("Q-0003", -21, "What does Model Risk need at Design exit?", "Answer", "Validation plan, monitoring design, audit trail spec.", "INV-0002; MRM standard 4.3", "S. Okafor", ""),
    ("Q-0004", -15, "Who approves a new GenAI use case?", "Reuse", "Same as Q-0001.", "Q-0001", "R. Patel", "Q-0001"),
    ("Q-0005", -12, "How long should Triage take?", "Answer", "Seven days before it reads as aging.", "Config, stage table", "J. Whitfield", ""),
    ("Q-0006", -8, "Where do I submit a new AI idea?", "Answer", "The Jira intake form in project AI.", "AI intake form", "New hire", ""),
    ("Q-0007", -5, "What does Model Risk need at Design exit?", "Reuse", "Same as Q-0003.", "Q-0003", "L. Nguyen", "Q-0003"),
    ("Q-0008", -1, "Can a vendor model go to Scale before its SOC 2 renewal?", "Routed", "Routed to Third-Party Risk.", "Third-Party Risk team", "R. Patel", ""),
]
SAMPLE_REV = [
    (-22, "Q4 AI roadmap deck v2", "Sample PM", 5, 3, "Fix first", "Sections 2 and 4 overlap on capacity; merge them so the asks are MECE."),
    (-10, "Q4 AI roadmap deck v3", "Sample PM", 8, 0, "Ready", ""),
    (-6, "AI-003 MRM escalation memo", "S. Okafor", 6, 2, "Fix first", "The ask has no date or decider; say who decides by when."),
    (-2, "Chat deflection week-2 readout", "Digital Channels", 7, 1, "Ready", "Containment number needs its source and date."),
]
SAMPLE_CHG = [
    (-24, "Retired old intake tracker", "OneDrive/AI/Intake.xlsx", "Archive/Intake-2026Q3.xlsx", "Topics: council notes doc; Answers Q-0006", "Sample PM"),
    (-9, "Moved fraud notes into topic doc", "Documents/fraud-notes.docx", "AI-OS/Topics/fraud-alerts.docx", "Topics row fraud-alerts", "Sample PM"),
]
SAMPLE_TOP = [
    ("council", "Portfolio Council and governance", "M. Okafor", "Portfolio Council", "", "Active", "AI-OS/Topics/council.docx"),
    ("call-summary", "Contact center call summarization", "M. Alvarez", "Tactical Standup", "AI-001", "Active", "AI-OS/Topics/call-summary.docx"),
    ("complaint-triage", "Complaint and dispute handling", "J. Whitfield", "Tactical Standup", "AI-002, AI-014", "Active", "AI-OS/Topics/complaint-triage.docx"),
    ("fraud-alerts", "Fraud models", "S. Okafor", "Portfolio Council", "AI-003, AI-009", "Active", "AI-OS/Topics/fraud-alerts.docx"),
    ("kyc-extract", "KYC document extraction", "R. Patel", "Tactical Standup", "AI-004", "Active", "AI-OS/Topics/kyc-extract.docx"),
    ("mrm", "Model Risk Management requirements", "R. Chen", "Portfolio Council", "", "Active", "AI-OS/Topics/mrm.docx"),
    ("genai-policy", "GenAI usage policy", "T. Nguyen", "Portfolio Council", "AI-016", "Active", "AI-OS/Topics/genai-policy.docx"),
    ("vendor-copilot", "Collections vendor pilot", "D. Kim", "Weekly Intake", "AI-005", "Active", "AI-OS/Topics/vendor-copilot.docx"),
    ("chat-deflection", "Chat deflection FAQ assistant", "M. Alvarez", "Tactical Standup", "AI-008", "Active", "AI-OS/Topics/chat-deflection.docx"),
]
SAMPLE_PEO = [
    ("M. Okafor", "Portfolio Council chair", "Enterprise AI", "council", "Wants decisions framed as options with a recommendation.", "Meeting", -24),
    ("R. Chen", "Model Risk lead", "Model Risk Management", "mrm, fraud-alerts", "Prefers written questions by email; replies in two days.", "Email", -21),
    ("M. Alvarez", "PM owner, contact center and digital", "AI Product", "call-summary, chat-deflection", "Teams first; likes a weekly number.", "Teams", -19),
    ("T. Nguyen", "Compliance partner, GenAI", "Compliance", "genai-policy", "Needs the policy clause cited, not paraphrased.", "Email", -10),
    ("S. Okafor", "PM owner, fraud", "AI Product", "fraud-alerts", "", "Meeting", -9),
    ("D. Kim", "PM owner, collections and cards", "AI Product", "vendor-copilot, complaint-triage", "", "Meeting", -11),
]


# ---------------------------------------------------------------- data sheets
def head_cell(ws, col, title, width, note, computed):
    c = ws.cell(row=1, column=col, value=title)
    c.font = f(10, True, INK if not computed else INK2)
    c.fill = CALC_HEAD if computed else INPUT_HEAD
    c.alignment = Alignment(vertical="center", wrap_text=True)
    c.border = BOTTOM
    if note or computed:
        c.comment = Comment(("Computed. Cowork never writes here. " if computed else "") + (note or ""), "AI-OS")
    ws.column_dimensions[get_column_letter(col)].width = width


def data_sheet(wb, spec, data, date_keys=(), pct_keys=()):
    ws = wb.create_sheet(spec.name)
    for i, (k, h, w, n, fm) in enumerate(spec.cols, 1):
        head_cell(ws, i, h, w, n, fm is not None)
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "C2" if spec is UC else "B2"
    ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(spec.cols)), spec.last)
    date_cols = [list(spec.letter).index(k) + 1 for k in date_keys]
    pct_cols = [list(spec.letter).index(k) + 1 for k in pct_keys]
    for r in range(2, spec.last + 1):
        for i, (k, h, w, n, fm) in enumerate(spec.cols, 1):
            c = ws.cell(row=r, column=i)
            if fm is not None:
                c.value = spec.expand(fm, r)
                c.fill = CALC_CELL
                c.font = f(9, color=INK2)
            else:
                c.font = f(10)
            if i in date_cols:
                c.number_format = "yyyy-mm-dd"
            if i in pct_cols:
                c.number_format = "0%"
    for r, row in enumerate(data, 2):
        for col, v in enumerate(row, 1):
            if v != "" and v is not None:
                ws.cell(row=r, column=col, value=v)
    return ws


def validate(ws, spec, key, options):
    dv = DataValidation(type="list", formula1='"%s"' % ",".join(options), allow_blank=True,
                        showErrorMessage=True, errorTitle="Not on the list", error="Pick one of: " + ", ".join(options))
    ws.add_data_validation(dv)
    L = spec.L(key)
    dv.add("%s2:%s%d" % (L, L, spec.last))


def state_format(ws, rng):
    for label, (fill, text) in STATE.items():
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"%s"' % label],
                                      fill=PatternFill("solid", fgColor=fill), font=Font(name=FONT, color=text, bold=True)))


def name(wb, nm, ref):
    wb.defined_names[nm] = DefinedName(nm, attr_text=ref)


def build_config(wb, sample):
    ws = wb.create_sheet("Config")
    for col, w in {"A": 34, "B": 30, "C": 14, "D": 26, "E": 18, "F": 3, "G": 22, "H": 12, "I": 3, "J": 14, "K": 26, "L": 34}.items():
        ws.column_dimensions[col].width = w
    ws["A1"] = "Config"
    ws["A1"].font = f(16, True, BRAND)
    ws["A2"] = "Blue cells are yours to set once. Grey cells are written by Cowork or computed. Nothing here is a secret: no tokens or passwords, ever."
    ws["A2"].font = f(10, color=INK3, italic=True)

    def setting(row, nm, label, live, smp, note, kind="input", fmt=None):
        ws.cell(row=row, column=1, value=label).font = f(10)
        c = ws.cell(row=row, column=2, value=smp if sample else live)
        c.fill = INPUT_HEAD if kind == "input" else CALC_CELL
        c.font = f(10, color="1F3FBF" if kind == "input" else INK2)
        if fmt:
            c.number_format = fmt
        n = ws.cell(row=row, column=3, value=note)
        n.font = f(9, color=INK3)
        name(wb, nm, "Config!$B$%d" % row)

    def heading(row, text, col=1):
        ws.cell(row=row, column=col, value=text).font = f(11, True)

    heading(3, "Settings")
    setting(4, "OwnerName", "Your name (as Jira shows it)", "", "Sample PM", "Picks out use cases you own.")
    setting(5, "JiraSite", "Jira site URL", "https://YOURCOMPANY.atlassian.net", "https://example.atlassian.net", "No trailing slash. Builds the issue links.")
    setting(6, "JiraProjects", "Jira project key(s)", "AI", "AI", "Comma-separated.")
    setting(7, "JiraScope", "Jira scope in plain words", "All use cases in the project(s) above that are not Done, plus anything closed in the last 90 days",
            "All use cases in AI that are not Done, plus anything closed in the last 90 days", "What Cowork asks the connector for.")
    setting(8, "SampleAsOf", "Sample data as-of date", None, SAMPLE_AS_OF, "Leave BLANK for real use.", fmt="yyyy-mm-dd")
    setting(9, "AsOf", "Today (computed)", '=IF(SampleAsOf="",TODAY(),SampleAsOf)', '=IF(SampleAsOf="",TODAY(),SampleAsOf)', "Do not edit.", "calc", "yyyy-mm-dd")
    setting(10, "WeekStart", "This week starts (computed)", "=AsOf-WEEKDAY(AsOf,3)", "=AsOf-WEEKDAY(AsOf,3)", "Monday of the current week.", "calc", "yyyy-mm-dd")
    heading(11, "Thresholds and capacity")
    setting(12, "DecisionWarn", "Open decision: warning after (days)", 3, 3, "")
    setting(13, "DecisionCritical", "Open decision: critical after (days)", 7, 7, "")
    setting(14, "UnconfirmedWarn", "Unconfirmed item: warning after (days)", 5, 5, "")
    setting(15, "SnapshotMaxAge", "Jira snapshot: stale after (days)", 1, 1, "")
    setting(16, "CapacityPoints", "Delivery capacity this quarter (points)", 24, 24, "Work in Delivery and Value consumes it.")
    cap = "=SUMIFS(%s,%s,\"Committed\")" % (UC.rng("Size"), UC.rng("Cap"))
    setting(17, "CapacityCommitted", "Committed points (computed)", cap, cap, "", "calc")
    setting(18, "CapacityOpen", "Open points (computed)", "=MAX(0,CapacityPoints-CapacityCommitted)", "=MAX(0,CapacityPoints-CapacityCommitted)", "", "calc")
    heading(19, "Jira snapshot (written by Cowork on every refresh)")
    setting(20, "SnapshotAt", "Snapshot pulled at", None, dt.datetime(2026, 10, 2, 8, 41), "Date and time.", "calc", "yyyy-mm-dd hh:mm")
    setting(21, "SnapshotSource", "Snapshot source", "", "Copilot connector (Jira Cloud)", "Copilot connector, or CSV: <file name>.", "calc")
    setting(22, "SnapshotCount", "Use cases in snapshot", "", 16, "Compared to the last refresh to catch a short pull.", "calc")
    age = '=IF(SnapshotAt="","",ROUND(IF(SampleAsOf="",NOW(),SampleAsOf+TIME(9,0,0))-SnapshotAt,1))'
    setting(23, "SnapshotAge", "Snapshot age in days (computed)", age, age, "", "calc")

    # Stages
    heading(25, "Stages (the operating model's eight)")
    for col, t in enumerate(("Stage", "Stale after (days)", "At-risk window", "Gate owner", "Next forum"), 1):
        c = ws.cell(row=26, column=col, value=t)
        c.font, c.fill = f(10, True), INPUT_HEAD
    for i, row in enumerate(STAGES):
        for col, v in enumerate(row, 1):
            ws.cell(row=27 + i, column=col, value=v).font = f(10, color="1F3FBF" if col in (2, 3) else INK)
    for nm, col in (("StageName", "A"), ("StageStale", "B"), ("StageWindow", "C"), ("StageOwner", "D"), ("StageForum", "E")):
        name(wb, nm, "Config!$%s$27:$%s$34" % (col, col))

    heading(36, "Risk tiers (promised intake-to-approval window)")
    for col, t in enumerate(("Tier", "Promise (days)", "What"), 1):
        c = ws.cell(row=37, column=col, value=t)
        c.font, c.fill = f(10, True), INPUT_HEAD
    for i, (t, days, what) in enumerate(TIERS):
        ws.cell(row=38 + i, column=1, value=t).font = f(10)
        ws.cell(row=38 + i, column=2, value=days).font = f(10, color="1F3FBF")
        ws.cell(row=38 + i, column=3, value=what).font = f(9, color=INK3)
    name(wb, "TierName", "Config!$A$38:$A$40")
    name(wb, "TierDays", "Config!$B$38:$B$40")
    heading(42, "Functions that are always high tier")
    for i in range(8):
        c = ws.cell(row=43 + i, column=1, value=TIER_FUNCS[i] if i < len(TIER_FUNCS) else None)
        c.font, c.fill = f(10, color="1F3FBF"), INPUT_HEAD
    name(wb, "TierFuncs", "Config!$A$43:$A$50")

    # Status map
    heading(25, "Jira status → stage", col=7)
    for col, t in ((7, "Jira status (exact)"), (8, "Stage")):
        c = ws.cell(row=26, column=col, value=t)
        c.font, c.fill = f(10, True), INPUT_HEAD
    for i, (st, sg) in enumerate(STATUS_MAP):
        ws.cell(row=27 + i, column=7, value=st).font = f(10, color="1F3FBF")
        ws.cell(row=27 + i, column=8, value=sg).font = f(10, color="1F3FBF")
    name(wb, "MapStatus", "Config!$G$27:$G$66")
    name(wb, "MapStage", "Config!$H$27:$H$66")
    ws.cell(row=67, column=7, value="Add your workflow's statuses in the blank rows.").font = f(9, color=INK3, italic=True)
    dv = DataValidation(type="list", formula1='"%s"' % ",".join([s_[0] for s_ in STAGES] + ["Closed"]), allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("H27:H66")

    # Field map
    heading(25, "Jira field map (what Cowork reads into each Use Cases column)", col=10)
    for col, t in ((10, "Workbook column"), (11, "Jira field"), (12, "Note")):
        c = ws.cell(row=26, column=col, value=t)
        c.font, c.fill = f(10, True), INPUT_HEAD
    for i, (a, b, n) in enumerate(FIELD_MAP):
        ws.cell(row=27 + i, column=10, value=a).font = f(10)
        ws.cell(row=27 + i, column=11, value=b).font = f(10, color="1F3FBF")
        ws.cell(row=27 + i, column=12, value=n).font = f(9, color=INK3)
    ws.cell(row=27 + len(FIELD_MAP), column=10, value="Rename the Jira fields to whatever your project calls them.").font = f(9, color=INK3, italic=True)
    return ws


# ---------------------------------------------------------------- dashboard kit
GRID = {"A": 2, "B": 4, "C": 11, "D": 13, "E": 13, "F": 40, "G": 11, "H": 11, "I": 12, "J": 30, "K": 30, "L": 2}


def link(sheet, text, cell="A1"):
    return '=HYPERLINK("#%s!%s","%s")' % (q(sheet), cell, text)


def dash(wb, title, subtitle):
    ws = wb.create_sheet(title)
    ws.sheet_view.showGridLines = False
    for k, v in GRID.items():
        ws.column_dimensions[k].width = v
    ws["B1"] = title if title != "Home" else "AI Operating System"
    ws["B1"].font = f(20, True, BRAND)
    ws.row_dimensions[1].height = 30
    ws["B2"] = '="%s  ·  as of "&TEXT(AsOf,"ddd d mmm yyyy")' % subtitle
    ws["B2"].font = f(10, color=INK2)
    ws["G2"] = ('=IF(SampleAsOf<>"","SAMPLE DATA. Use AI-OS.xlsx for real work.",'
                'IF(SnapshotAt="","No Jira snapshot yet. Say: refresh dashboard",'
                'IF(SnapshotAge>SnapshotMaxAge,"Jira snapshot is "&SnapshotAge&" days old. Say: refresh dashboard","Jira snapshot "&TEXT(SnapshotAt,"d mmm hh:mm"))))')
    ws["G2"].font = f(9, True, "7A5200")
    ws.merge_cells("G2:K2")
    ws.conditional_formatting.add("G2:K2", FormulaRule(formula=['OR(SampleAsOf<>"",SnapshotAt="",SnapshotAge>SnapshotMaxAge)'], fill=BANNER))
    # Navigation: every dashboard links to every other.
    nav_cols = [3, 4, 5, 6, 7]
    for d_, col in zip(DASHBOARDS, nav_cols):
        c = ws.cell(row=3, column=col)
        if d_ == title:
            c.value = d_
            c.font = f(10, True, "FFFFFF")
            c.fill = NAV_ON
        else:
            c.value = link(d_, d_)
            c.font = f(10, False, LINK, underline="single")
        c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[3].height = 20
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return ws


TILES = [(3, 5), (6, 6), (7, 9), (10, 10), (11, 11)]


def tile(ws, row, slot, label, value, sub, target=None, fmt="0"):
    col, end = TILES[slot]
    for rr in range(row, row + 3):
        for cc in range(col, end + 1):
            ws.cell(row=rr, column=cc).fill = TILE
        if end > col:
            ws.merge_cells(start_row=rr, start_column=col, end_row=rr, end_column=end)
    a = ws.cell(row=row, column=col, value=link(target, label + "  ›") if target else label)
    a.font = f(9, True, LINK if target else INK3)
    a.alignment = Alignment(indent=1, vertical="bottom")
    b = ws.cell(row=row + 1, column=col, value=value)
    b.font = f(20, True, INK)
    b.number_format = fmt
    b.alignment = Alignment(indent=1, horizontal="left", vertical="center")
    c = ws.cell(row=row + 2, column=col, value=sub)
    c.font = f(9, color=INK2)
    c.alignment = Alignment(indent=1, vertical="top", wrap_text=True)
    ws.row_dimensions[row + 1].height = 30
    return b


def section(ws, row, text, sub=None, target=None):
    c = ws.cell(row=row, column=2, value=text)
    c.font = f(12, True, INK)
    if sub:
        ws.cell(row=row, column=6, value=sub).font = f(9, color=INK3, italic=True)
    if target:
        t = ws.cell(row=row, column=11, value=link(target[0], target[1]))
        t.font = f(9, False, LINK, underline="single")
        t.alignment = Alignment(horizontal="right")


def heads(ws, row, start, titles):
    for i, t in enumerate(titles):
        c = ws.cell(row=row, column=start + i, value=t)
        c.font = f(9, True, INK3)
        c.border = BOTTOM


def id_link(spec, keycol_range, k_expr, mode="LARGE"):
    """The k-th item of a ranked list, as a link to its row on the data sheet."""
    pick = "MATCH(%s(%s,%s),%s,0)" % (mode, keycol_range, k_expr, keycol_range)
    return '=IFERROR(HYPERLINK("#%s!A"&(%s+1),INDEX(%s,%s)),"")' % (q(spec.name), pick, spec.rng(spec.cols[0][0]), pick)


def lookup(spec, idcell, key, text=True):
    return '=IF(%s="","",INDEX(%s,MATCH(%s,%s,0))%s)' % (idcell, spec.rng(key), idcell, spec.rng(spec.cols[0][0]), '&""' if text else "")


def ranked(ws, top, n, spec, rank_key, fields, mode="LARGE", empty=None, number=True, wrap_cols=(6,), state_cols=()):
    """n rows of a ranked list. fields: [(col, key, is_text)] looked up by the ID in column C."""
    for k in range(1, n + 1):
        rr = top + k - 1
        if number:
            ws.cell(row=rr, column=2, value=k).font = f(9, color=INK3)
        c = ws.cell(row=rr, column=3, value=id_link(spec, spec.rng(rank_key), k, mode))
        c.font = f(10, color=LINK)
        say_cols = [col for col, key, txt in fields if key == "Say"]
        for col, key, txt in fields:
            ws.cell(row=rr, column=col, value=lookup(spec, "$C%d" % rr, key, txt))
        for col in range(3, 12):
            cell = ws.cell(row=rr, column=col)
            cell.border = BOTTOM
            if col != 3:
                cell.font = f(10, color=BRAND if col in say_cols else INK)
            cell.alignment = Alignment(vertical="top", wrap_text=col in wrap_cols)
    for col in state_cols:
        L = get_column_letter(col)
        state_format(ws, "%s%d:%s%d" % (L, top, L, top + n - 1))
    if empty:
        e = ws.cell(row=top, column=6)
        e.value = '=IF(COUNT(%s)=0,"%s",%s)' % (spec.rng(rank_key), empty, (e.value or '""')[1:] if e.value else '""')
    more = ws.cell(row=top + n, column=11, value='=IF(COUNT(%s)>%d,"+"&(COUNT(%s)-%d)&" more on the %s sheet","")' % (spec.rng(rank_key), n, spec.rng(rank_key), n, spec.name))
    more.font = f(9, color=INK3, italic=True)
    more.alignment = Alignment(horizontal="right")


def text_list(ws, top, n, spec, rank_key, text_expr, empty, mode="LARGE"):
    """A ranked list rendered as one sentence per row: ID in C, text in D:K."""
    rng = spec.rng(rank_key)
    for k in range(1, n + 1):
        rr = top + k - 1
        c = ws.cell(row=rr, column=3, value=id_link(spec, rng, k, mode))
        c.font = f(10, color=LINK)
        idc = "$C%d" % rr
        body = text_expr(idc)
        if k == 1:
            v = '=IF(%s="",IF(COUNT(%s)=0,"%s",""),%s)' % (idc, rng, empty, body)
        else:
            v = '=IF(%s="","",%s)' % (idc, body)
        t = ws.cell(row=rr, column=4, value=v)
        t.font = f(10, italic=False)
        t.alignment = Alignment(vertical="top", wrap_text=True)
        ws.merge_cells(start_row=rr, start_column=4, end_row=rr, end_column=11)
        for col in range(3, 12):
            ws.cell(row=rr, column=col).border = BOTTOM
    return top + n


def L(spec, key, idc):
    """Lookup of a field by ID for use inside a larger text formula."""
    return "INDEX(%s,MATCH(%s,%s,0))" % (spec.rng(key), idc, spec.rng(spec.cols[0][0]))


def bar_chart(ws, anchor, cats, series, colors, horizontal=False, stacked=False, h=6.2, w=12, legend=False):
    ch = BarChart()
    ch.type = "bar" if horizontal else "col"
    ch.style = 1
    if stacked:
        ch.grouping, ch.overlap = "stacked", 100
    ch.legend = None
    if legend:
        from openpyxl.chart.legend import Legend
        ch.legend = Legend()
        ch.legend.position = "b"
    ch.y_axis.majorGridlines = None
    ch.y_axis.delete = True
    if horizontal:
        ch.x_axis.scaling.orientation = "maxMin"
    for ref in series:
        ch.add_data(ref, titles_from_data=True)
    ch.set_categories(cats)
    for sr, col in zip(ch.series, colors):
        sr.graphicalProperties.solidFill = col
        sr.graphicalProperties.line.solidFill = "FFFFFF"
    ch.gapWidth = 60
    dl = DataLabelList()
    dl.showVal = True
    dl.showSerName = dl.showCatName = dl.showLegendKey = dl.showPercent = False
    dl.numFmt = "0;-0;;"  # hide zero labels on stacked segments
    ch.dataLabels = dl
    ch.height, ch.width = h, w
    ws.add_chart(ch, anchor)


# Shorthands for counting over the Use Cases sheet.
def ucount(*pairs):
    return "COUNTIFS(" + ",".join("%s,%s" % (UC.rng(k), v) for k, v in pairs) + ")"


OPEN = ("StageN", '">0"')


# ---------------------------------------------------------------- the five dashboards
def build_home(wb):
    ws = dash(wb, "Home", "My desk")
    r = 5
    tile(ws, r, 0, "NEEDS YOU", '=COUNTIFS(Inventory!$K:$K,"Open")+COUNTIF(Inventory!$K:$K,"Unconfirmed")',
         '=COUNTIFS(Inventory!$K:$K,"Open",Inventory!$C:$C,"Decision")&" decisions · "&COUNTIFS(Inventory!$K:$K,"Open",Inventory!$C:$C,"Conflict")&" conflicts · "&COUNTIF(Inventory!$K:$K,"Unconfirmed")&" unconfirmed"')
    tile(ws, r, 1, "PORTFOLIO", "=" + ucount(("Health", '"Overdue"')),
         '="overdue · "&' + ucount(("Health", '"At risk"')) + '&" at risk · "&' + ucount(("Fresh", '"Stale"')) + '&" stale"', "Portfolio")
    tile(ws, r, 2, "WEEKLY STATUS", "='Weekly Status'!$C$6", '="Flow "&\'Weekly Status\'!$F$6&" · Value "&\'Weekly Status\'!$G$6&" · Risk "&\'Weekly Status\'!$J$6', "Weekly Status")
    tile(ws, r, 3, "GATES", "=" + ucount(("Gate", '"Critical"')), '="critical · "&' + ucount(("Clock", '"Over"')) + '&" over tier window"', "Gates")
    tile(ws, r, 4, "DONE THIS WEEK", '=COUNTIF(Done!$G:$G,"Yes")', '=COUNTIF(Done!$F:$F,WeekStart-7)&" last week"')
    state_format(ws, "G6:I6")

    r = 9
    section(ws, r, "Needs you", "Open decisions, conflicts and unconfirmed items, worst first.")
    heads(ws, r + 1, 2, ["#", "ID", "Type", "Topic", "Summary", "Age", "Severity", "Use case", "From", "Say this"])
    ranked(ws, r + 2, 8, INV, "Key", [(4, "Type", True), (5, "Topic", True), (6, "Summary", True), (7, "Age", False), (8, "Sev", True), (9, "Jira", True), (10, "From", True), (11, "Say", True)],
           empty="Nothing open. The inventory is clear.", state_cols=(8,))
    for rr in range(r + 2, r + 10):
        ws.cell(row=rr, column=7).alignment = Alignment(horizontal="center", vertical="top")

    r = 21
    section(ws, r, "Use cases needing attention", "Overdue, flagged, failing their gate, at risk, stale or over their tier window.", ("Portfolio", "Portfolio  ›"))
    heads(ws, r + 1, 2, ["#", "Key", "Stage", "Owner", "Use case", "Days to target", "Health", "Gate", "Why", "Say this"])
    ranked(ws, r + 2, 8, UC, "SevKey", [(4, "Stage", True), (5, "Owner", True), (6, "Name", True), (7, "DaysTo", False), (8, "Health", True), (9, "Gate", True), (10, "Why", True), (11, "Say", True)],
           empty="Nothing needs attention.", wrap_cols=(6, 10), state_cols=(8, 9))
    for rr in range(r + 2, r + 10):
        ws.cell(row=rr, column=7).alignment = Alignment(horizontal="center", vertical="top")

    r = 33
    section(ws, r, "Done this week", "Feeds the weekly report. Say: done: <what you finished>", ("Weekly Status", "Weekly status  ›"))
    heads(ws, r + 1, 3, ["Date", "Use case", "Topic", "Accomplishment"])
    for k in range(1, 9):
        rr = r + 1 + k
        pick = "MATCH(LARGE(%s,%d),%s,0)" % (DONE.rng("Key"), k, DONE.rng("Key"))
        c = ws.cell(row=rr, column=3, value="=IFERROR(INDEX(%s,%s),\"\")" % (DONE.rng("Date"), pick))
        c.number_format = "ddd d mmm"
        ws.cell(row=rr, column=4, value='=IF($C%d="","",INDEX(%s,%s)&"")' % (rr, DONE.rng("Jira"), pick))
        ws.cell(row=rr, column=5, value='=IF($C%d="","",INDEX(%s,%s)&"")' % (rr, DONE.rng("Topic"), pick))
        ws.cell(row=rr, column=6, value='=IF($C%d="","",INDEX(%s,%s)&"")' % (rr, DONE.rng("What"), pick))
        ws.merge_cells(start_row=rr, start_column=6, end_row=rr, end_column=11)
        for col in range(3, 12):
            cell = ws.cell(row=rr, column=col)
            cell.border = BOTTOM
            cell.font = f(10)
            cell.alignment = Alignment(vertical="top", horizontal="left")
    ws.cell(row=r + 2, column=6).value = '=IF(COUNTIF(Done!$G:$G,"Yes")=0,"Nothing logged this week yet.",' + ws.cell(row=r + 2, column=6).value[1:] + ")"

    r = 44
    section(ws, r, "Accomplishments per week", "Last eight weeks.")
    heads(ws, r + 1, 3, ["Week of", "Done"])
    for i in range(8):
        rr = r + 2 + i
        c = ws.cell(row=rr, column=3, value="=WeekStart-7*%d" % (7 - i))
        c.number_format = "d mmm"
        c.font = f(10)
        c.alignment = Alignment(horizontal="left")
        ws.cell(row=rr, column=4, value="=COUNTIF(Done!$F:$F,$C%d)" % rr).font = f(10)
    bar_chart(ws, "F%d" % (r + 1), Reference(ws, min_col=3, min_row=r + 2, max_row=r + 9),
              [Reference(ws, min_col=4, min_row=r + 1, max_row=r + 9)], [SERIES1], h=5.2, w=12)
    return ws


def build_portfolio(wb):
    ws = dash(wb, "Portfolio", "Where every use case stands")
    r = 5
    tile(ws, r, 0, "IN FLIGHT", "=" + ucount(OPEN), '=' + ucount(("Health", '"On track"')) + '&" on track · "&' + ucount(("Stage", '"Closed"')) + '&" closed"')
    tile(ws, r, 1, "OVERDUE", "=" + ucount(("Health", '"Overdue"')), '=' + ucount(("Health", '"At risk"')) + '&" more at risk inside their window"', "Weekly Status")
    tile(ws, r, 2, "STALE", "=" + ucount(("Fresh", '"Stale"')), '=' + ucount(("Fresh", '"Aging"')) + '&" aging · no update past their stage cadence"')
    tile(ws, r, 3, "GATES CRITICAL", "=" + ucount(("Gate", '"Critical"')), '="failing the gate for the stage they are in"', "Gates")
    tile(ws, r, 4, "CAPACITY", '=CapacityCommitted&" of "&CapacityPoints', '="points committed · "&CapacityOpen&" open · "&' + ucount(("Line", '"Fits"')) + '&" fit"')

    r = 9
    section(ws, r, "Pipeline by stage", "Health against each use case's target date for the stage it is in.", ("Gates", "Gates by stage  ›"))
    heads(ws, r + 1, 3, ["Stage", "On track", "At risk", "Overdue", "Total", "Stale"])
    for i, st in enumerate([x[0] for x in STAGES]):
        rr = r + 2 + i
        ws.cell(row=rr, column=3, value=st).font = f(10)
        ws.cell(row=rr, column=4, value="=" + ucount(("Stage", "$C%d" % rr), ("Health", '"On track"')))
        ws.cell(row=rr, column=5, value="=" + ucount(("Stage", "$C%d" % rr), ("Health", '"At risk"')))
        ws.cell(row=rr, column=6, value="=" + ucount(("Stage", "$C%d" % rr), ("Health", '"Overdue"')))
        ws.cell(row=rr, column=7, value="=SUM(D%d:F%d)" % (rr, rr))
        ws.cell(row=rr, column=8, value="=" + ucount(("Stage", "$C%d" % rr), ("Fresh", '"Stale"')))
        for col in range(3, 9):
            c = ws.cell(row=rr, column=col)
            c.border = BOTTOM
            if col > 3:
                c.alignment = Alignment(horizontal="center")
                c.font = f(10)
    bar_chart(ws, "I%d" % (r + 1), Reference(ws, min_col=3, min_row=r + 2, max_row=r + 9),
              [Reference(ws, min_col=c, min_row=r + 1, max_row=r + 9) for c in (4, 5, 6)],
              [BAR_GREEN, BAR_AMBER, BAR_RED], horizontal=True, stacked=True, h=4.9, w=11, legend=True)

    r = 20
    section(ws, r, "What starts next: WSJF against capacity", "Ranked by WSJF. Capacity decides how far down the list we get; once one doesn't fit, everything below waits.")
    ws.cell(row=r + 1, column=3, value='="Committed "&CapacityCommitted&" of "&CapacityPoints&" points in Delivery and Value. Open: "&CapacityOpen&" points."').font = f(10, True)
    heads(ws, r + 2, 2, ["#", "Key", "Stage", "Owner", "Use case", "WSJF", "Size", "Cum. points", "Capacity line", "Value $K"])
    ranked(ws, r + 3, 8, UC, "Rank", [(4, "Stage", True), (5, "Owner", True), (6, "Name", True), (7, "WSJF", False), (8, "Size", False), (9, "Cum", False), (10, "Line", True), (11, "Value", False)],
           mode="SMALL", empty="Nothing scored yet.", state_cols=(10,))
    for rr in range(r + 3, r + 11):
        for col in (7, 8, 9, 11):
            ws.cell(row=rr, column=col).alignment = Alignment(horizontal="center", vertical="top")

    r = 33
    section(ws, r, "All open use cases", "In stage order. Click a key for its record; the Use Case tab shows one in full.", ("Use Case", "Use case detail  ›"))
    heads(ws, r + 1, 2, ["", "Key", "Stage", "Function", "Use case", "Health", "Freshness", "Tier", "Gate", "Next forum"])
    ranked(ws, r + 2, 16, UC, "Order", [(4, "Stage", True), (5, "Func", True), (6, "Name", True), (7, "Health", True), (8, "Fresh", True), (9, "Tier", True), (10, "Gate", True), (11, "Forum", True)],
           mode="SMALL", number=False, empty="No open use cases. Say: refresh dashboard", state_cols=(7, 8, 10))

    r = 52
    section(ws, r, "Value: realized vs projected", "$K annual run-rate, by quarter, from the Value sheet.")
    heads(ws, r + 1, 3, ["Quarter", "Projected", "Realized", "Realized %"])
    for i in range(6):
        rr = r + 2 + i
        cnt = "COUNT(%s)" % VAL.rng("Proj")
        idx = "MAX(0,%s-6)+%d" % (cnt, i + 1)
        for col, key in ((3, "Q"), (4, "Proj"), (5, "Real")):
            c = ws.cell(row=rr, column=col, value='=IF(%s>%s,"",INDEX(%s,%s))' % (idx, cnt, VAL.rng(key), idx))
            c.font = f(10)
            c.alignment = Alignment(horizontal="left")
        c = ws.cell(row=rr, column=6, value='=IF(OR(C%d="",D%d=0),"",E%d/D%d)' % (rr, rr, rr, rr))
        c.number_format = "0%"
        c.font = f(10)
        c.alignment = Alignment(horizontal="left")
    bar_chart(ws, "G%d" % (r + 1), Reference(ws, min_col=3, min_row=r + 2, max_row=r + 7),
              [Reference(ws, min_col=4, min_row=r + 1, max_row=r + 7), Reference(ws, min_col=5, min_row=r + 1, max_row=r + 7)],
              [SERIES1, SERIES2], h=5.6, w=13, legend=True)

    r = 64
    section(ws, r, "Portfolio mix", "Open use cases only.")
    heads(ws, r + 1, 3, ["Risk tier", "Open", "", "Impact", "Open", "", "Risk flag", "Open"])
    for i, (t, _, _) in enumerate(TIERS):
        rr = r + 2 + i
        ws.cell(row=rr, column=3, value=t)
        ws.cell(row=rr, column=4, value="=" + ucount(OPEN, ("Tier", "$C%d" % rr)))
    for i, imp in enumerate(["revenue", "cost", "cycle", "risk", "insight"]):
        rr = r + 2 + i
        ws.cell(row=rr, column=6, value=imp)
        ws.cell(row=rr, column=7, value="=" + ucount(OPEN, ("Impact", '"*%s*"' % imp)))
    for i, fl in enumerate(["NPI", "Reg report", "No human review"]):
        rr = r + 2 + i
        ws.cell(row=rr, column=9, value=fl)
        ws.cell(row=rr, column=10, value="=" + ucount(OPEN, ("Risk", '"*%s*"' % fl)))
    for rr in range(r + 2, r + 7):
        for col in (3, 4, 6, 7, 9, 10):
            ws.cell(row=rr, column=col).font = f(10)
            ws.cell(row=rr, column=col).alignment = Alignment(horizontal="left")
    return ws


def build_weekly(wb):
    ws = dash(wb, "Weekly Status", "The output of the three sittings")
    ws["B4"] = '="Week of "&TEXT(WeekStart,"d mmm yyyy")&". Every line is computed from the Use Cases and Inventory sheets."'
    ws["B4"].font = f(10, color=INK3, italic=True)

    overdue = ucount(("Health", '"Overdue"'))
    atrisk = ucount(("Health", '"At risk"'))
    real = 'IFERROR(SUMIFS(%s,%s,"Y")/SUMIFS(%s,%s,"Y"),"")' % (VAL.rng("Real"), VAL.rng("Done"), VAL.rng("Proj"), VAL.rng("Done"))
    flagged = '(' + ucount(OPEN) + '-' + ucount(OPEN, ("Risk", '""')) + ')'
    held = ucount(("Stage", '"Design"'), ("Gate", '"Critical"'))
    # Row 5 labels, row 6 RAG word, row 7 metric, row 8 note. Overall in C:E, then Flow F, Value G:I, Risk J:K.
    blocks = [
        ((3, 5), "OVERALL", '=IF(OR(F6="Red",G6="Red",J6="Red"),"Red",IF(OR(F6="Amber",G6="Amber",J6="Amber"),"Amber","Green"))', '="worst of the three"', '=""'),
        ((6, 6), "FLOW", '=IF(%s=0,"Green",IF(%s<=2,"Amber","Red"))' % (overdue, overdue), '=%s&" overdue"' % overdue, '=%s&" more inside their at-risk window."' % atrisk),
        ((7, 9), "VALUE", '=IF(%s="","Amber",IF(%s>=0.9,"Green",IF(%s>=0.75,"Amber","Red")))' % (real, real, real), '=IF(%s="","not measured",TEXT(%s,"0%%")&" realized")' % (real, real),
         '="of projected value across closed quarters: $"&TEXT(SUMIFS(%s,%s,"Y")/1000,"0.0")&"M of $"&TEXT(SUMIFS(%s,%s,"Y")/1000,"0.0")&"M."' % (VAL.rng("Real"), VAL.rng("Done"), VAL.rng("Proj"), VAL.rng("Done"))),
        ((10, 11), "RISK AND CONTROLS", '=IF(%s>0,"Amber","Green")' % held, '=%s&" of "&%s&" carry a risk flag"' % (flagged, ucount(OPEN)), '=IF(%s>0,%s&" held at the design gate.","Nothing held at the design gate.")' % (held, held)),
    ]
    for (c0, c1), label, rag, metric, note in blocks:
        for rr in range(5, 9):
            for cc in range(c0, c1 + 1):
                ws.cell(row=rr, column=cc).fill = TILE
            if c1 > c0:
                ws.merge_cells(start_row=rr, start_column=c0, end_row=rr, end_column=c1)
        ws.cell(row=5, column=c0, value=label).font = f(9, True, INK3)
        g = ws.cell(row=6, column=c0, value=rag)
        g.font = f(16, True)
        ws.cell(row=7, column=c0, value=metric).font = f(10, True)
        n = ws.cell(row=8, column=c0, value=note)
        n.font = f(9, color=INK2)
        for rr in range(5, 9):
            ws.cell(row=rr, column=c0).alignment = Alignment(indent=1, vertical="center", wrap_text=True)
    ws.row_dimensions[6].height = 26
    ws.row_dimensions[8].height = 28
    for col in "CFGJ":
        for label, (fill, text) in (("Red", RED), ("Amber", AMBER), ("Green", GREEN)):
            ws.conditional_formatting.add("%s6" % col, CellIsRule(operator="equal", formula=['"%s"' % label],
                                          fill=PatternFill("solid", fgColor=fill), font=Font(name=FONT, color=text, bold=True, size=16)))

    def sitting(row, title, when):
        ws.cell(row=row, column=2, value=title).font = f(13, True, BRAND)
        ws.cell(row=row, column=6, value=when).font = f(9, color=INK3, italic=True)
        for col in range(2, 12):
            ws.cell(row=row, column=col).border = Border(bottom=Side(style="medium", color=BRAND))
        return row + 1

    def sub(row, text):
        ws.cell(row=row, column=3, value=text).font = f(10, True, INK2)
        return row + 1

    def uc_label(idc):
        return '%s' % L(UC, "Name", idc)

    r = 10
    r = sitting(r, "Weekly Intake", "Every Monday, 15 min. Decides what comes in.")
    r = sub(r, "What came in")
    r = text_list(ws, r, 4, UC, "NewWk", lambda i: uc_label(i) + '&" · from "&' + L(UC, "Sponsor", i) + '&", "&' + L(UC, "Func", i), "Nothing new at the front door.") + 1
    r = sub(r, "Accepted, rejected or deferred")
    r = text_list(ws, r, 4, UC, "DecWk", lambda i: uc_label(i) + '&" · "&' + L(UC, "DecText", i), "No triage decisions this week.") + 1
    r = sub(r, "Tier and owner assigned")
    r = text_list(ws, r, 4, UC, "NewWk", lambda i: uc_label(i) + '&" · "&' + L(UC, "Tier", i) + '&" risk, "&' + L(UC, "TierDays", i) + '&" days. Owner "&' + L(UC, "Owner", i) + '&", sponsor "&' + L(UC, "Sponsor", i), "Nothing to assign.") + 1

    r = sitting(r, "Tactical Standup", "Every Tuesday, 30 min. Unblocks the work in flight.")
    r = sub(r, "Work stream health")
    for st in ("Discovery", "Design", "Delivery", "Scale"):
        n = ucount(("Stage", '"%s"' % st))
        red = '(%s+%s)' % (ucount(("Stage", '"%s"' % st), ("Health", '"Overdue"')), ucount(("Stage", '"%s"' % st), ("Health", '"<>Overdue"'), ("Gate", '"Critical"')))
        ws.cell(row=r, column=4, value='="%s: "&%s&" use case"&IF(%s=1,"","s")&IF(%s>0,", "&%s&" red","")&"."' % (st, n, n, red, red)).font = f(10)
        ws.merge_cells(start_row=r, start_column=4, end_row=r, end_column=11)
        r += 1
    r += 1
    r = sub(r, "Blockers flagged")
    r = text_list(ws, r, 4, UC, "Block", lambda i: uc_label(i) + '&": waiting on "&' + L(UC, "Waiting", i) + '&" ("&' + L(UC, "Stage", i) + '&")"', "Nothing is waiting on anyone outside the team.") + 1
    r = sub(r, "Fed to the Council")
    r = text_list(ws, r, 4, UC, "Council", lambda i: uc_label(i) + '&": "&' + L(UC, "Why", i), "Nothing to escalate.") + 1

    r = sitting(r, "Portfolio Council", "Run by the Director, every Thursday, 75 min. Decides.")
    r = sub(r, "What's new")
    r = text_list(ws, r, 4, INV, "NewWk", lambda i: L(INV, "Summary", i) + '&" ("&' + L(INV, "From", i) + '&IF(' + L(INV, "Conf", i) + '="Unconfirmed",", unconfirmed","")&")"', "Nothing new logged this week.") + 1
    r = sub(r, "What we need to know")
    ws.cell(row=r, column=4, value='=G7&" of projected value. "&' + atrisk + '&" use cases at risk, "&' + overdue + '&" overdue."').font = f(10)
    ws.merge_cells(start_row=r, start_column=4, end_row=r, end_column=11)
    r += 1
    r = text_list(ws, r, 4, INV, "KnowWk", lambda i: L(INV, "Summary", i) + '&" ("&' + L(INV, "From", i) + '&IF(' + L(INV, "Conf", i) + '="Unconfirmed",", unconfirmed","")&")"', "Nothing else logged this week.") + 1
    r = sub(r, "What needs a decision or discussion")
    r = text_list(ws, r, 6, INV, "OpenDec", lambda i: L(INV, "Summary", i) + '&" Open "&' + L(INV, "Age", i) + '&" days."', "No open decisions.") + 1
    ws.cell(row=r, column=3, value="Say draft weekly report to turn this into the Word draft, or prep for <sitting> for an agenda.").font = f(9, color=INK3, italic=True)
    return ws


def build_gates(wb):
    ws = dash(wb, "Gates", "The eight stages and what each gate needs")
    r = 5
    tile(ws, r, 0, "GATES CRITICAL", "=" + ucount(("Gate", '"Critical"')), '="failing the gate for their current stage"')
    tile(ws, r, 1, "GATES WARNING", "=" + ucount(("Gate", '"Warning"')), '="work still to do before the gate"')
    tile(ws, r, 2, "OVER TIER WINDOW", "=" + ucount(("Clock", '"Over"')), '="of "&' + ucount(("Clock", '"<>Past approval"'), OPEN) + '&" short of approval"')
    tile(ws, r, 3, "INTAKE TO DECISION", '=IFERROR(ROUND(SUMPRODUCT((%s<>"")*(%s<>""),%s-%s)/SUMPRODUCT((%s<>"")*(%s<>"")),0),"")' % (UC.rng("Decided"), UC.rng("Opened"), UC.rng("Decided"), UC.rng("Opened"), UC.rng("Decided"), UC.rng("Opened")),
         '="average days, all decided use cases"')
    tile(ws, r, 4, "CLOSED", "=" + ucount(("Stage", '"Closed"')), '=' + ucount(("Outcome", '"Declined"')) + '&" declined · "&' + ucount(("Outcome", '"Transferred"')) + '&" transferred"')

    r = 9
    section(ws, r, "By stage", "Gate graded only at the stage a use case is in, so a red means something.", ("Portfolio", "Portfolio  ›"))
    heads(ws, r + 1, 3, ["Stage", "Gate owner", "In stage", "Good", "Warning", "Critical", "Overdue", "Stale", "Next forum"])
    for i in range(8):
        rr = r + 2 + i
        ws.cell(row=rr, column=3, value="=INDEX(StageName,%d)" % (i + 1))
        ws.cell(row=rr, column=4, value="=INDEX(StageOwner,%d)" % (i + 1))
        ws.cell(row=rr, column=5, value="=" + ucount(("Stage", "$C%d" % rr)))
        ws.cell(row=rr, column=6, value="=" + ucount(("Stage", "$C%d" % rr), ("Gate", '"Good"')))
        ws.cell(row=rr, column=7, value="=" + ucount(("Stage", "$C%d" % rr), ("Gate", '"Warning"')))
        ws.cell(row=rr, column=8, value="=" + ucount(("Stage", "$C%d" % rr), ("Gate", '"Critical"')))
        ws.cell(row=rr, column=9, value="=" + ucount(("Stage", "$C%d" % rr), ("Health", '"Overdue"')))
        ws.cell(row=rr, column=10, value="=" + ucount(("Stage", "$C%d" % rr), ("Fresh", '"Stale"')))
        ws.cell(row=rr, column=11, value="=INDEX(StageForum,%d)" % (i + 1))
        for col in range(3, 12):
            c = ws.cell(row=rr, column=col)
            c.border = BOTTOM
            c.font = f(10)
            if 5 <= col <= 10:
                c.alignment = Alignment(horizontal="center")
    for col, rule in (("H", RED), ("G", AMBER)):
        ws.conditional_formatting.add("%s%d:%s%d" % (col, r + 2, col, r + 9), CellIsRule(operator="greaterThan", formula=["0"],
                                      fill=PatternFill("solid", fgColor=rule[0]), font=Font(name=FONT, color=rule[1], bold=True)))
    ws.conditional_formatting.add("I%d:I%d" % (r + 2, r + 9), CellIsRule(operator="greaterThan", formula=["0"],
                                  fill=PatternFill("solid", fgColor=RED[0]), font=Font(name=FONT, color=RED[1], bold=True)))

    r = 20
    section(ws, r, "Tier clock", "The tier sets the promised intake-to-approval window. It is computed from the risk flags and function, not chosen.")
    heads(ws, r + 1, 3, ["Tier", "Promise", "Short of approval", "Over window", "Average age", "Intake to decision"])
    for i in range(3):
        rr = r + 2 + i
        ws.cell(row=rr, column=3, value="=INDEX(TierName,%d)" % (i + 1))
        ws.cell(row=rr, column=4, value='=INDEX(TierDays,%d)&" days"' % (i + 1))
        short = ucount(("Tier", "$C%d" % rr), ("Clock", '"<>Past approval"'), OPEN)
        ws.cell(row=rr, column=5, value="=" + short)
        ws.cell(row=rr, column=6, value="=" + ucount(("Tier", "$C%d" % rr), ("Clock", '"Over"')))
        ws.cell(row=rr, column=7, value='=IFERROR(ROUND(AVERAGEIFS(%s,%s,$C%d,%s,"<>Past approval",%s,">0"),0)&" days","")' % (UC.rng("Age"), UC.rng("Tier"), rr, UC.rng("Clock"), UC.rng("StageN")))
        ws.cell(row=rr, column=8, value='=IFERROR(ROUND(SUMPRODUCT((%s=$C%d)*(%s<>""),%s-%s)/SUMPRODUCT((%s=$C%d)*(%s<>"")),0)&" days","")' % (
            UC.rng("Tier"), rr, UC.rng("Decided"), UC.rng("Decided"), UC.rng("Opened"), UC.rng("Tier"), rr, UC.rng("Decided")))
        for col in range(3, 9):
            c = ws.cell(row=rr, column=col)
            c.border = BOTTOM
            c.font = f(10)
            if col >= 5:
                c.alignment = Alignment(horizontal="center")
    ws.conditional_formatting.add("F%d:F%d" % (r + 2, r + 4), CellIsRule(operator="greaterThan", formula=["0"],
                                  fill=PatternFill("solid", fgColor=AMBER[0]), font=Font(name=FONT, color=AMBER[1], bold=True)))

    r = 26
    section(ws, r, "Gate exceptions", "Every use case failing the gate for the stage it is in, with what the gate owner needs to see.")
    heads(ws, r + 1, 2, ["#", "Key", "Stage", "Owner", "Use case", "Tier", "Gate", "Gate owner", "What the gate needs", "Say this"])
    ranked(ws, r + 2, 10, UC, "GateKey", [(4, "Stage", True), (5, "Owner", True), (6, "Name", True), (7, "Tier", True), (8, "Gate", True), (10, "Need", True), (11, "Say", True)],
           empty="No gate exceptions.", wrap_cols=(6, 10), state_cols=(8,))
    for k in range(10):
        rr = r + 2 + k
        ws.cell(row=rr, column=9, value='=IF($C%d="","",IFERROR(INDEX(StageOwner,MATCH($D%d,StageName,0)),""))' % (rr, rr))
        ws.cell(row=rr, column=9).font = f(10)
    ws.cell(row=r + 13, column=3, value="Oldest first. Gate graded only for the stage each use case is in now.").font = f(9, color=INK3, italic=True)
    return ws


def build_usecase(wb, sample):
    ws = dash(wb, "Use Case", "One use case, end to end")
    ws["B5"] = "Pick a use case"
    ws["B5"].font = f(11, True)
    sel = ws["E5"]
    sel.value = "AI-003" if sample else None
    sel.font = f(14, True, BRAND)
    sel.fill = INPUT_HEAD
    sel.alignment = Alignment(horizontal="center")
    dv = DataValidation(type="list", formula1="=%s" % UC.rng("Key"), allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("E5")
    ws["F5"] = '=IF(E5="","Choose a key from the list, or say: show <KEY>",IF(UCRow="","Not found on the Use Cases sheet",INDEX(%s,UCRow)))' % UC.rng("Name")
    ws["F5"].font = f(14, True)
    ws["K5"] = '=IF(UCRow="","",HYPERLINK("#%s!A"&(UCRow+1),"Record on Use Cases  ›"))' % q(UC.name)
    ws["K5"].font = f(9, False, LINK, underline="single")
    ws["K5"].alignment = Alignment(horizontal="right")
    ws["L5"] = '=IFERROR(MATCH(E5,%s,0),"")' % UC.rng("Key")
    ws["L5"].font = f(8, color="FFFFFF")
    name(wb, "UCSel", "%s!$E$5" % q("Use Case"))
    name(wb, "UCRow", "%s!$L$5" % q("Use Case"))

    def val(key, text=True):
        return '=IF(UCRow="","",INDEX(%s,UCRow)%s)' % (UC.rng(key), '&""' if text else "")

    # Status tiles
    r = 7
    tile(ws, r, 0, "STAGE", val("Stage"), '=IF(UCRow="","","Jira: "&INDEX(%s,UCRow)&" · next: "&INDEX(%s,UCRow))' % (UC.rng("Status"), UC.rng("Forum")), "Gates")
    tile(ws, r, 1, "HEALTH", val("Health"), '=IF(UCRow="","",IF(INDEX(%s,UCRow)="","no target",INDEX(%s,UCRow)&" days to target, "&TEXT(INDEX(%s,UCRow),"d mmm")))' % (UC.rng("DaysTo"), UC.rng("DaysTo"), UC.rng("Target")))
    tile(ws, r, 2, "FRESHNESS", val("Fresh"), '=IF(UCRow="","","last update "&INDEX(%s,UCRow)&" days ago")' % UC.rng("Since"))
    tile(ws, r, 3, "TIER", val("Tier"), '=IF(UCRow="","",INDEX(%s,UCRow)&"-day promise · "&INDEX(%s,UCRow)&" days open · "&INDEX(%s,UCRow))' % (UC.rng("TierDays"), UC.rng("Age"), UC.rng("Clock")))
    tile(ws, r, 4, "CAPACITY", '=IF(UCRow="","",IF(INDEX(%s,UCRow)="","Not ranked",INDEX(%s,UCRow)))' % (UC.rng("Cap"), UC.rng("Cap")),
         '=IF(UCRow="","",IF(INDEX(%s,UCRow)="","WSJF "&IF(INDEX(%s,UCRow)="","not scored",INDEX(%s,UCRow)),"WSJF rank "&INDEX(%s,UCRow)&" · "&INDEX(%s,UCRow)))' % (UC.rng("Rank"), UC.rng("WSJF"), UC.rng("WSJF"), UC.rng("Rank"), UC.rng("Line")), "Portfolio")
    state_format(ws, "C8:K8")

    # Gate strip
    r = 11
    section(ws, r, "The eight gates", "Passed gates stay passed. The current one is graded; later ones are pending.")
    for i in range(8):
        col = 3 + i
        h = ws.cell(row=r + 1, column=col, value="=INDEX(StageName,%d)" % (i + 1))
        h.font = f(9, True, INK3)
        h.alignment = Alignment(horizontal="center")
        g = ws.cell(row=r + 2, column=col, value='=IF(UCRow="","",IF(INDEX(%s,UCRow)="Closed","Closed",IF(INDEX(%s,UCRow)="",'
                                                 '"Pending",IF(INDEX(%s,UCRow)>%d,"Passed",IF(INDEX(%s,UCRow)=%d,INDEX(%s,UCRow),"Pending")))))' % (
                                                     UC.rng("Stage"), UC.rng("StageN"), UC.rng("StageN"), i + 1, UC.rng("StageN"), i + 1, UC.rng("Gate")))
        g.alignment = Alignment(horizontal="center")
        g.font = f(10, True)
        g.border = BOTTOM
    state_format(ws, "C%d:J%d" % (r + 2, r + 2))
    n = ws.cell(row=r + 3, column=3, value='=IF(UCRow="","",IF(INDEX(%s,UCRow)="","Nothing outstanding at this gate.","Gate needs: "&INDEX(%s,UCRow)&" (gate owner: "&IFERROR(INDEX(StageOwner,INDEX(%s,UCRow)),"")&")"))' % (UC.rng("Need"), UC.rng("Need"), UC.rng("StageN")))
    n.font = f(10, True, INK)
    ws.merge_cells(start_row=r + 3, start_column=3, end_row=r + 3, end_column=11)

    # Fields
    r = 16
    section(ws, r, "The record", "As Jira holds it. Change it in Jira, then say refresh dashboard.")
    left = [("Function", "Func", True), ("Owner", "Owner", True), ("Sponsor", "Sponsor", True), ("Opened", "Opened", False), ("Updated", "Updated", False),
            ("Stage target", "Target", False), ("Decided", "Decided", False), ("Waiting on", "Waiting", True)]
    right = [("Value $K", "Value", True), ("Size (points)", "Size", True), ("WSJF", "WSJF", True), ("Risk flags", "Risk", True), ("Impact", "Impact", True),
             ("Success metric", "Metric", True), ("Data ready", "Data", True), ("Baseline", "Baseline", True)]
    for i, ((la, ka, ta), (lb, kb, tb)) in enumerate(zip(left, right)):
        rr = r + 1 + i
        ws.cell(row=rr, column=3, value=la).font = f(9, True, INK3)
        c = ws.cell(row=rr, column=5, value=val(ka, ta))
        c.font = f(10)
        if not ta:
            c.number_format = "yyyy-mm-dd"
        c.alignment = Alignment(horizontal="left")
        ws.merge_cells(start_row=rr, start_column=5, end_row=rr, end_column=6)
        ws.cell(row=rr, column=7, value=lb).font = f(9, True, INK3)
        c2 = ws.cell(row=rr, column=9, value=val(kb, tb))
        c2.font = f(10)
        c2.alignment = Alignment(horizontal="left")
        ws.merge_cells(start_row=rr, start_column=9, end_row=rr, end_column=11)
        for col in range(3, 12):
            ws.cell(row=rr, column=col).border = BOTTOM

    r = 26
    section(ws, r, "In the inventory", "Every Inventory row that names this use case, newest first.")
    heads(ws, r + 1, 2, ["", "ID", "Type", "Date", "Summary", "", "State", "From", "", "Say this"])
    ranked(ws, r + 2, 6, INV, "Sel", [(4, "Type", True), (5, "Date", False), (6, "Summary", True), (8, "State", True), (9, "From", True), (11, "Say", True)],
           number=False, empty="Nothing logged against this use case.", state_cols=())
    for rr in range(r + 2, r + 8):
        ws.cell(row=rr, column=5).number_format = "yyyy-mm-dd"
        ws.cell(row=rr, column=5).alignment = Alignment(horizontal="left", vertical="top")
        ws.merge_cells(start_row=rr, start_column=6, end_row=rr, end_column=7)

    r = 36
    section(ws, r, "Done against it", "From the Done log, newest first.")
    for k in range(1, 6):
        rr = r + k
        pick = "MATCH(LARGE(%s,%d),%s,0)" % (DONE.rng("Sel"), k, DONE.rng("Sel"))
        c = ws.cell(row=rr, column=3, value='=IFERROR(INDEX(%s,%s),"")' % (DONE.rng("Date"), pick))
        c.number_format = "yyyy-mm-dd"
        c.alignment = Alignment(horizontal="left")
        t = ws.cell(row=rr, column=4, value='=IF($C%d="",%s,INDEX(%s,%s)&"")' % (rr, '"Nothing logged yet."' if k == 1 else '""', DONE.rng("What"), pick))
        ws.merge_cells(start_row=rr, start_column=4, end_row=rr, end_column=11)
        for col in range(3, 12):
            ws.cell(row=rr, column=col).border = BOTTOM
            ws.cell(row=rr, column=col).font = f(10)

    r = 43
    section(ws, r, "Say this in Cowork")
    for i, cmd in enumerate(['="draft Jira update for "&E5', '="what\'s open on "&IF(UCRow="","<topic>",IF(INDEX(%s,UCRow)="","<topic>",INDEX(%s,UCRow)))' % (UC.rng("Topic"), UC.rng("Topic")),
                             '="log this: <note about "&E5&">"', '="prep for "&IF(UCRow="","<sitting>",INDEX(%s,UCRow))' % UC.rng("Forum")]):
        c = ws.cell(row=r + 1 + i, column=3, value=cmd)
        c.font = f(10, color=BRAND)
    return ws


def build_commands(wb):
    ws = wb.create_sheet("Commands")
    for i, (t, w) in enumerate((("Say this in Cowork", 30), ("What happens", 96), ("Group", 12)), 1):
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
        ("What this is", "The system of record for an AI portfolio desk. Cowork appends rows to the log sheets and refreshes the Use Cases snapshot from Jira; the five dashboard tabs recompute from them against today's date. Nothing on a dashboard is typed by hand."),
        ("Dashboards", None),
        ("Home", "My desk: what needs me, which use cases need attention, what I did this week. Its tiles link to the other four."),
        ("Portfolio", "Health against the stage target, freshness, pipeline by stage, WSJF ranking against capacity, every open use case, value realized vs projected, and the portfolio mix."),
        ("Weekly Status", "RAG for the portfolio and its three elements, then the week as the three sittings produce it: Weekly Intake, Tactical Standup, Portfolio Council."),
        ("Gates", "The eight stages with gate grades, overdue and stale counts; the tier clock; and every gate exception with what the gate owner needs."),
        ("Use Case", "One use case end to end: pick a key at the top. Status, the eight-gate strip, the record, its Inventory and Done history, and the commands to run."),
        ("Which cells", "Blue headers are inputs. Grey headers and grey cells are formulas: never type over them. Add a row by filling the first empty row's blue columns. Never insert, delete or edit rows on a log sheet: append a correction instead."),
        ("Append-only", "Inventory, Done, Answers, Reviews and Changes are logs. A decision is closed by a new Resolved row pointing at it (Ref), a rumour by a Confirmed row. Use Cases is a snapshot of Jira, replaced in full on each refresh; OneDrive version history keeps every previous pull."),
        ("Privacy", "Nothing from 1:1s, performance or career conversations goes in this workbook. That lives in AI-OS/Private. No customer data anywhere: case or ticket IDs only."),
        ("Data sheets", None),
        ("Use Cases", "One row per use case, from Jira. Example: AI-003 | Fraud alert prioritization | Design | Fraud Operations | S. Okafor | Fraud Ops Director | 2026-07-31 | 2026-09-30 | 2026-09-29 | NPI | risk | insight | 1200 | 8 | 6.8 | Y | ready | Y | MRM model designation | 2026-08-22 | | | Y | fraud-alerts"),
        ("Inventory", "Example: INV-0019 | 2026-10-05 | Decision | fraud-alerts | Approve a second data engineer or slip Design a month | S. Okafor | Meeting | Confirmed | | AI-003"),
        ("Done", "Example: 2026-10-05 | Got MRM sign-off on the call summarization validation plan | call-summary | AI-001 | Email"),
        ("Value", "One row per quarter: projected and realized $K, and Y once the quarter is closed and measured."),
        ("Others", "Answers (Support Guide log), Reviews (Review Gate runs), Changes (file moves), Topics, People, Commands, Config."),
    ]
    if sample:
        rows.insert(1, ("SAMPLE", "This copy holds the site's sixteen illustrative use cases, dated around " + SAMPLE_AS_OF.isoformat() + ". Every age is measured from that date (Config › Sample data as-of). Use AI-OS.xlsx for real work."))
    for r, (a, b) in enumerate(rows, 1):
        ca = ws.cell(row=r, column=1, value=a)
        if b is None:
            ca.font = f(16 if r == 1 else 12, True, BRAND if r == 1 else INK)
            continue
        if a in DASHBOARDS:
            ca.value = link(a, a)
            ca.font = f(10, True, LINK, underline="single")
        else:
            ca.font = f(10, True)
        cb = ws.cell(row=r, column=2, value=b)
        cb.font = f(10)
        cb.alignment = Alignment(wrap_text=True, vertical="top")
        ca.alignment = Alignment(vertical="top")


# ---------------------------------------------------------------- assemble
def build(sample):
    wb = Workbook()
    wb.remove(wb.active)

    ws = data_sheet(wb, UC, SAMPLE_UC if sample else [], date_keys=("Opened", "Updated", "Target", "Decided", "ClosedOn"))
    for key, opts in (("Data", ["ready", "partial", "none"]), ("Metric", ["Y"]), ("Baseline", ["Y"]), ("Flagged", ["Y"]), ("Outcome", ["Declined", "Transferred"])):
        validate(ws, UC, key, opts)
    for key in ("Health", "Fresh", "Gate", "Clock", "Line", "Sev"):
        state_format(ws, "%s2:%s%d" % (UC.L(key), UC.L(key), UC.last))

    inv = [(i, d(o), t, tp, sm, fr, ch, cf, rf, jk) for i, o, t, tp, sm, fr, ch, cf, rf, jk in SAMPLE_INV] if sample else []
    ws = data_sheet(wb, INV, inv, date_keys=("Date",))
    validate(ws, INV, "Type", ["New", "Know", "Decision", "Conflict", "Confirmed", "Resolved"])
    validate(ws, INV, "Channel", ["Meeting", "Email", "Teams", "Call", "Document", "Jira", "Session"])
    validate(ws, INV, "Conf", ["Confirmed", "Unconfirmed"])
    state_format(ws, "%s2:%s%d" % (INV.L("Sev"), INV.L("Sev"), INV.last))

    done = [(d(o), a, t, j, so) for o, a, t, j, so in SAMPLE_DONE] if sample else []
    ws = data_sheet(wb, DONE, done, date_keys=("Date", "Week"))
    validate(ws, DONE, "Source", ["Session", "Email", "Teams", "Calendar"])
    data_sheet(wb, VAL, SAMPLE_VAL if sample else [], pct_keys=("Pct",))
    ans = [(i, d(o), qq, k, a, so, b, rf) for i, o, qq, k, a, so, b, rf in SAMPLE_ANS] if sample else []
    ws = data_sheet(wb, ANS, ans, date_keys=("Date",))
    validate(ws, ANS, "Kind", ["Answer", "Routed", "Reuse"])
    ws = data_sheet(wb, REV, [(d(x[0]),) + tuple(x[1:]) for x in SAMPLE_REV] if sample else [], date_keys=("Date",))
    validate(ws, REV, "Verdict", ["Ready", "Fix first"])
    data_sheet(wb, CHG, [(d(x[0]),) + tuple(x[1:]) for x in SAMPLE_CHG] if sample else [], date_keys=("Date",))
    data_sheet(wb, TOP, SAMPLE_TOP if sample else [])
    data_sheet(wb, PEO, [x[:6] + (d(x[6]),) for x in SAMPLE_PEO] if sample else [], date_keys=("Updated",))
    build_commands(wb)
    build_config(wb, sample)
    build_readme(wb, sample)

    dashes = [build_home(wb), build_portfolio(wb), build_weekly(wb), build_gates(wb), build_usecase(wb, sample)]
    for i, w in enumerate(dashes):
        wb.move_sheet(w, offset=-(wb.index(w) - i))
    wb.active = 0
    wb.calculation.fullCalcOnLoad = True  # Excel recomputes on open; no stale cached values
    for w in wb.worksheets:
        w.sheet_properties.tabColor = (BRAND if w.title in DASHBOARDS else
                                       "8A91A0" if w.title in ("Config", "Read Me", "Commands") else SERIES1)
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
    for smp in (False, True):
        print("wrote", os.path.relpath(build(smp), HERE))
    print("wrote", os.path.relpath(zip_onedrive(), HERE))
