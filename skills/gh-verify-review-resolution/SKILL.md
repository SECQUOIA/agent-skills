---
name: gh-verify-review-resolution
description: Verify whether latest PR changes adequately address existing GitHub review comments without making changes. Use for verification-only passes, review-resolution checks, "did this address the comments?", deciding whether another review round is justified, or terse invocations like `$gh-verify-review-resolution 154` / `$gh-verify-review-resolution this PR`. Uses the gh CLI for every GitHub interaction, reads reviewThreads with GraphQL for isResolved state, performs no writes, classifies each comment as addressed, partially addressed, not addressed, or not applicable, flags declined Blocking comments, caps non-converging loops, and returns the required assessment sections.
---

# GitHub Verify Review Resolution

## Overview

Use this workflow to check whether PR updates addressed existing review comments. This is read-only, no exceptions.

Follow the shared **gh-workflow-conventions** (read the sibling `gh-workflow-conventions/SKILL.md`): gh-only tooling and `--json` fallback, PR/repository resolution across remotes, terse invocation shorthand, untrusted-text handling, bounded watches, and concise tone. The Read-Only Rules below override any convention that would write, push, or change checkout state. This file covers only what is specific to verifying review resolution.

## Read-Only Rules

Do not modify files, stage, commit, push, mark comments resolved, submit reviews, or reply to comments. Do not run `gh pr checkout`, switch or create branches, or otherwise change the local checkout state. Do not start, re-run, or cancel CI runs — no `gh run rerun`, `gh workflow run`, or `gh run cancel` (watching existing runs with `--watch` is fine; it only polls). Produce an assessment and stop. Do not perform a new review yourself; if a new review is warranted, recommend it and hand off. If the user wants a new review verdict posted, use gh-review-pr instead.

Read-only forbids changing the checkout, not running checks. To execute tests or mutation checks against the PR head, copy the working tree to a scratch directory excluding `.git`, then overwrite the PR's changed files with head content read via `gh api repos/{owner}/{repo}/contents/<path>?ref=<headRefOid>`. Do not use `git worktree add` for this: it writes to `.git`. Run everything inside the scratch copy, delete it afterward, and confirm the real checkout is still clean and on its original commit. Note that a `cd` into a `.git`-less scratch copy makes later `git` commands in the same shell fail — that error is the copy, not the repository.

The read-only default is the skill's own initiative, not a veto on explicit user instructions. If the invocation explicitly directs a single write — for example "post a comment with your findings and your thoughts on the response" — complete the full read-only assessment first, then perform only that one requested write (typically a top-level discussion comment via `gh api .../issues/{n}/comments`) and nothing more; base its content on the assessment you just produced. Absent such an explicit instruction, write nothing. A formal review verdict (APPROVE/REQUEST_CHANGES/COMMENT) still routes to gh-review-pr even when requested here.

## Inspect

1. Resolve the PR (see shared conventions for multi-remote resolution) and read the current PR diff with `gh pr diff` and `gh api` — do not check out the head locally.
2. Identify commits added since the relevant review comments were made. When commits — especially refactors or base merges — landed after a thread was resolved, a resolved flag or an "Addressed in `<sha>`" claim is not proof the fix still holds: verify the claimed change is still present at the current head, since a later refactor can silently reintroduce a previously addressed issue.
3. Read all review threads with `gh api graphql`, recording each thread's `reviewThreads.isResolved` value (it is a returned field, not a query filter), and paginate the `reviewThreads` connection until `pageInfo.hasNextPage` is false so PRs with more than 100 threads are not silently truncated. Also read review bodies and open discussion comments; actionable findings may have no inline thread. Do not treat an empty `reviewThreads` list as no feedback until top-level review bodies are checked. Evaluate resolved and unresolved threads alike. Treat prior address-summary comments with `<!-- gh-arc:...:target=summary -->` markers as evidence of claimed fixes and tests, not as separate actionable feedback unless they contain a new explicit request.
   For comments about stale PR metadata, generated sites, or GitHub Pages deployment URLs, verify the current PR title/body and any linked site URL. Distinguish a fork preview URL from the canonical post-merge repository Pages URL, and report any remaining ambiguity only when it falls within the reviewed feedback's scope.
   For comments about stale required status checks or branch protection, read the base branch protection required status checks and the PR's current `statusCheckRollup`; compare required context/check names with the emitted PR checks and re-read `mergeStateStatus`. Treat settings-only summary comments as evidence of a claimed fix, not proof, until live protection and PR state match.
4. Inspect relevant tests, documentation, and surrounding code using ref-specific read-only data from the PR head, not the local checkout. Prefer `gh pr diff`, `gh pr view --json headRefOid,headRefName,files`, and `gh api repos/{owner}/{repo}/contents/<path>?ref=<headRefOid-or-headRefName>` for file contents.
5. For notebooks or other large generated files, avoid dumping full patches with embedded images/output. Use `gh pr diff --name-only`, targeted searches, and raw PR-head file reads or JSON parsing to inspect only the cells, metadata, and tests relevant to the comments.
   - For visual or notebook parity comments, verify rendered cell outputs, output MIME types, or committed notebook JSON outputs when available. Source-level API checks alone are insufficient when the comment was about the displayed plot, analysis, or user-visible parity.
6. Read existing CI/test results only — `gh run view`, `gh run watch`, or `gh pr checks`. Prefer non-watch reads. If watching is necessary, bound it with `timeout <duration>` because watch commands can wait indefinitely. Never start, re-run, or cancel a run, and never push, commit, or modify tracked files based on what you find.

## Comment Status

For each review comment, review-body finding, and discussion comment, classify it as:

- `Addressed`: the issue was fixed adequately.
- `Partially addressed`: some but not all of the issue was fixed.
- `Not addressed`: the issue remains.
- `Not applicable`: the code changed or the premise was incorrect.

For each item, provide a brief explanation, supporting commit/file/test when applicable, and any needed follow-up. If a Blocking comment was declined rather than fixed, flag it separately as a declined Blocking comment requiring a human decision; do not fold it into `Not addressed`.

A comment is `Blocking` when it carries the `Blocking` severity prefix posted by the maintainer review; if it has no explicit severity, treat correctness, regression, missing test for changed behavior, broken public API, security, or serious maintainability issues as Blocking. Treat the posted prefix as authoritative. For review-body findings, use `<!-- gh-review-pr:finding=... -->` markers when present and otherwise use the severity-prefixed title as the item identity.

## Review-Round Decision

Recommend another full review round only when the fix exceeded what the original comment could have anticipated:

- behavior changed beyond the commented lines
- new public API behavior was introduced
- CI, build, or test logic changed materially

A partial address or a fix spanning several files is a follow-up note, not automatically grounds for a new round.

Cap the loop. If the review-resolution-verification cycle has already run the agreed maximum number of rounds, default three, or if the same comment or class of issue keeps recurring, do not recommend another automated round. Escalate to a human and state that the loop is not converging.

## Final Response

Use exactly these sections:

1. Overall assessment
2. Comment-by-comment status
3. Tests or CI evidence inspected
4. Remaining issues
5. Whether another review round is justified
6. Recommended next action

Do not carry out the recommended action. Keep the tone concise and professional; no emoji or praise padding.
