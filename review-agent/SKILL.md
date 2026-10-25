---
name: review-agent
description: Use when implementation subagents (e.g. Sonnet fix agents) have finished work on local branches or worktrees and you must decide whether each branch is ready to push or open a PR - including when the agent reports "tests pass, CI green, committed".
---

# Reviewing agent branches

## Overview
A local pre-push review of work an agent did for you, held to the **reviewing-prs** bar. **REQUIRED:** read reviewing-prs and use its Axes table and Severity rule unchanged; this skill only replaces its PR-specific steps.

The agent's report is a claim, not evidence. "CI passes" and "root cause found" are verified here or listed as not checked.

## Process (per branch)
1. **Pin it.** `git fetch origin`; record head sha, merge-base with `origin/main`, commit list. Check the issue for linked PRs (`gh pr list --state all --search <issue#>`): merged, or open/claimed by someone else → stop, verdict Escalate. Our own open PR → review only commits after the PR head (none → nothing to push; say so).
2. **Review blind.** Dispatch one fresh reviewer subagent per branch with: the issue (`gh issue view <n> --comments`), the worktree path, the base sha, this skill. **Not** the implementer's report — it anchors the review. Reviewers read only; any build uses the worktree's own `CARGO_TARGET_DIR` under `~/.cache` and the machine's build-concurrency cap.
3. **Gatekeeping.** Send back without walking axes if: the diff doesn't fix what the issue asks; unrelated changes bundled; tests deleted, `#[ignore]`d or assertions loosened; panic paths (`unwrap`/`expect`/`panic!`/indexing on input) added in non-test code; docs claim behaviour that didn't land.
4. **Prove the test guards the fix.** Revert only the non-test change (`git stash`/checkout the base version of the fixed files), run the new test: it must fail, then pass with the fix restored. Can't build → "Not checked: regression test not shown to fail without the fix".
5. **Root cause vs symptom.** State the root cause in one line from the code, not from the report. If the fix sits downstream of it (clamp, special case, retry), name the other callers of the root-cause path the fix doesn't cover.
6. **Walk every reviewing-prs axis.** One line each: a concrete scenario (inputs → wrong result) or the line of code that rules it out.
7. **Verdict** (below). Send-back findings go to the **same** implementer agent (SendMessage keeps its context), then re-review only the new commits.
8. **Before push** (Ready only): run the project's pre-push gates (e.g. local CodeRabbit), then push.

## Verdicts
- **Ready to push** — zero P1/P2, regression test shown to fail without the fix (or the gap listed), CI rerun or listed as not checked.
- **Send back** — any P1/P2, or a gatekeeping failure. Findings carry scenarios.
- **Escalate** — the decision is the owner's (scope, product behaviour, licensing, already merged, issue ambiguous).

## Output contract (one block per branch)
```
Branch: <name> @ <sha> (base <sha>) — Issue #<n>
Verdict: Ready to push | Send back | Escalate
Root cause: <one line, from code>
Regression test: fails without fix: yes | no | not run
Findings: [P1|P2|P3] file:line — reproduced | source-traced — scenario (inputs → wrong result)
Axes: one line each — scenario found, or why it can't happen
Read: files/functions read in full
Not checked: what wasn't run or read
```
Batch: end with a table `branch | verdict | P1/P2 count | next action`.

## Red flags — go back to step 4
- Verdict copied from the implementer's "all green"
- Reviewer was shown the implementer's summary
- "Test added" without it failing on the unfixed code
- Nits list with no Axes lines
- One combined review for several branches
