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
   It keeps open, non-draft PRs into `main` with an APPROVED review **on the current head** from an OWNER/MEMBER/COLLABORATOR who isn't the author (`reviewDecision` may lag; the head-commit check is what counts). It excludes and flags: more than 2500 counted lines or 50 files; feature labels; new `CommandSpec` ids; new crates; `.github/`, `packaging/`, `xtask/`, `Cargo.toml`, the i18n pin, binary assets; integration/batch PRs; conflicts; CI not green (SonarCloud Scan ignored); unresolved review threads; outstanding change requests; anything by PierrunoYT.
2. **Light pass** on each candidate. Write one line per item:
   - `gh pr diff N`: does it do what the title says, and nothing unrelated? Any obvious bug, panic path (`unwrap`/`expect`/`[i]` on input), MS asset or copied wording?
   - Does a bug fix carry a test?
   - Drift: if the scan says main changed the same files since the PR's base, CI is stale. Mark it **"needs rebase/CI rerun"** rather than mergeable.
   - Anything doubtful moves to flagged. This is not a review: when in doubt, send it to `reviewing-prs`.
3. **Rebase candidates:** PRs whose *only* flag is "conflicts with main". Find the clashing files:
   `git fetch origin pull/N/head:refs/scan/N && git merge-tree --write-tree --name-only origin/main refs/scan/N`
   - **Docs only** (`ROADMAP.md`, `docs/*.md`): land-branch candidate (step 6).
   - **Small code clash** (a few files, the clash is mechanical, e.g. a moved function or a neighbour's edit): low-hanging fruit; offer it, flag that the resolution is ours and needs a look.
   - **Anything else** (files split/moved since, i18n `.tsv` moved to craft-i18n, semantic clash): back to the author.
4. **Report** to Martin: candidates table (PR | title | author | approver | size | light-pass verdict), rebase candidates with their clashing files, then flagged with reasons, then the count of stale approvals. **Dry run stops here.**
5. **Pick:** AskUserQuestion, multiSelect, one option per mergeable candidate (batches of 4).
6. **Land each pick through the merge queue**, squash, one PR in flight per area of the code.
   - **Clean PR:** `gh pr merge N -R storytold/wordcraft --squash --match-head-commit <head> --subject "<Area: what changed (#N)>" --body "<original Co-Authored-By trailers>"` (with the queue on, this adds it to the queue). Add `--delete-branch` only for same-repo branches (`cross_repo: false`).
   - **Needs a rebase** (we never push to contributors' forks; it's rejected anyway): a Sonnet agent, own worktree and `CARGO_TARGET_DIR` (`~/.cache/wordcraft-target-land-N`), max ~3 building at once:
     1. `git fetch origin && git switch -c land/N origin/main && git merge --squash refs/scan/N`.
     2. Docs clashes keep **both** sides (progress-log rows from main and from the PR; one status/revision line, bumped). Code clashes: resolve minimally, nothing else.
     3. Fix only what the light pass asked for (e.g. timing-ratio tests → work-step counts, as in #5643).
     4. `cargo xtask ci` green (set `CRAFT_I18N_DIR`). Commit: the PR's subject + `(#N)`, body notes what we changed, keeps the author's Co-Authored-By and adds `Co-Authored-By: <author> <id+login@users.noreply.github.com>`.
     5. One Opus review-agent pass on `git diff origin/main...land/N` versus `refs/scan/N`: did the resolution change anything beyond the clash and the asked-for fixes?
     6. Push `land/N` to origin, `gh pr create` titled like the original, body "Lands #N by @author (approved by @approver) rebased onto main. Closes #N." plus what we changed; then queue it with `gh pr merge <new> --squash --delete-branch`. If the queue's ruleset wants a fresh approval, ask Martin for the reviewer.
     7. Leave a one-line comment on #N linking the land PR (the only comment this skill posts unasked).
   - After each land, check `main` CI (`gh run list -b main -L 1`). Red → **stop the run** and tell Martin.

## Rules
- Approvals only count on the head commit. A push after approval means the PR is not a candidate.
- Never rebase-merge. Integration PRs are flagged and use a merge commit by hand.
- Don't widen the limits mid-run. "It's only slightly over 2500" stays flagged.
- Don't post comments or reviews unless Martin asks (except step 6.7's link).
- Never push straight to `main`; everything goes through a PR and the merge queue.
