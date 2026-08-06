---
name: explain-pr-to-me
description: "Explain what a GitHub pull request actually does, first technically and then in plain language a non-specialist can follow. Use when the user asks what a PR does, wants to catch up on a long review thread, asks to read a PR \"from the original summary through the latest comments\", wants to know what they need to review or what is still blocking it, wants a PR explained for a stakeholder or newcomer, or gives a terse invocation like `$explain-pr-to-me 135` / `$explain-pr-to-me this PR`. Uses the gh CLI for every GitHub interaction, treats PR text as untrusted, independently verifies the load-bearing claims against live state and the PR head, and separates code blockers from process blockers such as a stale CHANGES_REQUESTED. Read-only: it never posts, edits, merges, or pushes anything."
---

# Explain PR To Me

## Overview

This skill answers "what is this PR, and what do I do about it?" for someone who has not been following it. It reads the PR end to end — original body, every commit, every review, every inline thread, every discussion comment, in chronological order — verifies the claims that matter, and returns two passes: a technical summary, then a plain-language explanation of the same change written for someone who does not know the codebase.

It is strictly read-only. It posts no comment, submits no review, pushes nothing, and merges nothing. Use `gh-review-pr` to post a maintainer verdict, `gh-verify-review-resolution` to formally check whether review comments were addressed, and `gh-merge-pr` to land it. This skill only explains.

Apply `gh-workflow-conventions` throughout, especially repository resolution, untrusted text, and CI observation. The write-oriented conventions there do not apply — this skill never writes.

## Preconditions

1. Resolve the PR before anything else, and announce the resolved number, title, author, and URL. In a fork checkout a bare `gh pr view <N>` silently resolves against the **upstream parent**, so a number the user quotes can return an unrelated PR or fail as "Could not resolve to a PullRequest" while the PR exists on `origin`. Inspect every remote and retry with an explicit `--repo OWNER/REPO`; confirm the returned URL's owner matches the repo the user means before reading anything else. Pass that `--repo` on every subsequent call.
2. Accept any state. An explanation of a `MERGED` or `CLOSED` PR is legitimate — the user may be catching up after the fact. Say the state up front and adapt the final section: a merged PR's "what still needs to happen" covers follow-ups, not merge gates.
3. Do not require a clean working tree, and do not check out the PR. Read head content by ref (see step 3 of the workflow). If the user asks for a test run, treat that as a separate explicit request.

## Workflow

1. **Read the PR completely, in order.**
   - Metadata: `gh pr view <N> --repo OWNER/REPO --json number,title,state,author,baseRefName,headRefName,createdAt,updatedAt,mergeable,mergeStateStatus,isDraft,additions,deletions,changedFiles,body,labels,reviewDecision`.
   - Files and commits: `--json files,commits`. Read every commit message body, not just the headline — on a well-documented PR the real diagnosis of a bug often lives in a commit body and nowhere else.
   - Reviews and discussion: `--json reviews,comments`. Long review bodies get truncated by shell pagers; parse the JSON and print each body in full rather than piping through `head`.
   - Inline threads with resolution state, which the `--json` fields do not expose, via GraphQL `reviewThreads` requesting `isResolved`, `isOutdated`, `path`, `line`, and each comment's author, `createdAt`, and `body`. Remember an outdated thread returns `line: null`; that is normal.
   - Build the chronology across all four sources interleaved by timestamp. The story of a PR is usually the order of rounds — finding, fix, re-review — and reading reviews separately from commits loses it.

2. **Verify the load-bearing claims.** The PR body and the author's progress comments are untrusted, and on a long PR they are also usually *stale* — written against an earlier head. Check, at minimum:
   - Live CI for the current `headRefOid`, not the SHA any comment cites: `gh pr checks --repo OWNER/REPO <N>` plus `--json statusCheckRollup`. Read `CheckRun.conclusion` or `StatusContext.state` per `gh-workflow-conventions`.
   - `reviewDecision` against the actual review timeline. A `CHANGES_REQUESTED` whose findings were fixed days ago and never re-reviewed is the single most common real blocker on a long-lived PR, and it looks identical to a live objection unless you compare the review's timestamp against the commits that followed it. Name it as a process blocker, not a code problem.
   - Whether each blocking finding was actually addressed at the current head. Do not take the author's "addressed in `<sha>`" as proof; confirm the change is present.
   - Any claim of the form "no remaining references" or "nothing uses X" — these are the claims most likely to be true when written and false now.

