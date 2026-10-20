# The issue → PR → merge pipeline

These skills support the group's development pipeline. Invoke a stage with
`$skill <ref>` or a matching request. A handoff identifies the next useful stage;
it does not authorize that stage's writes unless the user requested the broader
workflow. All stages share [`gh-workflow-conventions`](skills/gh-workflow-conventions/SKILL.md)
and load specialized references only when relevant.

One agent can execute every authorized stage. Invoking a component skill does not
require another agent. When delegation helps, use the shared
[delegation contract](skills/gh-workflow-conventions/references/delegation.md):
workers perform bounded tasks, while the coordinator verifies handoffs, integrates
changes, and owns stage transitions and publication. A prepared worker result
does not complete a stage that still requires a verified push, review, or merge.

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
   │ gh-address-review-comments│      │  gh-merge-pr  │  verify live gates → merge → scoped closeout
   └────────────┬─────────────┘      └───────┬───────┘
                ▼                             ▼
   ┌──────────────────────────────┐   (post-merge, when relevant)
   │ gh-verify-review-resolution  │   • gh-julia-release   → documented install path
   │  (read-only by default)     │   • gh-pages-deployment → check/manage Pages
   └────────────┬─────────────────┘
                └───▶ targeted/full review only when justified; otherwise handoff
```

## Stages

| Stage | Skill | Does | Hands off to |
|-------|-------|------|--------------|
| 0 | `gh-triage-issue` | Optional, for claimed bugs: re-confirms the defect against fresh base source, reproduces it with one failing test, records acceptance criteria, and posts that evidence on the issue. Writes no fix | `gh-issue-to-pr` |
| 1 | `gh-issue-to-pr` | Implements a focused change, performs proportionate checks, opens a draft PR, and observes current-head CI | `gh-review-pr` |
| 2 | `gh-review-pr` | Posts one maintainer review verdict with severity-tagged findings; checks linked-issue intent and merge-readiness | address (if changes) or merge (if approved) |
| 3a | `gh-address-review-comments` | Implements the smallest correct fixes for review feedback, replies in each thread | `gh-verify-review-resolution` |
| 3b | `gh-verify-review-resolution` | Read-only by default: classifies whether each comment was addressed; recommends No, Targeted, or Full review; posts an outcome review only when requested | address, justified review, or handoff |
| 4 | `gh-merge-pr` | Verifies current-head CI, feedback, policy-dependent approval, and mergeability; merges and performs authorized closeout | release or next work when requested |
| post | `gh-julia-release` | Publishes through documented General or URL-only policy and verifies a fresh `Pkg.add` installation | — |
| post | `gh-pages-deployment` | Investigates/manages GitHub Pages and other hosted documentation deployment state | — |

## Three meta skills (the pipeline improving itself)

The same pipeline maintains the skills:

- `apply-conversation-lessons` — folds friction from a session into the skills, committing to your personal `learnings/<user>` branch (never `main`) in this managed repo.
- `submit-learnings` — when the week's learnings are ready, rebases on `main`, pushes your branch, and opens a PR. The reviewer then runs `gh-review-pr` and `gh-merge-pr` on it — so improvements to the skills flow through the exact same issue→PR→merge pipeline. See [CONTRIBUTING.md](CONTRIBUTING.md).
- `sync-secquoia-skills` — after the reviewer merges the weekly PRs, pulls the merged `main` back into your local clone: rebases your `learnings/<user>` branch onto it and refreshes installed skill links when skills were added or removed. This closes the weekly loop.
