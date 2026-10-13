# 5. Jira

The system of record.

**Live view:** https://rudiselbrett-lab.github.io/director-ai-strategy/#jira

> **Mock-up. Snapshot as of October 13, 2026.** The same portfolio in Jira, one issue per use case. It is the one place the work lives, and every other tab is a view of it. A picture, not a live connection; every issue is invented.

Project: AI Use Case Capability (AI) · Issue type: Capability · Declines stay as issues

## The backlog

The same sixteen use cases as Jira issues, with the workflow status and the flag riding on top. The board, the gates and the weekly report all read this and nothing else.

| Key | Summary | Flag | Status | Assignee | Points | WSJF | Est. value | Updated |
|-----|---------|:-:|--------|----------|:-:|:-:|:-:|---|
| AI-001 | Contact center call summarization | | In Scale | M. Alvarez | 8 | 4.2 | $850K | Oct 9 |
| AI-002 | Complaint triage and routing | | In Discovery | J. Whitfield | 5 | | | Oct 10 |
| AI-003 | Fraud alert prioritization | ⚑ | In Design | S. Okafor | 8 | 6.8 | $1.2M | Oct 11 |
| AI-004 | KYC document extraction | ⚑ | In Discovery | R. Patel | 13 | | | Oct 7 |
| AI-005 | Collections outreach timing | | Awaiting Approval | D. Kim | 5 | 7.5 | $950K | Oct 10 |
| AI-006 | Branch staffing forecast | | Awaiting Approval | L. Nguyen | 8 | 5.1 | $400K | Oct 1 |
| AI-007 | Marketing copy assistant | | Triage | Intake team | 2 | | | Oct 11 |
| AI-008 | Chat deflection FAQ assistant | | In Progress | M. Alvarez | 5 | 5.9 | $600K | Oct 8 |
| AI-009 | Wire fraud anomaly detection | | Backlog | Intake team | 8 | | | Oct 12 |
| AI-010 | Statement insight summaries | ⚑ | Backlog | Intake team | 3 | | | Oct 4 |
| AI-011 | Loan document pre-fill | | In Benefits Review | T. Brooks | 3 | 8.9 | $1.4M | Oct 3 |
| AI-012 | Teller balancing assistant | ⚑ | Triage | Intake team | 3 | | | Oct 5 |
| AI-013 | ATM cash forecasting | | In Discovery | R. Patel | 5 | | | Oct 9 |
| AI-014 | Dispute intake summarizer | | Awaiting Approval | D. Kim | 8 | 3.4 | $300K | Oct 7 |
| AI-015 | RM email auto-drafting | | Done | Intake team | 2 | | | Sep 25 |
| AI-016 | HR policy chatbot | | Done | Intake team | 3 | | | Sep 16 |

## One issue: AI-003 Fraud alert prioritization

The fields that do the work sit on the issue: the risk tier, the date it opened, the readiness evidence. The comment stream is where the week's narrative comes from, so the weekly report writes itself from what the team already logs rather than from a second dashboard.

### Description

**What problem are we solving, and why now?**
Fraud analysts work one queue ordered by alert age, so a high-risk alert can sit behind low-risk ones for most of a shift. Alert volume is up 34% year on year and the team has not grown. Now, because the Q3 loss run rate is running above plan and adding headcount is not on the table.

**What does the process look like today, and what changes?**
Today an analyst opens the oldest unworked alert, checks the transaction and the customer history across two systems, and dispositions it. That review does not change. What changes is the order the queue is worked in: alerts are ranked by predicted risk so the highest exposure is seen first. Nothing is auto-closed and every disposition stays with a person.

**What metric defines success, and what is it today?**
Fraud loss per thousand alerts worked. Today that is $4,100, averaged across the last two quarters. Target is $3,200 within two quarters of launch, with no increase in the false positive rate.

### Readiness

Graded Oct 13 · Portfolio Council

| Gate | Grade | Note |
|------|:-:|------|
| Intake | Green | |
| Triage | Green | |
| Discovery | Green | |
| Design | **Red** | Awaiting MRM model designation |
| Approval | N/A | Not due until Approval |
| Delivery | N/A | Not due until Delivery |
| Scale | N/A | Not due until Scale |
| Value | N/A | Not due until Value |

### Activity

> **S. Okafor**, 2 days ago
> Still held at the design gate awaiting MRM model designation. Nothing on our side is blocking; Model Risk is in Tuesday's standup and it is on Thursday's Council agenda.

> **R. Patel**, 9 days ago
> Discovery package accepted. Value estimate $1.2M, size 8, WSJF 6.8. Moving to Governance.

### Details

| Field | Value |
|-------|-------|
| Status | In Design |
| Assignee | S. Okafor |
| Impediment | ⚑ Flagged: MRM model designation |
| Risk Tier | High · 70+ days to approval |
| Opened | Aug 12 |
| Business Sponsor | Fraud Ops Director |
| Consumer Bank function | Fraud Operations |
| Story Points | 8 |
| Estimated Annual Value | $1.2M |
| WSJF | 6.8 |
| Impact | Risk / control, Decision / insight |
| Data Readiness | Ready |
| Success Metric | Defined |
| Baseline Captured | Yes |
| Labels | NPI |
| Stage Target Date | Oct 10 |
| Updated | Oct 11 |