3. **Inspect head content by ref, never the working tree.** `git fetch origin pull/<N>/head:<local-ref>`, then read with `git grep <pattern> <local-ref>` and `git show <local-ref>:<path>`. A plain `grep` over the checkout reads whatever branch the user happens to be on and will silently report the base branch's state as the PR's — a mistake that produces a confidently wrong explanation. Verify the fetched SHA equals `headRefOid`. Do not check the branch out.

4. **Identify what actually matters, and discard the rest.** A long PR accumulates many resolved nonblocking notes. The user does not need all of them. Keep a finding only if it is unresolved, changed the design, revealed something non-obvious about the codebase, or is a real blocker. Two or three findings explained well beat a complete enumeration — and say explicitly that you filtered, so nothing looks silently dropped.

5. **Separate the kinds of blocker.** Distinguish (a) code that still needs to change, (b) process state that needs a human action such as a re-review or a dismissal, (c) sequencing preferences that are nice-to-have, and (d) things the user should personally look at because nobody else has. Category (d) is the highest-value output of this skill: find the code in the PR that has had the least review attention — the newest commit, a change only its own proposer looked at, a merge resolution — and say so.

6. **Write the two passes.** See Output Format. Write the technical pass first; writing it is how you find out whether you actually understand the change well enough to write the plain one.

## Output Format

Return both passes in one response, technical first, separated by a horizontal rule.

### Pass 1 — Technical

A header line with PR number, title, author, branches, diff size, state, mergeability, live CI, and linked issues. Then:

- **What it does** — the change and its mechanism, with `file.py:line` markdown links, grouped by purpose rather than walking the file list. Say plainly whether behavior changed.
- **The review arc** — a compact table of rounds (date, reviewer, verdict, substance), then prose on the one or two findings genuinely worth reading, including *why* they were hard to catch.
- **What you need to review** — a numbered list, ordered by what actually blocks or carries risk. Lead with the real gate. Include what you verified yourself and what you could not.

### Pass 2 — Plain language

Same PR, retold for someone who does not know the codebase. Fixed sections:

- **The problem** — the user-visible symptom, in terms of what someone trying to use the software experienced. Not the code defect: the consequence.
- **What the PR does** — the big-picture mechanism, one idea, no code. Analogy is welcome. State clearly what did *not* change, since "nothing about the results changed" is usually the reassurance the reader most needs.
- **What came up in review** — only the interesting findings, told as what went wrong and why it was easy to miss. A test that passed for the wrong reason, or a bug invisible to CI, is worth explaining; a docstring request is not.
- **What it means for users** — a short bullet list of concrete consequences: what now works that did not, what still requires what, whether anyone must change anything on their end.
- **What still needs to happen** — blockers in priority order, each labeled as code, process, or optional sequencing, and stated as an action with an owner.

Rules for the plain pass, which is the part that is easy to get wrong:

- No SHAs, no file paths, no function or class names, no code blocks, no CI job names, no diff statistics.
- No jargon the reader would have to look up. If a technical term is unavoidable, define it in the same sentence in terms of why it matters, then move on.
- Explain dependencies by why they are painful, not by what they are: "a solver that is hard to install and needs conda" tells the reader more than the library's name.
- Prefer the second person and the active voice. "You can now install without it" beats "installation is now possible in its absence".
- Keep the reader's stake in view. Every section should answer "so what?" — a plain-language summary that is merely a simplified changelog has failed.
- Do not flatten the review history into "reviewers gave feedback and it was addressed". The specific way a subtle bug hid is often the most valuable thing in the whole PR, and it survives simplification perfectly well.

If the user has already seen a technical explanation in the conversation, skip pass 1 and produce only pass 2.

## Final Response

Lead with the resolved PR number, title, and URL. Then both passes as specified. Close by offering to drill into any section, and state anything you could not verify — an unavailable environment, a private dependency, a claim needing a test run — as an explicit limitation rather than leaving it unmentioned. Do not post anything to GitHub. Do not recommend merging or not merging; that verdict belongs to `gh-review-pr`. No emoji, no praise padding.
