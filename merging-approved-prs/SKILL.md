---
name: merging-approved-prs
description: Use when Martin asks to merge, land or sweep approved pull requests on storytold/wordcraft, find PRs ready to merge, clear the approved-PR backlog, or do a merge pass / merge sweep - including a dry run.
---

# Merging approved PRs (wordcraft, semi-automatic)

## Overview
The script finds PRs that are safe to land; you do a **light** read; **Martin picks**; you merge only his picks. Never merge without his selection in this session. Large PRs and features never land through this skill: they're reported, not merged.

## Process
1. **Scan** (read-only, ~3 min for ~1300 PRs), from the wordcraft clone:
   `python3 ~/.claude/skills/merging-approved-prs/scan.py --json <scratchpad>/scan.json`
   It keeps open, non-draft PRs into `main` with an APPROVED review **on the current head** from an OWNER/MEMBER/COLLABORATOR who isn't the author (`reviewDecision` is useless: `main` has no branch protection). It excludes and flags: more than 2500 counted lines or 50 files; feature labels; new `CommandSpec` ids; new crates; `.github/`, `packaging/`, `xtask/`, `Cargo.toml`, the i18n pin, binary assets; integration/batch PRs; conflicts; CI not green (SonarCloud Scan ignored); unresolved review threads; outstanding change requests; anything by PierrunoYT.
2. **Light pass** on each candidate. Write one line per item:
   - `gh pr diff N`: does it do what the title says, and nothing unrelated? Any obvious bug, panic path (`unwrap`/`expect`/`[i]` on input), MS asset or copied wording?
   - Does a bug fix carry a test?
   - Drift: if the scan says main changed the same files since the PR's base, CI is stale. Mark it **"needs rebase/CI rerun"** rather than mergeable.
   - Anything doubtful moves to flagged. This is not a review: when in doubt, send it to `reviewing-prs`.
3. **Report** to Martin: candidates table (PR | title | author | approver | size | light-pass verdict), then flagged with reasons, then the count of stale approvals. **Dry run stops here.**
4. **Pick:** AskUserQuestion, multiSelect, one option per mergeable candidate (batches of 4).
5. **Merge each pick**, squash, pinned to the head you checked:
   `gh pr merge N -R storytold/wordcraft --squash --match-head-commit <head> --subject "<Area: what changed (#N)>" --body "<original Co-Authored-By trailers>"`
   Add `--delete-branch` only for same-repo branches (`cross_repo: false`).
   After each merge, wait for `main` CI (`gh run list -b main -L 1`). If it goes red, **stop the run** and tell Martin.

## Rules
- Approvals only count on the head commit. A push after approval means the PR is not a candidate.
- Never rebase-merge. Integration PRs are flagged and use a merge commit by hand.
- Don't widen the limits mid-run. "It's only slightly over 2500" stays flagged.
- Don't post comments or reviews unless Martin asks.
