---
name: reviewing-prs
description: Use when reviewing someone else's pull request, deciding Approve vs Request changes vs Comment, posting a review verdict, re-reviewing a PR after new commits, or batch-testing several PRs together - including when a build and manual test already passed.
---

# Reviewing PRs

## Overview
A manual test proves the PR does what it says. A review asks what else it breaks. **Never approve on a passing test or a quick "read it, no defect" pass** — every Approve needs an adversarial read of the diff that answers the axes below.

CI green only covers the scenarios its tests cover. "Tests pass" is not evidence for a case nobody tested.

## Process
1. **Pin the head.** Record the exact head sha, and CI status *at that sha* (run link, test counts). Re-review: diff only from the last reviewed head, and say whether each earlier finding is fixed.
2. **Gatekeeping first.** Choose **Comment (not an approval)** if: it conflicts with main, no CI has run on the head, it's stacked on an unmerged PR, or it bundles unrelated changes (ask for a split). Choose **Request changes** without going further if: CI fails or it doesn't compile, it doesn't actually fix the linked issue, or docs claim work that hasn't landed.
3. **Read the diff, then the callers.** For every changed function, list the state it writes (fields, caches, collections, counters, documents) and grep who else reads that state. The bug is usually in the reader you didn't open.
4. **Walk every axis.** For each one, write either a concrete failure scenario or the line that rules it out. "Looks fine" is not an answer.
5. **Test**, if you're building: the scenarios from step 4, not just the happy path in the PR description.
6. **Human eyes, when it applies.** If the PR claims visible behaviour (layout, rendering, UI, typing feel) or a blocking finding is only source-traced, give the user a ready-to-run build of the PR head (own `CARGO_TARGET_DIR` under `~/.cache`, never `/tmp`), exact repro steps and the expected vs suspected result. Ask them to look before you post. This checks claims; it doesn't replace step 4.
7. **Second reviewer for risky PRs.** If the diff touches revisions/authorship, protection, caches or revision counters, untrusted-input parsing, or batches a per-call path: run a second independent review (fresh subagent, this skill, no sight of the first) and merge the findings. Single runs miss different P2s.
8. **Give the verdict** using the severity rule and output contract.

## Axes
| Axis | Ask |
|---|---|
| Keyed state | Is anything cached or memoised by a counter, id or revision this changes, rewinds or reuses? Can a stale entry be hit later? |
| Guards and postchecks | Does a validator, protection check or invariant check list collections or fields by name? Does the PR mutate one that isn't listed? |
| Other actors | Set up: author A already has a revision/lock/ownership record on the target; author B now triggers the new code. Write the record you'd expect afterwards (who, what), then the record the code actually leaves. Different = finding. "A's record is preserved" is not the check — B's change must be recorded as B's. |
| Pre-existing state | What if the target already has the property, a duplicate entry, or a previous run's output? Run it twice. |
| Our check vs the real consumer | When we validate input a dependency later parses, do both agree on duplicates, first vs last wins, ordering and unknown values? Read the dependency's source at the locked version. |
| Loosened predicates | Did a condition get wider? Feed it ordinary input that isn't the target case (plain prose, a normal file, a selection replaced). |
| Sibling branches | Is a variant handled (left/centre/right, each enum arm, each format)? Check the arms the tests skip, and whether tests would pass if that arm were wrong. |
| Captured once, used many | List **every** variable assigned before a loop or split and read inside it. For each: does the loop body change what it was derived from (style, paragraph, selection, position)? |
| Replaced path | When N calls become one batched call, or a helper replaces a sequence: list what the old path recomputed per call (properties, styles, permissions, autoformat, events). Each one now computed once or skipped is a candidate finding. |
| Hostile input and cost | Lengths, counts, repeats from files or commands: capped? Panic paths? Quadratic work on input still under the caps? |

## Severity rule
- **P1 — blocks:** a safety, security or protection bypass; data loss; crash; doesn't compile.
- **P2 — blocks:** a wrong result a user would keep in a reachable scenario: wrong content or layout, wrong author or revision, lost edits, stale display, quadratic slowdown. Rare triggers and "off by default" don't downgrade it.
- **P3 — non-blocking:** cosmetic, unreachable, or a question.

Approve means zero P1/P2 findings.

## Output contract
```
Verdict: Approve | Request changes | Comment (not an approval)
Head: <sha> — CI at this head: <result, link, counts>
Findings: [P1|P2|P3] file:line — reproduced | source-traced — scenario (inputs → wrong result)
Axes: one line each — the scenario found, or why it can't happen
Read: files/functions read in full
Not checked: what you didn't read or run; no local execution unless you did it
```
A finding without a scenario is a question, not a finding. Merge conflicts are not part of the code verdict; say so.

## Red flags — stop and go back to step 4
- "Built and tested, works" → Approve
- "Read the diff, no defect found" with no Axes lines
- "I'll trust CI for the edge cases"
- "Low" or "cosmetic" for anything touching authorship, revisions, caches or security
- Approve with a finding that has a wrong-result scenario ("doesn't block, but…")
- "Correctly doesn't overwrite X", without checking what happens to the change that got skipped
- Reviewing ten PRs in one combined build with a one-line verdict each
- Checking our parser against itself, not against the library that consumes the data
