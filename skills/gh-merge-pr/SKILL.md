---
name: gh-merge-pr
description: Merge a GitHub PR after verifying live head, CI, review gates, and mergeability. Handles requested completion and issue handoff; honors the repository's merge policy.
---

# GitHub Merge PR

Land the requested PR only after verifying its live gates. Read [shared conventions](../gh-workflow-conventions/SKILL.md); use `gh` for GitHub interactions. A direct merge request or `$gh-merge-pr` invocation authorizes the merge and safe procedural closeout below. It does not authorize rewriting history, changing repository settings, overriding unfixed feedback, or clearing another reviewer's decision.

## Establish readiness

Resolve the intended repository/PR and read state, author, head SHA, base, draft state, review decision, merge state, checks, and relevant reviews/body findings. If it is no longer open, report the actual state. Do not require a clean local checkout for a purely remote merge; if local work supplies intended fixes, protect it, ensure those fixes are pushed, and verify their actual PR head before merging. Do not silently push unrelated local commits.

Read [CI observation](../gh-workflow-conventions/references/ci-and-checks.md). Require complete, green current-head checks; accept intentional skipped checks under the repository policy and do not ignore reported non-required failures. No checks yet, a watch exit code, or an older green SHA is insufficient. Read live policy before stating an approval is required. `REVIEW_REQUIRED` is a gate unless a live exception is verified as described there; a COMMENT never supplies approval.

Compare approval SHAs with head. When commits postdate approval, inspect that delta and its evidence; verify scoped follow-up fixes or obtain a re-review for substantive unreviewed work. Do not describe a superseded approval as approval of the new head. A repository permitting zero approvals may merge without peer review; report that fact when every review was self-authored.

Inspect paginated review threads, body-only findings, and relevant response history. Verify the code or accepted deferral, not just the “addressed” reply. Direct merge authorization permits resolving an addressed thread at the unchanged head when no later disagreement remains. A nonblocking, explicitly accepted follow-up can conclude a discussion when the linked record still covers the precise work; report it as deferred rather than fixed. Ambiguous, declined, or unfixed Blocking feedback stops the merge absent an explicit override. Do not erase its obligation by resolving it.

Before resolving threads or changing readiness, read [GitHub write rules](../gh-workflow-conventions/references/github-writes.md), recheck exact targets/head, and verify each mutation. Require no unresolved threads unless the user explicitly overrides. Body-only blocking items remain gates even when all threads are resolved.

A standing `CHANGES_REQUESTED` is separate from thread state. An explicit merge instruction from the same invoking account permits dismissing that account's own verdict only after verifying every requested change is delivered; document the delivered fixes and re-read the aggregate decision. Do not manufacture an APPROVE. Another reviewer's standing decision requires that reviewer or an explicit authorized override. User-directed deferrals remain reported obligations.

A merge-now request permits marking a draft ready after other gates pass; re-read readiness and any newly triggered checks. Require a conflict-free head and satisfaction of every applicable merge gate. For ordered batches, conflicts, stale bases, or a rebase-only repository, consult [batch and strategy cases](references/batch-and-strategy.md) before proceeding. Do not infer semantic conflict resolution from mechanical mergeability.

Validate key changed artifacts according to risk. When committed outputs could be stale and no check rebuilds/diffs them, use [artifact verification](../gh-workflow-conventions/references/artifact-verification.md): prove unaffected provenance or check the relevant generated result. Avoid rebuilding unrelated artifacts merely because they exist. Distinguish PR-head evidence from merge-result evidence.

## Merge the verified head

Use the requested strategy if repository policy permits it. Otherwise inspect allowed methods and prefer merge, then squash, then rebase. Check `rebaseable` before a rebase merge; CLEAN merge state alone does not prove rebaseability. Do not delete the branch unless requested or required by repository policy.

Immediately before merging re-read state/head/gates, then run `gh pr merge <pr> --repo OWNER/REPO <strategy> --match-head-commit <verified-head>`. If the head changed, re-assess it; never retry without the head guard. Re-read the PR to verify MERGED state, merge time/commit, base, and URL. Ambiguous write outcomes require readback before any retry.

## Post-merge handoff

Read [post-merge follow-through](references/post-merge.md) when there are base workflows, linked issues, generated deliverables, local synchronization, installer-managed skills, siblings, or requested next-work recommendations. Observe expected checks for the merge commit within the shared bound, distinguishing pending from failing and CI from deployment/security workflows. Do not claim remote work completed when observation is still pending.

Verify relevant issue closure. Default-branch closing keywords may close issues automatically; non-default bases often require later integration. Manually close only under merge-as-completion authorization or established issue-series policy, and only after its criteria are satisfied. Keep genuinely incomplete issues open and identify their closure path.

Return PR link, merge commit, the head and gates verified before merge, post-merge check state, issue actions, and remaining obligations. Include next issue only when requested, and artifact/local-checkout provenance when material. Never equate a successful merge with completed deployment or cleared security alerts without checking those outcomes.
