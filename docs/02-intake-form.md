# 2. Intake Form

Fifteen minutes, not a specification.

**Live view:** https://rudiselbrett-lab.github.io/director-ai-strategy/#intake

> **Mock-up.** The form a requester fills in. On the live page, typing into a narrative box shows live answer coaching. Fifteen minutes is the only thing we ask of anyone; everything downstream is computed from it. Nothing submits anywhere.

Target: 15 minutes · Live answer coaching · Reviewed weekly · Jira is the system of record

## Section 1: General information

| Field | Notes |
|-------|-------|
| Use case name | e.g., Complaint triage and routing |
| Business owner / sponsor | Accountable for value after approval |
| Consumer Bank function | e.g., Customer Care |
| Submitted by | |
| Date | |
| What problem are we solving, and why now? | Narrative |
| What does the process look like today, and what changes? | Narrative |
| What metric defines success, and what is it today? | Narrative. Discovery will turn this into a measured baseline and a target. |

## Section 2: Business benefit

**Impact** (select all that apply)
- Revenue / growth
- Cost / productivity improvement
- Cycle time reduction
- Risk / control improvement
- Decision / insight improvement
- Other

**Value** (select one)

| Option | Meaning |
|--------|---------|
| High | Material or measurable $ impact |
| Medium | Efficiency or cost avoidance |
| Low | Limited quantifiable value |

**Scale** (select one)

| Option | Meaning |
|--------|---------|
| Enterprise | Multiple functions |
| Single function | |
| Team / niche | |

## Section 3: Feasibility

**Data readiness** (select one)

| Option | Meaning |
|--------|---------|
| Ready | Data exists and is accessible |
| Partially ready | Gaps or cleanup needed |
| Not ready | |

**Primary data sources** (optional, free text)

**Expected effort** (select one; covers process variation, integration, and technology support together)

| Option | Meaning |
|--------|---------|
| Low | Standardized process, existing tools, business-owned configuration |
| Medium | Some process variation, integration, or shared services support |
| High | Manual or inconsistent process, new tools, or dedicated engineering |

## Section 4: Risk flags

Routing only. Detailed risk review happens post-experimentation. Any flag routes to Risk or MRM before Approve; a prototype may still proceed in a controlled environment.

- Uses customer or nonpublic personal information (NPI)
- Output feeds a regulatory or financial report
- Runs without human review of the output
- None of the above

*Submit:* in production this creates a Jira issue in the AI Use Case Capability project.

## How this works

- **Fifteen minutes.** Longer means we're asking for detail we haven't earned yet.
- **Ask only what the requester can answer.** Refinement comes after experimentation.
- **Declining early is a good outcome.** A bad idea is cheapest before anyone builds it.

## Where this goes

- Every submission becomes a **Jira issue** and carries that ID forward.
- Work is staffed and reported from Jira. If it's there, it's in the portfolio.
- Declines get a Jira issue too. **Declines are portfolio data.**

## What happens next

1. **Triaged within 48 hours** at Monday's Weekly Intake. Routed, never queued. Accepted with a risk tier and a named PM, or rejected with the reason on the record.
2. **The tier sets your clock.** Low risk is twenty-one days to approval, medium forty-five, high seventy or more. It is assigned from what the idea touches, not chosen, and you are told it on day one.
3. **Discovery runs two to three weeks.** The PM validates the hypothesis, sizes the scope and assesses regulatory impact, then writes a one-page summary: a go or no-go, and a reading against the eight gates.
4. **The Council decides on Thursdays.** Approved to delivery with a six-month window, or archived as learning.

Submit as many ideas as you like. What gets funded is what fits capacity that quarter. A rejection at intake costs a week; one in production costs two quarters.

## Intake team use only

Completed before the routine to support the triage decision.

| Criterion | Rating |
|-----------|--------|
| Strategic alignment | High / Med / Low |
| Business value | High / Med / Low |
| Scale | High / Med / Low |
| Feasibility | High / Med / Low |
| Risk exposure | High / Med / Low |
| Confidence in stated value | High / Med / Low |

**Recommended next step:** Approve · Rapid Prototype · More Discovery · Partner with another team · Decline

**Rationale:** free text
