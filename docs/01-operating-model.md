# 1. Operating Model

Director of AI Strategy operating model. One record. Eight stages. Three routines. Disciplined triage.

**Live view:** https://rudiselbrett-lab.github.io/director-ai-strategy/#thinking

> **Directional only.** Ideas to react to, not a model to adopt. A real operating model gets built with the people who have to run it (Risk, Finance, Technology, the product owners), and it would change in that conversation. Not something Ally operates today. Every other tab on the site is generated from what is defined here.

## The Principle

**Smooth is fast and fast is smooth. Clarity is what makes both possible.**

This model builds clarity at every gate so everyone can move together. Intake clarifies whether an idea is worth exploring. Triage clarifies what success looks like. Discovery clarifies whether the problem is real. Design clarifies whether we can build it and govern it well. By Approval, Risk, PM, and Finance are all seeing the same picture.

That shared clarity is what keeps things moving forward. When things change during Discovery or Design (and they will), everyone sees it at the same time. Risk owns the Design gate, so if governance requirements shift, we address it together before build starts, not after. If conditions change, we escalate or re-tier as a portfolio, not rework in silos. The 70 days for high-risk work reflects real governance rigor, and everyone knows that upfront.

## Eight Stages. One Record.

Three things have to be true to leave each stage.

| # | Stage | Exit criteria |
|---|-------|---------------|
| 1 | **Intake** | Idea documented · Risk tier assigned · PM owner named |
| 2 | **Triage** | Business case drafted · Governance model type ID'd · Baseline & success metrics set |
| 3 | **Discovery** | Hypothesis validated · Regulatory impact assessed · Model risk controls defined |
| 4 | **Design** | Tech architecture specified · Governance framework mapped · Audit trail & monitoring designed |
| 5 | **Approval** | Business case finalized · PM & Risk both sign off · Capacity locked in |
| 6 | **Delivery** | Build & testing complete · Audit trail live & validated · Rollout plan operationalized |
| 7 | **Scale** | Model monitoring live · Risk oversight ready · Third-party review scheduled |
| 8 | **Value** | Baseline performance confirmed · Actual performance measured · Variance documented |

Each exit criterion carries one of three statuses: **Complete**, **In Progress**, or **Blocked**.

## Intake Gate: What Gets In

| Criterion | What it means |
|-----------|---------------|
| **Clear Problem** | Specific customer or operational pain. Measurable. Not "we want to use AI." Someone owns it. |
| **AI as the Answer** | Why AI? Could this be solved with process, rules, or simpler tools? If yes, that's the path. AI only when it's clearly the right lever. |
| **Measurable Outcome** | How will we know if this works? Revenue, cost, risk reduction. Must be quantifiable. Not aspirational. |
| **Owner & Timeline** | Accountable PM identified. Have they got runway? Not interest. Ownership. |

## Triage Gate: Define Value

| Element | What it means |
|---------|---------------|
| **Hypothesis** | What we expect to happen. Stated at Triage. Finance and Risk must agree it's testable. |
| **Baseline** | How we measure today. Set by Finance. Every use case measured against it at Value stage. |
| **Success Criteria** | Explicit numbers, not hopes. Adoption thresholds, revenue lift, risk reduction. Stated upfront. |
| **Stop Condition** | What triggers a pivot or restart. Stated at Triage. Prevents rework chasing a dead direction. |

## Cycle Time by Risk Tier

Intake to Approval.

| Tier | Target | Profile |
|------|--------|---------|
| **Low risk** | 21 days | Internal tools, employee-only access, minimal regulatory exposure. |
| **Medium risk** | 45 days | Revenue impact, internal process, regulatory review required. |
| **High risk** | 70+ days | Customer-facing, credit decisions, compliance-critical, regulatory gated. |

The tier is derived from what the use case touches (risk flags, function, impact), not chosen by the requester.

## Three Routines. Weekly Rhythm.

### Weekly Intake
*Every Monday, 15 min*

- **Attendees:** Portfolio Lead (Director), PM Lead
- **Decision:** Portfolio Lead decides: accept, reject, or defer.
- **Outputs:** Risk tier assigned. PM owner named. Triage backlog updated.
- **SLA:** PM owner identified within 48 hours or escalate to skip-level.

### Tactical Standup
*Every Tuesday, 30 min*

- **Attendees:** All active PMs, Tech Lead, Model Risk & Monitoring rep
- **Format:** Each PM / work stream lead reports status, blocker, ask. 2 to 3 min each.
- **Outputs:** Blockers flagged for escalation. Work stream health visible. Portfolio Council agenda fed.
- **Escalation SLA:** Red items surface by Tuesday. Director decides by Wednesday EOD or they escalate.

### Portfolio Council
*Run by the Director, every Thursday, 75 min (tight when active)*

- **Attendees:** Director, PM Lead, Risk Lead, Finance Rep, Tech Lead

| Segment | Time | Agenda |
|---------|------|--------|
| What's New | 15 min | Intake backlog triage. Risk tier review. |
| What We Know | 25 min | Design reviews. Tech feasibility. Governance gaps. Blockers from Tactical. |
| What We Decide | 35 min | Approve to Delivery. Capacity trade-offs. Kill or advance red items. Escalation paths. |

### Escalation

Any red item escalates to Portfolio Council. Director decides: unblock, re-tier, or accept the delay. Blocker owner must surface options within the decision window.

## Gate Ownership and Criteria

| Gate | Owner | Decision criteria |
|------|-------|-------------------|
| Intake | Portfolio Lead | Clear problem. AI is the answer. Measurable outcome. PM is named. |
| Triage | PM Owner | Business case solid. Hypothesis is testable. Baseline is set. Stop condition is real. |
| Discovery | PM Owner | Hypothesis validated with data. Regulatory impact clear. Risk controls outlined. |
| Design | Model Risk & Monitoring | Architecture is sound. Governance framework applied. Monitoring is designable. |
| Approval | Director / Portfolio Council | Business case holds. PM ready. Risk ready. Capacity allocated. Director breaks ties if PM and Risk disagree. |
| Delivery | Tech Lead | Build complete. Audit trail works. Rollout plan is executable. |
| Scale | Model Risk & Monitoring | Monitoring is live. Controls are testable. Third-party review is scheduled. |
| Value | Governance & Audit | Performance vs. baseline measured. Controls held. Variance documented. |

## Measures. How We Know It's Working.

| Measure | Value | Basis |
|---------|-------|-------|
| Days intake to approval | 21 to 70 | By risk tier, predictable |
| Late-stage blockers | 0 | Risk in, then blockers surface early |
| Value realization | 92% | vs. hypothesis at Approval, baseline set at Triage |
| Live capabilities | 3 | With monitoring in place |
| PMs using board | 12 of 14 | Active PMs |

Values are from the illustrative sample portfolio as rendered on 2026-10-13. The live page recomputes them against the date it is opened.

## What This Means Operationally

- **Risk is not a launch gate.** It owns the Design gate. Governance happens before you build, not after. Delivery doesn't surface control gaps.
- **One record. One status. No re-reviews.** A use case moves through eight stages once. Risk doesn't re-evaluate at launch what it decided at Design. Finance doesn't re-baseline at Value what it set at Triage.
- **Blockers are portfolio problems, not PM problems.** Escalation isn't a PM asking permission. It's a Director unblocking someone or re-tiering work. Happens within 24 hours.
- **Speed comes from predictability.** You know your timeline upfront. 21 days for low risk means 21 days. 70+ for high risk means full governance. No surprises.
