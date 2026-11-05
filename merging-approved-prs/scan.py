#!/usr/bin/env python3
"""Scan storytold/wordcraft open PRs for ones safe to merge after a light pass.

Usage: python3 scan.py [--repo storytold/wordcraft] [--git-dir PATH] [--json OUT]
Prints a markdown report: MERGE CANDIDATES (need the light read + Martin's pick) and
FLAGGED (excluded, with reasons). Read-only: never merges, comments or pushes.
"""
import argparse, json, re, subprocess, sys
from collections import Counter

MAX_LINES, MAX_FILES = 2500, 50
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
BLOCKED_AUTHORS = {"pierrunoyt"}
FEATURE_LABELS = {"feature", "enhancement", "feat"}
# Not counted towards size (generated / data).
SIZE_EXEMPT = re.compile(r"(^|/)Cargo\.lock$|^contributors/contributors\.json$|(^|/)locales?/|\.ftl$|\.po$")
# Touching these always needs a full human look.
RISKY = [
    (re.compile(r"^\.github/"), "CI/workflow"),
    (re.compile(r"^packaging/"), "packaging/signing"),
    (re.compile(r"^xtask/"), "quality gates (xtask)"),
    (re.compile(r"(^|/)Cargo\.toml$"), "Cargo.toml (deps/crates)"),
    (re.compile(r"^craft-i18n\.rev$"), "i18n pin"),
    (re.compile(r"^(rust-toolchain|deny|clippy)\.toml$|^\.cargo/"), "toolchain/lint config"),
]
BINARY = re.compile(r"\.(png|jpe?g|gif|webp|ico|icns|bmp|tiff?|svg|ttf|otf|woff2?|wav|mp3|ogg|flac|pdf|docx?|odt|rtf|zip|bin)$", re.I)
NEW_CMD = re.compile(r'^\+.*CommandSpec::new\("([\w.]+)"')
PANICKY = re.compile(r"\.unwrap\(\)|\.expect\(|\bpanic!|\bunreachable!|\btodo!|\bunimplemented!|\bunsafe\b")
IGNORED_CHECKS = re.compile(r"^SonarCloud Scan$|^sonarcloud / SonarCloud Scan$")

LIST_Q = """query($owner:String!,$name:String!,$after:String){repository(owner:$owner,name:$name){
 pullRequests(states:OPEN,first:50,after:$after,orderBy:{field:CREATED_AT,direction:DESC}){
  pageInfo{hasNextPage endCursor}
  nodes{number title isDraft headRefOid baseRefName author{login} authorAssociation
   reviews(last:100){nodes{state authorAssociation author{login} commit{oid}}}}}}}"""

DETAIL_Q = """query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){pullRequest(number:$n){
 number title body url additions deletions changedFiles mergeable isCrossRepository headRefName headRefOid
 labels(first:20){nodes{name}}
 files(first:100){nodes{path additions deletions changeType}}
 reviewThreads(first:100){nodes{isResolved isOutdated comments(first:1){nodes{author{login}}}}}
 commits_last:commits(last:1){nodes{commit{statusCheckRollup{contexts(first:100){nodes{
  __typename ...on CheckRun{name conclusion status} ...on StatusContext{context state}}}}}}}}}}"""


def gh_graphql(query, **variables):
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        if v is not None:
            args += ["-F" if isinstance(v, int) else "-f", f"{k}={v}"]
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"gh api graphql failed: {out.stderr.strip()}")
    return json.loads(out.stdout)["data"]["repository"]


def approval_state(pr):
    """Return (approvers_on_head, stale_approvers, change_requesters)."""
    author = (pr["author"] or {}).get("login", "")
    on_head, stale, blockers = [], [], []
    # Each reviewer's last verdict, as GitHub counts it: a plain COMMENTED review doesn't replace
    # an approval or change request (latestReviews did, so a follow-up comment hid an approval).
    last = {}
    for r in pr["reviews"]["nodes"]:
        login = (r["author"] or {}).get("login", "ghost")
        if r["state"] in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            last[login] = r
    for login, r in last.items():
        if login == author:
            continue
        if r["state"] == "CHANGES_REQUESTED":
            blockers.append(login)
        elif r["state"] == "APPROVED" and r["authorAssociation"] in TRUSTED:
            oid = (r["commit"] or {}).get("oid")
            if oid == pr["headRefOid"]:
                on_head.append(login)
            else:
                stale.append((login, oid))
    return on_head, stale, blockers


SMALL_INTERDIFF = 20  # code lines changed since approval that a quick re-review can cover


