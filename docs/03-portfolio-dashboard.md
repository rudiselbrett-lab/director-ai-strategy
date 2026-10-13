# 3. Portfolio Dashboard

Where every use case stands.

**Live view:** https://rudiselbrett-lab.github.io/director-ai-strategy/#portfolio

> **Snapshot as of October 13, 2026. Illustrative data.** Sixteen invented use cases. The live page recomputes health, staleness, WSJF rank, capacity and suggested actions against the date it is opened, so these numbers will not match it on any other day. Nobody writes a status here. The board reads the record.

The live page filters by stage, health, and freshness (fresh, aging, stale), and can show closed use cases.

## Headline

| Measure | Value | Basis |
|---------|-------|-------|
| In flight | 14 | Active use cases |
| Est. annual value | $5.7M | Scored pipeline |
| On track | 11 | Beyond risk window |
| At risk | 2 | Inside risk window |
| Overdue | 1 | Past target date |
| Stale | 2 | No update in more than one cycle |

## Pipeline by stage

| Intake | Triage | Discovery | Design | Approval | Delivery | Scale | Value |
|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 2 | 2 | 3 | 1 | 3 | 1 | 1 | 1 |

## What starts next (WSJF)

8 of 24 delivery points committed across the portfolio, 16 open.

| Rank | Use case | WSJF | |
|:-:|---|:-:|---|
| 1 | Collections outreach timing (AI-005) | 7.5 | Fits |
| 2 | Fraud alert prioritization (AI-003) | 6.8 | Fits |
| | *Capacity line* | | |
| 3 | Branch staffing forecast (AI-006) | 5.1 | Below the line |
| 4 | Contact center call summarization (AI-001) | 4.2 | Below the line |
| 5 | Dispute intake summarizer (AI-014) | 3.4 | Below the line |

AI-005 and AI-003 fit the 16 open points. Next by rank (AI-006) needs 8. Deviating from rank is recorded with a rationale.

## All use cases

14 of 16 shown (2 closed), 9 with suggested actions. Sorted by health.

| ID | Use case | Function | Tier | Flags | Stage | Owner / sponsor | WSJF | Est. value | Complete | Target | Health | Last update |
|----|----------|----------|------|-------|-------|-----------------|:-:|:-:|:-:|---|---|---|
| AI-003 | Fraud alert prioritization | Fraud Operations | High · 70+ days | NPI | Design | S. Okafor / Fraud Ops Director | 6.8 | $1.2M | 100% | Oct 10 (3d overdue) | Overdue | 2d ago |
| AI-010 | Statement insight summaries | Digital Banking | Low · 21 days | | Intake | Intake team / sponsor not named | | | 33% | Oct 15 (in 2d) | At risk | 9d ago, aging |
| AI-004 | KYC document extraction | Onboarding | High · 70+ days | NPI, Reg report | Discovery | R. Patel / Deposits Operations | | | 57% | Oct 17 (in 4d) | At risk | 6d ago |
| AI-007 | Marketing copy assistant | Marketing | Medium · 45 days | | Triage | Intake team / Consumer Marketing | | | 60% | Oct 18 (in 5d) | On track | 2d ago |
| AI-009 | Wire fraud anomaly detection | Payments | High · 70+ days | NPI | Intake | Intake team / Payments Risk | | | 67% | Oct 19 (in 6d) | On track | 1d ago |
| AI-012 | Teller balancing assistant | Branch Network | Low · 21 days | | Triage | Intake team / Branch Operations | | | 60% | Oct 21 (in 8d) | On track | 8d ago, aging |
| AI-006 | Branch staffing forecast | Branch Network | Low · 21 days | | Approval | L. Nguyen / Retail Distribution | 5.1 | $400K | 100% | Oct 22 (in 9d) | On track | 12d ago |
| AI-002 | Complaint triage and routing | Customer Care | Medium · 45 days | NPI | Discovery | J. Whitfield / Head of Customer Care | | | 71% | Oct 25 (in 12d) | On track | 3d ago |
| AI-005 | Collections outreach timing | Collections | High · 70+ days | | Approval | D. Kim / Collections VP | 7.5 | $950K | 100% | Oct 29 (in 16d) | On track | 3d ago |
| AI-013 | ATM cash forecasting | Branch Network | Low · 21 days | | Discovery | R. Patel / Treasury Services | | | 71% | Oct 31 (in 18d) | On track | 4d ago |
| AI-008 | Chat deflection FAQ assistant | Digital Banking | High · 70+ days | No human review | Delivery | M. Alvarez / Digital Channels | 5.9 | $600K | 100% | Nov 3 (in 21d) | On track | 5d ago |
| AI-014 | Dispute intake summarizer | Customer Care | Medium · 45 days | NPI | Approval | D. Kim / Card Services | 3.4 | $300K | 100% | Nov 6 (in 24d) | On track | 6d ago |
| AI-001 | Contact center call summarization | Contact Center | Medium · 45 days | NPI | Scale | M. Alvarez / Contact Center Ops | 4.2 | $850K | 100% | Nov 27 (in 45d) | On track | 4d ago |
| AI-011 | Loan document pre-fill | Consumer Lending | High · 70+ days | NPI | Value | T. Brooks / Lending Operations | 8.9 | $1.4M | 100% | Dec 2 (in 50d) | On track | 10d ago |

