---
name: merging-approved-prs
description: Use when Martin asks to merge, land or sweep approved pull requests on storytold/wordcraft, find PRs ready to merge, clear the approved-PR backlog, or do a merge pass / merge sweep - including a dry run.
---

# Merging approved PRs (wordcraft, semi-automatic)

## Overview
The script finds PRs that are safe to land; you do a **light** read; **Martin picks**; you merge only his picks. Never merge without his selection in this session. Large PRs and features never land through this skill: they're reported, not merged.

## Process
1. **Scan** (read-only, ~3-5 min for ~1300 PRs), from the wordcraft clone:
   `python3 ~/.claude/skills/merging-approved-prs/scan.py --json <scratchpad>/scan.json`
   It keeps open, non-draft PRs into `main` with an APPROVED review from an OWNER/MEMBER/COLLABORATOR who isn't the author (`reviewDecision` may lag; the commit check is what counts), either **on the current head** or **carried**: approved on an older commit whose code change (docs excluded, line numbers and context ignored) is identical to the head's, so only a rebase, docs or trailers changed. It excludes and flags: more than 2500 counted lines or 50 files; feature labels; new `CommandSpec` ids; new crates; `.github/`, `packaging/`, `xtask/`, `Cargo.toml`, the i18n pin, binary assets; integration/batch PRs; conflicts (listing the files, and marked **docs only** when all are `ROADMAP.md`/`README.md`/`docs/*.md`); CI not green (SonarCloud Scan ignored); unresolved non-outdated review threads; outstanding change requests; anything by PierrunoYT.
   It also lists **small change since approval** (≤20 code lines differ from what was approved), **docs-only conflicts**, and **stale** approvals (bigger changes: full `reviewing-prs`).
2. **Light pass** on each candidate. Write one line per item:
   - `gh pr diff N`: does it do what the title says, and nothing unrelated? Any obvious bug, panic path (`unwrap`/`expect`/`[i]` on input), MS asset or copied wording?
   - Does a bug fix carry a test?
   - **Outdated open threads** (scan checks column): read each. Outdated means the code moved, not that it was fixed (#2905: four outdated CodeRabbit threads, two still real). Unaddressed → flagged.
   - **Carried approval:** skim the docs interdiff; the code is what was approved.
   - Drift: if the scan says main changed the same files since the PR's base, CI is stale. Mark it **"needs rebase/CI rerun"** rather than mergeable (with the queue on, the queue's own run covers it).
   - Anything doubtful moves to flagged. This is not a review: when in doubt, send it to `reviewing-prs`.
   - **Small change since approval:** one Sonnet subagent per PR re-reviews only the interdiff: `git diff` of approved commit vs head, against their merge bases (`range-diff --no-merges` misses edits made in merge commits; #4545's only code change was in one). Clean → candidate; escalate per `reviewing-prs` routing.
3. **Rebase candidates:** PRs whose *only* flag is "conflicts with main". The scan lists the clashing files (by hand: `git fetch origin pull/N/head:refs/scan/N && git merge-tree --write-tree --name-only origin/main refs/scan/N`).
   - **Docs only** (`ROADMAP.md`, `docs/*.md`): land-branch candidate (step 6). If Martin prefers the author rebase, comment: "Thanks, this is approved but now conflicts with `main`, only in docs: <files>. Could you rebase onto current `main`, keeping both sides of each conflict (your entry first in the progress log and revision tables)? Once CI is green we'll merge it."
   - **Changelog fragments are proposed** (each PR writes its own fragment instead of editing `ROADMAP.md`/`docs/gaps.md`/parity docs). If they land, docs clashes should mostly stop: update `DOCS_ONLY` in `scan.py` and this step to the fragment layout, and land-branch resolution becomes "convert the PR's doc edits into a fragment".
   - **Small code clash** (a few files, the clash is mechanical, e.g. a moved function or a neighbour's edit): low-hanging fruit; offer it, flag that the resolution is ours and needs a look.
   - **Anything else** (files split/moved since, i18n `.tsv` moved to craft-i18n, semantic clash): back to the author.
4. **Report** to Martin: candidates table (PR | title | author | approver (carried?) | size | light-pass verdict), rebase candidates with their clashing files, then flagged with reasons, then small-change re-review results, then the count of stale approvals. **Dry run stops here.**
5. **Pick:** AskUserQuestion, multiSelect, one option per mergeable candidate (batches of 4). "Merge them" in reply to a listed set counts as picking that set.
6. **Land each pick through the merge queue**, squash, one PR in flight per area of the code. Before the run, check the queue is on (`gh api repos/storytold/wordcraft/rulesets`, look for a `merge_queue` rule). **Queue off:** merge one at a time and wait for the `main` **push** run after each (`gh run list -R storytold/wordcraft -b main -w CI -e push -L 1`; without `-e push`, fork PRs whose branch is named `main` show up as `action_required`). A PR the queue ejects goes back to Martin with the failing check; don't requeue it blind.
   - **Clean PR:** `gh pr merge N -R storytold/wordcraft --squash --match-head-commit <head> --subject "<Area: what changed (#N)>" --body "<original Co-Authored-By trailers>"` (with the queue on, this adds it to the queue). Add `--delete-branch` only for same-repo branches (`cross_repo: false`).
   - **Needs a rebase** (we never push to contributors' forks; it's rejected anyway): a Sonnet agent, own worktree and `CARGO_TARGET_DIR` (`~/.cache/wordcraft-target-land-N`), max ~3 building at once:
     1. `git fetch origin && git switch -c land/N origin/main && git merge --squash refs/scan/N`.
     2. Docs clashes keep **both** sides (progress-log rows from main and from the PR; one status/revision line, bumped). Code clashes: resolve minimally, nothing else.
     3. Fix only what the light pass asked for (e.g. timing-ratio tests → work-step counts, as in #5643).
     4. `cargo xtask ci` green (set `CRAFT_I18N_DIR`). Commit: the PR's subject + `(#N)`, body notes what we changed, keeps the author's Co-Authored-By and adds `Co-Authored-By: <author> <id+login@users.noreply.github.com>`.
     5. One Opus review-agent pass on `git diff origin/main...land/N` versus `refs/scan/N`: did the resolution change anything beyond the clash and the asked-for fixes?
     6. Push `land/N` to origin, `gh pr create` titled like the original, body "Lands #N by @author (approved by @approver) rebased onto main. Closes #N." plus what we changed; then queue it with `gh pr merge <new> --squash --delete-branch`. If the queue's ruleset wants a fresh approval, ask Martin for the reviewer.
     7. Leave a one-line comment on #N linking the land PR (the only comment this skill posts unasked).
   - After each land, check `main` CI (`gh run list -R storytold/wordcraft -b main -w CI -e push -L 1`). Red → **stop the run** and tell Martin.

## Rules
- Approvals count on the head commit, or carried by an identical code change (the scan decides; don't eyeball it). Any other push after approval means the PR is not a candidate until re-reviewed.
- Never rebase-merge. Integration PRs are flagged and use a merge commit by hand.
- Don't widen the limits mid-run. "It's only slightly over 2500" stays flagged.
- Don't post comments or reviews unless Martin asks (except step 6.7's link).
- Never push straight to `main`; everything goes through a PR and the merge queue.
