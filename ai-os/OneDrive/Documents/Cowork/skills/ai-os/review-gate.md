# review this

A pre-flight check against one editorial standard. Report what passes, what
fails and the specific fix. **Never rewrite the work.** Not even "here's a
cleaned-up version". If I want a rewrite, I'll ask for one separately.

## The eight checks

| # | Check | Passes when |
|---|---|---|
| 1 | **MECE** (primary) | Sections don't overlap and together cover the question. No item could sit in two sections; nothing obviously missing. |
| 2 | **Answer first** | The recommendation or conclusion is in the first three lines. |
| 3 | **Sourced** | Every number and factual claim has a source, a date or an owner. |
| 4 | **Numbers reconcile** | Totals add up; the same metric has the same value everywhere; units are stated. |
| 5 | **Explicit asks** | Every ask names who decides, what the options are, and by when. |
| 6 | **Risk and control** | Model risk tier, customer impact, regulatory or compliance exposure, and third-party risk are addressed where relevant, or explicitly marked not applicable. |
| 7 | **Clean data** | No customer data, no confidential personnel content, nothing from Private. |
| 8 | **Fit for the forum** | Length and depth fit the audience (Council: one page plus appendix; Standup: bullets). |

## Output

```
Verdict: Fix first (6/8)

FAIL  1 MECE: sections 2 and 4 both cover capacity. Fix: merge 4 into 2, or make 4 about funding only.
FAIL  5 Explicit asks: "We need support from Risk" has no decider or date. Fix: "Need R. Chen to approve validation scope by Oct 15."
PASS  2, 3, 4, 6, 7, 8
```

Order failures by how much they'd hurt the document in front of its
audience. Each fix is specific enough to act on without asking.

Then append a row to the Reviews sheet: Date, Artifact, Author, Passed,
Failed, Verdict (`Ready` if 8/8 or only check 8 fails; otherwise `Fix
first`), Top fix.