def code_change(git_dir, ref):
    """The PR's net added/removed lines against main, per file, docs excluded. Line numbers and
    context are ignored, so a rebase (or code moving under it) leaves this unchanged."""
    base = git(git_dir, "merge-base", "origin/main", ref).stdout.strip()
    if not base:
        return None
    diff = git(git_dir, "diff", base, ref, "--", ".", ":(exclude)ROADMAP.md", ":(exclude)docs/*.md").stdout
    return [l for l in diff.splitlines() if l[:1] in "+-" and not l.startswith(("+++ ", "--- "))
            or l.startswith("diff --git")]


def approval_drift(git_dir, number, stale):
    """(carried, small): stale approvers whose approved code change equals the head's (a rebase,
    docs or trailers only), and {approver: n} for those within SMALL_INTERDIFF code lines."""
    ref = f"refs/scan/pr-{number}"
    if git(git_dir, "fetch", "-q", "origin", f"+refs/pull/{number}/head:{ref}").returncode != 0:
        return [], {}
    head = code_change(git_dir, ref)
    carried, small = [], {}
    for login, oid in stale:
        if not oid or head is None:
            continue
        if git(git_dir, "cat-file", "-e", oid).returncode != 0:
            git(git_dir, "fetch", "-q", "origin", oid)
        approved = code_change(git_dir, oid) if git(git_dir, "cat-file", "-e", oid).returncode == 0 else None
        if approved is None:
            continue
        # ponytail: multiset difference of lines, ignores order; good enough to size a re-review.
        delta = sum(((Counter(head) - Counter(approved)) + (Counter(approved) - Counter(head))).values())
        if delta == 0:
            carried.append(login)
        elif delta <= SMALL_INTERDIFF:
            small[login] = delta
    return carried, small


def conflict_files(git_dir, number):
    """Files that conflict when the PR head merges into origin/main, or None if unknown."""
    out = git(git_dir, "merge-tree", "--write-tree", "--name-only", "origin/main", f"refs/scan/pr-{number}")
    if out.returncode not in (0, 1):
        return None
    return sorted({l.split(" in ", 1)[1] for l in out.stdout.splitlines() if l.startswith("CONFLICT") and " in " in l})


DOCS_ONLY = re.compile(r"^(ROADMAP|README|CHANGELOG)\.md$|^docs/.*\.md$")


def ci_state(d):
    nodes = d["commits_last"]["nodes"]
    rollup = nodes[0]["commit"]["statusCheckRollup"] if nodes else None
    if not rollup:
        return "none", []
    bad, pending = [], []
    for c in rollup["contexts"]["nodes"]:
        name = c.get("name") or c.get("context") or "?"
        if IGNORED_CHECKS.search(name):
            continue
        if c["__typename"] == "CheckRun":
            if c["status"] != "COMPLETED":
                pending.append(name)
            elif c["conclusion"] not in ("SUCCESS", "SKIPPED", "NEUTRAL"):
                bad.append(name)
        elif c.get("state") in ("PENDING", "EXPECTED"):
            pending.append(name)
        elif c.get("state") != "SUCCESS":
            bad.append(name)
    if bad:
        return "red", bad
    if pending:
        return "pending", pending
    return "green", []


def git(git_dir, *args):
    return subprocess.run(["git", "-C", git_dir, *args], capture_output=True, text=True)


def main_drift(git_dir, number, paths):
    """Files the PR touches that changed on origin/main since the PR's merge base."""
    ref = f"refs/scan/pr-{number}"
    if git(git_dir, "fetch", "-q", "origin", f"+refs/pull/{number}/head:{ref}").returncode != 0:
        return None
    base = git(git_dir, "merge-base", "origin/main", ref).stdout.strip()
    if not base:
        return None
    changed = set(git(git_dir, "diff", "--name-only", base, "origin/main").stdout.split())
    behind = git(git_dir, "rev-list", "--count", f"{base}..origin/main").stdout.strip()
    return int(behind or 0), sorted(changed & set(paths))


def test_start(git_dir, ref, path, cache={}):
    """Line number of the first #[cfg(test)] in the PR-head file (inline test module), or None."""
    key = (ref, path)
    if key not in cache:
        out = git(git_dir, "show", f"{ref}:{path}").stdout if git_dir else ""
        cache[key] = next((i for i, l in enumerate(out.splitlines(), 1) if l.strip() == "#[cfg(test)]"), None)
    return cache[key]


