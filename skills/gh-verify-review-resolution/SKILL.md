---
name: gh-verify-review-resolution
description: Check whether a PR addresses existing review feedback or a referenced report. Read-only by default; post an outcome or perform bounded closeout only when explicitly requested.
---

# GitHub Verify Review Resolution

Assess existing findings at the current head, rather than starting a new review. Read [shared conventions](../gh-workflow-conventions/SKILL.md); use `gh` for GitHub interactions.

## Action boundary

Protect the original checkout: do not change its files, index, branches, HEAD, or Git metadata. Do not commit/push, mutate GitHub state, resolve threads, or start/re-run/cancel CI by default. Read existing CI and run proportionate local checks in disposable scratch space when execution is permitted. Temporary query files, exact-head scratch repositories, and isolated mutations are allowed; they do not relax protection of the original checkout or authorize external writes. A no-execution instruction remains binding.

For execution, read [scratch verification](references/scratch-verification.md) and the shared [checkout guidance](../gh-workflow-conventions/references/worktrees-and-checkouts.md) before materializing or testing source. Fetch missing objects into a scratch repository; do not build a hybrid from a dirty or divergent checkout. Verify the exact source tree and imported package identity before trusting a result.

A direct request to approve/post the outcome, resolve addressed threads, or mark ready authorizes only those bounded closeout actions after assessment. Read [closeout](references/closeout.md) at that point. Recommendations and automated re-entry never create that authorization. Merging belongs to `gh-merge-pr`.

## Inventory and inspect

1. Resolve the PR and record current head, base, state, relevant reviewed SHA, and commits since review. Read head-specific diffs/content, not a name-matching local branch. Accept merged/closed PRs for historical verification; do not present obsolete gates as current blockers.
2. Read all paginated review threads and their `isResolved` state, review bodies, and actionable discussion feedback, including resolved findings that later changes could have regressed. Empty inline thread lists do not exclude body-only findings. Use `gh-review-pr:finding` markers or severity-prefixed titles as body item identities. Empty review wrappers for inline replies are transport metadata, not extra findings.
3. If the user named a report/checklist, derive its full inventory from that artifact, map items to GitHub findings/fixes, and report source coverage separately. An earlier partial review inventory cannot substitute for the source. Treat `gh-arc` summaries as claimed fixes, not independent requests unless they contain new feedback.
4. Verify each item's complete concern against head code, contracts, docs, and evidence. An author's “addressed” reply or a resolved flag is insufficient. Revisit relevant dependencies after base merges or refactors. Preserve the finding's scope: an old identifier elsewhere outside the changed contract is not automatically an incomplete rename.
5. Scale new checks to what moved. Carry earlier evidence forward when relevant source, tests, inputs, environment, and contracts are unchanged or demonstrably inert. Re-measure head-dependent counts/claims when relevant changes invalidate them. For a new coverage guard, disputed protection, or consequential uncertainty, use [mutation safety](../gh-workflow-conventions/references/mutation-testing.md); routine verification does not require mutations. For outputs or visual parity, read [artifact guidance](../gh-workflow-conventions/references/artifact-verification.md) or [notebooks](../gh-workflow-conventions/references/notebook-artifacts.md) and inspect the delivered outputs, not source alone.
6. Read structured CI for the current head, allowing a bounded watch only when useful. Inspect branch policy when claiming an approval, required-check, or conversation gate. Separate content resolution, open threads, and formal review verdicts. A standing `CHANGES_REQUESTED` needs that reviewer's updated decision or dismissal; another account's approval does not erase it. On merged PRs, inspect the timeline before calling a historical verdict outstanding work.

## Classify and decide

Give every comment/finding/report item one status with concise supporting code, commit, test, or live-state evidence:

- `Addressed`: the requested remedy is adequately delivered.
- `Partially addressed`: a defined part remains.
- `Not addressed`: the concern remains.
- `Not applicable`: changed code or an incorrect premise makes it inapplicable.

Treat a requested nonblocking deferral as Addressed only when technically valid and tracked with working cross-links. Separately flag declined Blocking items for human decision; never silently downgrade an explicit severity. A content-addressed open thread is an administrative gate only when enforced, not a reason to downgrade its content status.

Choose `No`, `Targeted`, or `Full` for another review round. Prefer another address pass when remaining work is already defined. Use Targeted for bounded judgment about a revised approach; provide prior/current SHAs, intervening commits, item IDs, affected surfaces, and the precise review question. Use Full only when cross-cutting change prevents a reliable narrower assessment. New defects belong in a new-review handoff, not an outcome review of old items.

Cap automated review/address/verify cycles at the agreed limit, default three. Escalate recurring non-convergence instead of restarting the budget. Progressively smaller nonblocking self-review refinements do not justify endless rounds; prefer closeout once the actual gates are satisfied.

## Response

Use exactly these numbered sections:

1. Overall assessment
2. Comment-by-comment status
3. Tests or CI evidence inspected
4. Remaining issues
5. Whether another review round is justified
6. Recommended next action

Begin section 5 with `No`, `Targeted`, or `Full` and explain the reason. For `Targeted`, include the bounded review question and compact re-review brief above; for `Full`, state why a reliable narrower assessment is not possible. Include separate source-report coverage when relevant, evidence reused and its basis, declined Blocking items, and verified closeout results if requested. Otherwise recommend the appropriate next action without executing it. Offer an eligible outcome review when all items are Addressed; an author cannot formally approve their own PR.
