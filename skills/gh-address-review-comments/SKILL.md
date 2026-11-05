---
name: gh-address-review-comments
description: Address GitHub PR review feedback, push fixes, and publish resolutions. Use for requested changes or unresolved comments; explicit local-only or commit-and-push limits remain binding.
---

# GitHub Address Review Comments

Implement safe, in-scope feedback and make its disposition reviewable. Read [shared conventions](../gh-workflow-conventions/SKILL.md); use `gh` for GitHub interactions. A full invocation authorizes append-only fixes, one new summary per batch, inline replies, and eligible review re-requests. A bare “commit and push,” or an explicit local/draft/push-only limit, authorizes only that surface; it does not newly authorize comments, replies, metadata edits, or reviewer requests. Preserve authorization already granted in the session.

## Protect the workspace and resolve the head

Resolve the PR, head repository/branch/SHA, state, and author before editing. Inspect local status, untracked files, branch identity, and local/remote ancestry **before checkout, pull, or any reset**. Read [checkout guidance](../gh-workflow-conventions/references/worktrees-and-checkouts.md). Preserve all unrelated work. Use the existing checkout only when its state and verification inputs are safe; otherwise use an isolated checkout at the exact remote head.

If a local branch diverges, including after a remote rebase/force-push, work from an isolated exact remote head and leave the local variant and uncommitted work intact. A backup branch preserves commits, not dirty files. Do not reset hard, stash, rebase, amend, or force-push as recovery. Append commits only unless rewriting history was explicitly requested. If the remote advances before push, reconcile safely from refreshed state; never overwrite it.

For contributor branches or feedback transferred from a terminal PR, read [special destinations](references/special-destinations.md). Verify push rights and the explicit destination; same-repository authorship and fork modification permission are separate facts.

## Inventory and disposition

Read paginated GraphQL `reviewThreads` including `isResolved`, nested comments, stable IDs, and location; also read review bodies and discussion comments. Skip resolved threads as targets unless the user includes them or new evidence reopens the concern. `isOutdated` does not prove a fix. Use REST numeric comment IDs or `fullDatabaseId` for replies, not GraphQL node IDs. Include body-only `gh-review-pr:finding` markers. For reviewer-scoped requests, include that reviewer's replies within other people's threads.

Classify targets as actionable, already addressed, informational/out of scope, incorrect/harmful, or declined Blocking. Without a Blocking-only limit, address safe actionable nonblocking requests too. Preserve severity prefixes; an unprefixed correctness, security, regression, or serious maintainability concern is Blocking. Declining a Blocking item leaves it unresolved for human judgment.

Read [feedback triage](references/feedback-triage.md) when feedback overlaps, prescribes a deferral, concerns metadata/settings, claims a prior fix is missing, or makes a broad design claim. Map related targets to one coherent acceptance checklist, verify both diagnosis and remedy against current head, then implement the smallest correct solution. A question can expose a defect; an observation explicitly requiring no change is informational.

If there are no feedback targets, report the empty pass without posting a “nothing to address” comment. If targets exist but all need explanation rather than code, follow the publication path without manufacturing a commit.

## Verify changes

Use repository tests and conventions proportional to the changed behavior. For a bug, prefer a reproducing regression test and confirm the relevant failure/fix; reuse trustworthy existing evidence when its source, inputs, and environment remain valid. For optional mutation proof, first read [mutation safety](../gh-workflow-conventions/references/mutation-testing.md). Do not repeat mutation batteries or broad suites solely because another review round occurred. Keep checks honest: do not weaken tests to make a change pass.

Before staging, inspect the full PR diff for unintended scope, stale docs, generated state, and leftover formatting-only files. Commit only intended files. An assigned worker without the publication handoff returns local changes, check evidence, and prepared resolutions to its coordinator. The designated publisher pushes append-only to the verified head branch and follows [CI completion and observation](../gh-workflow-conventions/references/ci-and-checks.md), reading structured checks for the actual new PR head. A watch exit code is not proof of green CI. If a fork push is not yet reflected in the PR object, poll until the reported head matches before using head markers.

Diagnose actual failures attributable to the changes within the authorized scope. Queued/running checks remain ongoing work before the final resolution handoff; use the shared completion gate for any incomplete handoff. Re-read `reviewDecision`, draft/merge state, and any relevant enforced gates after the push. Addressed code does not clear a standing `CHANGES_REQUESTED`.

## Publish and hand off

When publication is authorized, read [resolution publication](references/publishing-resolutions.md) and the shared [GitHub write rules](../gh-workflow-conventions/references/github-writes.md) before writing. Refresh targets before claiming completeness. Publish one new batch summary and each required inline reply, verify stored bodies and markers, and request eligible reviewers once. Preserve existing PR text and comments; editing a named prior surface needs explicit authorization. Never mark threads resolved in this workflow.

Return PR link, actual fixing commits, relevant checks/CI at the pushed head, each material deferred or declined target, comment/reply and reviewer-request results, and remaining gates. If scope stopped before publication, report the concrete unposted resolutions and authorized work completed.