def diff_findings(repo, git_dir, number):
    out = subprocess.run(["gh", "pr", "diff", str(number), "-R", repo], capture_output=True, text=True)
    if out.returncode != 0:
        return ["diff unavailable"], []
    ref = f"refs/scan/pr-{number}"
    path, line_no, panics, new_cmds = "", 0, [], []
    for line in out.stdout.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
            continue
        if m := re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line):
            line_no = int(m.group(1)) - 1
            continue
        if line.startswith("-") or line.startswith("\\"):
            continue
        line_no += 1
        if not line.startswith("+"):
            continue
        if m := NEW_CMD.match(line):
            new_cmds.append(m.group(1))
        if not path.endswith(".rs") or re.search(r"(^|/)tests?(/|\.rs$)|_tests?\.rs$|/benches/|/examples/", path):
            continue
        if PANICKY.search(line) and not re.search(r"^\+\s*(debug_)?assert", line):
            start = test_start(git_dir, ref, path)
            if start is None or line_no < start:
                panics.append(f"{path}:{line_no}: {line[1:].strip()[:90]}")
    return panics, new_cmds


def assess(repo, git_dir, pr, carried=()):
    owner, name = repo.split("/")
    d = gh_graphql(DETAIL_Q, owner=owner, name=name, n=pr["number"])["pullRequest"]
    on_head, _, _ = approval_state(pr)
    if git_dir:  # conflict_files needs the head before main_drift fetches it
        git(git_dir, "fetch", "-q", "origin", f"+refs/pull/{pr['number']}/head:refs/scan/pr-{pr['number']}")
    flags, checks = [], []
    files = d["files"]["nodes"]
    paths = [f["path"] for f in files]
    counted = sum(f["additions"] + f["deletions"] for f in files if not SIZE_EXEMPT.search(f["path"]))
    if d["changedFiles"] > 100:
        counted = max(counted, d["additions"] + d["deletions"])  # file list truncated
    if counted > MAX_LINES or d["changedFiles"] > MAX_FILES:
        flags.append(f"large: {counted} lines / {d['changedFiles']} files")
    labels = {l["name"].lower() for l in d["labels"]["nodes"]}
    if labels & FEATURE_LABELS:
        flags.append(f"feature label: {', '.join(sorted(labels & FEATURE_LABELS))}")
    for rx, why in RISKY:
        hit = [p for p in paths if rx.search(p)]
        if hit:
            flags.append(f"{why}: {', '.join(hit[:3])}")
    added = [f["path"] for f in files if f["changeType"] == "ADDED"]
    if any(re.search(r"^(crates|apps)/[^/]+/Cargo\.toml$", p) for p in added):
        flags.append("new crate")
    if bins := [p for p in paths if BINARY.search(p)]:
        flags.append(f"binary/asset files: {', '.join(bins[:3])}")
    if re.search(r"\bintegration\b|\bbatch\b", d["title"], re.I):
        flags.append("integration/batch PR: merge commit + full look, not this skill")
    mergeable = d["mergeable"]
    # ponytail: GitHub computes mergeability lazily; UNKNOWN on first ask, so ask once more.
    if mergeable == "UNKNOWN":
        out = subprocess.run(["gh", "pr", "view", str(pr["number"]), "-R", repo, "--json", "mergeable", "-q", ".mergeable"],
                             capture_output=True, text=True)
        mergeable = out.stdout.strip() or "UNKNOWN"
    conflicts = None
    if mergeable == "CONFLICTING":
        conflicts = conflict_files(git_dir, pr["number"]) if git_dir else None
        if conflicts and all(DOCS_ONLY.search(p) for p in conflicts):
            flags.append(f"conflicts with main, docs only ({', '.join(conflicts)}): rebase request")
        else:
            flags.append("conflicts with main" + (f" ({', '.join(conflicts[:4])})" if conflicts else ""))
    elif mergeable != "MERGEABLE":
        flags.append(f"mergeability {mergeable}: GitHub hasn't computed it, rescan later")
    ci, ci_names = ci_state(d)
    if ci != "green":
        flags.append(f"CI {ci}" + (f": {', '.join(ci_names[:4])}" if ci_names else " (fork run not approved?)"))
    open_threads = [t for t in d["reviewThreads"]["nodes"] if not t["isResolved"]]
    unresolved = [t for t in open_threads if not t["isOutdated"]]
    if unresolved:
        who = sorted({(t["comments"]["nodes"] or [{}])[0].get("author", {}).get("login", "?") for t in unresolved})
        flags.append(f"{len(unresolved)} unresolved review thread(s) ({', '.join(who)})")
    if outdated := len(open_threads) - len(unresolved):
        # Outdated is not addressed (#2905: the code moved, the bug stayed). The light pass checks each.
        checks.append(f"{outdated} outdated open thread(s): check each was addressed")
    drift = main_drift(git_dir, pr["number"], paths) if git_dir else None
    panics, new_cmds = diff_findings(repo, git_dir, pr["number"])
    if new_cmds:
        flags.append(f"new command(s) = feature: {', '.join(new_cmds[:4])}")
    if panics:
        checks.append(f"panic-path additions in non-test code ({len(panics)}): " + " | ".join(panics[:3]))
    if drift is None and git_dir:
        checks.append("could not compute drift vs main")
    elif drift:
        behind, overlap = drift
        if overlap:
            checks.append(f"{behind} commits behind main; main also changed {', '.join(overlap[:4])} - CI may be stale")
    return {
        "number": d["number"], "title": d["title"], "url": d["url"],
        "author": (pr["author"] or {}).get("login", "ghost"), "approvers": on_head + [f"{l} (carried: same diff)" for l in carried],
        "conflicts": conflicts,
        "size": f"+{d['additions']}/-{d['deletions']} ({d['changedFiles']}f)",
        "head": d["headRefOid"], "cross_repo": d["isCrossRepository"],
        "flags": flags, "checks": checks,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="storytold/wordcraft")
    ap.add_argument("--git-dir", default=".", help="local clone with an `origin` remote ('' to skip drift)")
    ap.add_argument("--json")
    a = ap.parse_args()
    owner, name = a.repo.split("/")
    if a.git_dir:
        git(a.git_dir, "fetch", "-q", "origin", "main")

    prs, after = [], None
    while True:
        page = gh_graphql(LIST_Q, owner=owner, name=name, after=after)["pullRequests"]
        prs += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    candidates, flagged, stale_list, small_list = [], [], [], []
    for pr in prs:
        if pr["isDraft"] or pr["baseRefName"] != "main":
            continue
        on_head, stale, blockers = approval_state(pr)
        author = (pr["author"] or {}).get("login", "ghost")
        carried, small = [], {}
        if not on_head and stale and a.git_dir:
            carried, small = approval_drift(a.git_dir, pr["number"], stale)
        if not on_head and not carried:
            if small:
                c = conflict_files(a.git_dir, pr["number"])
                small_list.append((pr["number"], pr["title"], small, c))
            elif stale:
                stale_list.append((pr["number"], pr["title"], [l for l, _ in stale]))
            continue
        if author.lower() in BLOCKED_AUTHORS:
            flagged.append({"number": pr["number"], "title": pr["title"], "author": author,
                            "flags": ["author is PierrunoYT - flag to Martin, never merge"]})
            continue
        r = assess(a.repo, a.git_dir, pr, carried)
        if blockers:
            r["flags"].insert(0, f"changes requested by {', '.join(blockers)}")
        (flagged if r["flags"] else candidates).append(r)

    print(f"# Merge scan: {a.repo}\n\n{len(prs)} open PRs; {len(candidates) + len(flagged)} approved on head.\n")
    print(f"## Candidates ({len(candidates)}): need the light read, then Martin picks\n")
    print("| PR | Title | Author | Approved by | Size | Checks |\n|---|---|---|---|---|---|")
    for r in candidates:
        print(f"| #{r['number']} | {r['title'][:70]} | {r['author']} | {', '.join(r['approvers'])} | {r['size']} | {'; '.join(r['checks']) or 'clean'} |")
    print(f"\n## Flagged, excluded ({len(flagged)})\n\n| PR | Title | Author | Why |\n|---|---|---|---|")
    for r in flagged:
        print(f"| #{r['number']} | {r['title'][:70]} | {r['author']} | {'; '.join(r['flags'] + r.get('checks', []))} |")
    docs_only = [r for r in flagged if any("docs only" in f for f in r["flags"])]
    print(f"\n## Docs-only conflicts ({len(docs_only)}): send the rebase-request template\n")
    print(", ".join(f"#{r['number']}" for r in docs_only) or "none")
    print(f"\n## Small change since approval ({len(small_list)}): quick re-review (Sonnet) of the interdiff\n")
    for n, t, s, c in small_list:
        print(f"- #{n} {t[:70]}: " + ", ".join(f"{l} approved, {d} code lines differ" for l, d in s.items())
              + (f"; CONFLICTS: {', '.join(c[:4])} (rebase first)" if c else ""))
    print(f"\n## Approval is stale - the diff changed since approval ({len(stale_list)})\n")
    print(", ".join(f"#{n}" for n, _, _ in stale_list) or "none")
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"candidates": candidates, "flagged": flagged,
                       "small_interdiff": [{"number": n, "title": t, "delta": s, "conflicts": c} for n, t, s, c in small_list],
                       "stale": [{"number": n, "title": t, "approvers": s} for n, t, s in stale_list]}, f, indent=1)


if __name__ == "__main__":
    main()