WSJF and value are blank until a use case has been scored in Discovery.

### Blockers and tier windows

| ID | Waiting on | Tier window |
|----|-----------|-------------|
| AI-003 | MRM model designation | |
| AI-004 | Data access approval for KYC repository | Day 83 of a 70-day high-risk window |
| AI-010 | Named business sponsor | |
| AI-012 | Prep incomplete, deferred one cycle | |
| AI-006 | | Day 42 of a 21-day low-risk window |
| AI-014 | | Day 52 of a 45-day medium-risk window |

### Suggested actions

| ID | Severity | Action | Routine |
|----|----------|--------|---------|
| AI-003 | Red | Clear the blocker. 3 days past target on MRM model designation. | Portfolio Council |
| AI-010 | Red | Name a sponsor, or decline it. Due in 2 days with no one accountable for the value. | Weekly Intake |
| AI-010 | Amber | Complete the record. Only 33% of what intake asks for is on file, missing named sponsor and success metric. | Weekly Intake |
| AI-004 | Amber | Complete the record. Only 57% of what discovery asks for is on file, missing data readiness, value estimate and measured baseline. | Tactical Standup |
| AI-007 | Amber | Complete the record. Only 60% of what triage asks for is on file, missing success metric and data readiness. | Weekly Intake |
| AI-009 | Amber | Complete the record. Only 67% of what intake asks for is on file, missing success metric. | Weekly Intake |
| AI-012 | Amber | Settle it at the next triage. It is on its second return and owes an Approve or Decline. | Weekly Intake |
| AI-012 | Amber | Complete the record. Only 60% of what triage asks for is on file, missing success metric and data readiness. | Weekly Intake |
| AI-006 | Amber | Defer on the record, or free capacity. 3 points remain after higher-ranked work and this needs 8. | Portfolio Council |
| AI-014 | Amber | Defer on the record, or free capacity. 3 points remain after higher-ranked work and this needs 8. | Portfolio Council |
| AI-001 | Amber | Defer on the record, or free capacity. 3 points remain after higher-ranked work and this needs 8. | Portfolio Council |

## Trends and portfolio mix

### Value: realized vs. projected

| Quarter | Realized | Projected |
|---------|:-:|:-:|
| Q4 '25 | $1.6M | $1.8M |
| Q1 '26 | $2.4M | $2.6M |
| Q2 '26 | $3.9M | $4.2M |
| Q3 '26 | $3.6M | $5.7M |

$3.6M realized of $5.7M projected. Q3 '26 still in flight.

### Triage decisions per month

| Feb | Mar | Apr | May | Jun | Jul |
|:-:|:-:|:-:|:-:|:-:|:-:|
| 4 | 6 | 5 | 8 | 9 | 11 |

11 decisions in Jul, up from 4 in Feb. Throughput, not backlog.

### Cycle time: intake to decision

Median 41 days in Jul, down from 68 in Feb.

### Impact mix (in flight)

| Impact | Use cases |
|--------|:-:|
| Revenue / growth | 3 |
| Cost / productivity | 10 |
| Cycle time | 6 |
| Risk / control | 4 |
| Decision / insight | 6 |

Cost / productivity leads at 10 of 14 in flight; revenue / growth is thinnest at 3. Worth seeding growth-side use cases at intake. A use case can carry more than one impact type.

### Risk flags in flight

| Flag | Use cases |
|------|:-:|
| Customer / NPI data | 7 |
| Regulatory reporting | 1 |
| No human review | 1 |
| No flags | 6 |

8 of 14 in flight carry at least one flag; each routes to Risk or MRM before approval.

## How health and staleness are computed

### Health, against the expected completion date

| Health | Rule |
|--------|------|
| On track | Target date is beyond the stage's at-risk window. |
| At risk | Target date is inside the at-risk window (per-stage thresholds below). |
| Overdue | Target date has passed without an exit decision. |

### Staleness, based on last update, by stage cadence

A use case is aging past one review cycle without an update, and stale past two.

| Stage | At-risk window | Aging after | Stale after | Reviewed by |
|-------|:-:|:-:|:-:|---|
| Intake | 2 days | > 7 days | > 14 days | Weekly Intake, weekly |
| Triage | 2 days | > 7 days | > 14 days | Weekly Intake, weekly; Portfolio Council, weekly |
| Discovery | 5 days | > 10 days | > 20 days | Tactical Standup, weekly |
| Design | 7 days | > 14 days | > 28 days | Tactical Standup, weekly; Portfolio Council, weekly |
| Approval | 7 days | > 14 days | > 28 days | Portfolio Council, weekly |
| Delivery | 14 days | > 14 days | > 28 days | Tactical Standup, weekly |
| Scale | 7 days | > 14 days | > 28 days | Tactical Standup, weekly |
| Value | 14 days | > 45 days | > 90 days | Portfolio Council, weekly |
