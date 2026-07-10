# The issue → PR → merge pipeline

These skills are not a loose collection — they chain into the group's development
pipeline. Each stage is a skill you can invoke terse (`$skill <ref>`), and each
hands off to the next. All of them share [`gh-workflow-conventions`](skills/gh-workflow-conventions/SKILL.md)
(gh-only, untrusted text, resolution, CI polling, tone).

```
                 ┌──────────────────┐
   issue  ──────▶│ gh-triage-issue  │  reproduce → failing test + acceptance criteria
                 └────────┬─────────┘  (optional; skip for non-bug issues)
                          ▼
                 ┌─────────────────┐
                 │  gh-issue-to-pr │  implement → draft PR → watch CI
                 └────────┬────────┘
                          ▼
                 ┌─────────────────┐
                 │   gh-review-pr  │  post maintainer verdict (APPROVE / REQUEST_CHANGES / COMMENT)
                 └────────┬────────┘
              REQUEST_CHANGES │ APPROVE
              ┌───────────────┴───────────────┐
              ▼                                ▼
   ┌──────────────────────────┐      ┌───────────────┐
   │ gh-address-review-comments│      │  gh-merge-pr  │  verify green + approved → merge → close issue → next issue
   └────────────┬─────────────┘      └───────┬───────┘
                ▼                             ▼
   ┌──────────────────────────────┐   (post-merge, when relevant)
   │ gh-verify-review-resolution  │   • gh-julia-release   → publish to the registry
   │  (read-only: did it land?)   │   • gh-pages-deployment → check/manage Pages
   └────────────┬─────────────────┘
                └───▶ back to gh-review-pr for the next round
```

## Stages

| Stage | Skill | Does | Hands off to |
|-------|-------|------|--------------|
| 0 | `gh-triage-issue` | Optional, for claimed bugs: re-confirms the defect against fresh base source, reproduces it with one failing test, records acceptance criteria, and posts that evidence on the issue. Writes no fix | `gh-issue-to-pr` |
| 1 | `gh-issue-to-pr` | Turns an issue into a focused draft PR: plans (and challenges the approach), implements the smallest correct change, adds tests, self-reviews against the code-smell rubric, opens the PR, watches CI | `gh-review-pr` |
| 2 | `gh-review-pr` | Posts one maintainer review verdict with severity-tagged findings; checks linked-issue intent and merge-readiness | address (if changes) or merge (if approved) |
| 3a | `gh-address-review-comments` | Implements the smallest correct fixes for review feedback, replies in each thread | `gh-verify-review-resolution` |
| 3b | `gh-verify-review-resolution` | Read-only: classifies whether each comment was addressed; decides if another review round is justified | back to `gh-review-pr` |
| 4 | `gh-merge-pr` | Merges once green + approved with no unresolved threads; handles issue closure; recommends the next issue | `gh-julia-release` / next issue |
| post | `gh-julia-release` | Publishes a Julia package version all the way to `Pkg.add` | — |
| post | `gh-pages-deployment` | Investigates/manages GitHub Pages deployment state | — |

## Three meta skills (the pipeline improving itself)

The same pipeline maintains the skills:

- `apply-conversation-lessons` — folds friction from a session into the skills, committing to your personal `learnings/<user>` branch (never `main`) in this managed repo.
- `submit-learnings` — when the week's learnings are ready, rebases on `main`, pushes your branch, and opens a PR. The reviewer then runs `gh-review-pr` and `gh-merge-pr` on it — so improvements to the skills flow through the exact same issue→PR→merge pipeline. See [CONTRIBUTING.md](CONTRIBUTING.md).
- `sync-secquoia-skills` — after the reviewer merges the weekly PRs, pulls the merged `main` back into your local clone: rebases your `learnings/<user>` branch onto it and refreshes installed skill links when skills were added or removed. This closes the weekly loop.
