# 4. Weekly Status

Week of October 12, 2026.

**Live view:** https://rudiselbrett-lab.github.io/director-ai-strategy/#status

> **Snapshot as of October 13, 2026. Illustrative data.** The standing weekly report: the output of the three sittings, in the order they happen. Each routine reports what its own definition says it produces, computed from the record all three read. The live page keeps prior weeks as issued (September 28, 21 and 14) and recomputes the current week on every load.

Computed from the portfolio · One block per sitting · Issued weekly

## RAG

| Element | Rating | Reading |
|---------|:-:|---------|
| **Overall** | **Red** | Risk and controls is the constraint. Overall takes the worst of the three. |
| Flow | Amber | 1 of 14 are past their stage target, the longest by 3 days, and 2 have gone more than a review cycle without an update. |
| Value | Green | 92% of projected value realized across the last 3 closed quarters. Q3 '26 is in flight at $3.6M of $5.7M. |
| Risk and controls | Red | 8 of 14 in flight carry a risk flag. 1 held at the design gate, the longest 3 days past target. 3 past the window their tiers promised. |

## Weekly Intake

*Every Monday, 15 min. Next sitting Mon, Oct 19.*

**What came in**
- AI-009 · Wire fraud anomaly detection. From Payments Risk, day 5 of a 70-day window.
- AI-010 · Statement insight summaries. No named sponsor, day 21 of a 21-day window.

**Accepted, rejected or deferred**
- AI-007 · Marketing copy assistant. Accepted, in triage against a 45-day window.
- AI-012 · Teller balancing assistant. Prep incomplete, deferred one cycle.

**Tier and owner assigned**

| Use case | Tier | Owner | Sponsor |
|----------|------|-------|---------|
| AI-009 · Wire fraud anomaly detection | High, 70+ days | Intake team | Payments Risk |
| AI-010 · Statement insight summaries | Low, 21 days | Intake team | None named |
| AI-007 · Marketing copy assistant | Medium, 45 days | Intake team | Consumer Marketing |
| AI-012 · Teller balancing assistant | Low, 21 days | Intake team | Branch Operations |

## Tactical Standup

*Every Tuesday, 30 min. Next sitting Tue, Oct 13.*

**Work stream health**
- Discovery: 3 use cases, 1 amber.
- Design: 1 use case, 1 red.
- Delivery: 1 use case, inside its window.
- Scale: 1 use case, inside its window.
- Worst: AI-003 · Fraud alert prioritization, 3 days past target.

**Blockers flagged**
- AI-003 · Fraud alert prioritization. MRM model designation. Red, 3 days past target.
- AI-004 · KYC document extraction. Data access approval for KYC repository. Inside its window so far.

**Fed to the Council**
- AI-003 · Fraud alert prioritization. 3 days past target and blocked.
- AI-004 · KYC document extraction. Day 83 of a 70-day high-risk window.

## Portfolio Council

*Run by the Director, every Thursday, 75 min (tight when active). Next sitting Thu, Oct 15.*

**What's new**
- AI-003 · Fraud alert prioritization. Moved 2 days ago, now at Design.
- AI-005 · Collections outreach timing. Moved 3 days ago, now at Approval.
- AI-007 · Marketing copy assistant. Moved 2 days ago, now at Triage.
- AI-014 · Dispute intake summarizer. Moved 6 days ago, now at Approval.

**What we need to know**
- **Value.** 92% of projected value realized across the last 3 closed quarters, with Q3 '26 in flight at $3.6M of $5.7M.
- **Past the tier window.** 3 use cases are past the intake-to-approval window their tier promised: AI-006 at day 42 of 21, AI-004 at day 83 of 70, AI-014 at day 52 of 45. Either the tier was wrong or the blocker is, and both are the Council's call.
- **Approvals we do not control.** 2 initiatives are held on a decision owned elsewhere: AI-003 (MRM model designation) and AI-004 (data access approval for KYC repository). Nothing moves until those return.
- **No room to start.** 3 points remain and the next item by rank needs 8, so 3 scored use cases wait on something finishing or stopping.

**What needs a decision or discussion**

| Use case | Ask |
|----------|-----|
| AI-005 · Collections outreach timing | Awaiting the funding call at WSJF 7.5, $950K a year. |
| AI-006 · Branch staffing forecast | Awaiting the funding call at WSJF 5.1, $400K a year. Defer on the record, or free capacity: 3 points remain after higher-ranked work and this needs 8. |
| AI-014 · Dispute intake summarizer | Awaiting the funding call at WSJF 3.4, $300K a year. Defer on the record, or free capacity: 3 points remain after higher-ranked work and this needs 8. |
| AI-003 · Fraud alert prioritization | Clear the blocker, 3 days past target on MRM model designation. |
| AI-001 · Contact center call summarization | Defer on the record, or free capacity: 3 points remain after higher-ranked work and this needs 8. |

---

Every line above is computed from the portfolio as it stands. In production these read as the week's Jira comments on each issue, so the report writes itself from the work rather than being assembled by hand.
