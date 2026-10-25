# claude-skills

Skills for [Claude Code](https://claude.com/claude-code).

| Skill | What it does |
|---|---|
| [`reviewing-prs`](reviewing-prs/SKILL.md) | Reviewing someone else's pull request: pin the head, gatekeep, walk a fixed set of risk axes with a concrete failure scenario for each, grade findings P1–P3, and give Approve, Request changes or Comment in a fixed format |
| [`review-agent`](review-agent/SKILL.md) | Local pre-push review of branches written by implementation subagents: blind reviewer per branch, prove the regression test fails without the fix, root cause from code, the reviewing-prs axes and severity, then Ready to push, Send back or Escalate |

## Install

Copy a skill's folder into `~/.claude/skills/` (for you) or a project's `.claude/skills/` (for everyone working in it):

```sh
git clone https://github.com/benandez/claude-skills
cp -r claude-skills/reviewing-prs ~/.claude/skills/
```
