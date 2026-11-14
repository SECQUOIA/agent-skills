# Batch merges, conflicts and strategy

Read for ordered batches, authority instructions, missing expected PRs, conflicting/stale bases, rebase-only repositories, or branch retention. Apply shared [checkout](../../gh-workflow-conventions/references/worktrees-and-checkouts.md), [change hygiene](../../gh-workflow-conventions/references/change-hygiene.md), and [write rules](../../gh-workflow-conventions/references/github-writes.md) before branch or GitHub mutations.

Resolve the actual requested set. If an expected count differs, inspect relevant PRs/branch heads against fresh base: report already-merged/absorbed work, and ask only when an ahead branch's intended role remains ambiguous. Do not invent a missing PR.

Before the next merge, check [batch CI concurrency](../../gh-workflow-conventions/references/ci-and-checks.md#batch-writes-and-concurrency) for triggered runs that must be preserved; the next base push can displace an earlier pending run.

Respect explicit dependencies or authoritative branches. When no dependency fixes order, consider landing a CI gate before changes it should validate. Test the combined tree where that interaction matters; identical content in both orders does not establish identical validation history.

When a requested PR or batch requires a base update (`BEHIND` under strict checks, conflict, or material combined-tree interaction) and the allowed merge strategy accepts merge commits on the branch, an append-only base merge is permitted; skip unnecessary updates on already `CLEAN` non-interacting PRs so valid approvals and green checks are preserved. Preserve distinct compatible work from both parents; authority governs overlapping semantics, not deletion of unrelated additions. Reuse a reviewed successor resolution only after verifying it preserves the sequence's invariants. Ambiguous conflicts require a concrete decision. Recheck current-head CI/reviews after every resulting push. A single-PR merge request does not automatically authorize editing unrelated siblings.

For an authorized Dependabot PR with only Dependabot commits that needs such a base update, first inspect recent `dynamic` Dependabot runs (matching its ecosystem and package/directory) and re-read the PR head before mutating the branch or posting a command: an automatic rebase can start shortly after a base push while the PR still reports the old head. Wait when a matching update run is queued or running; otherwise, if Dependabot commands are active, request `@dependabot rebase` (bot-managed lockfile regeneration, not contributor history rewriting). Do not push extra merge commits onto an active Dependabot PR merely because a wait budget is expiring, since commits without `[dependabot skip]` disable future automatic rebases (see [Dependabot PR management](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/manage-your-dependency-security/manage-dependabot-prs)) and skip lockfile regeneration; use an append-only base merge only when Dependabot rebasing is disabled or unavailable, merge/squash strategy permits it, and current-head checks validate the merged lockfile. After any rebase or base merge, re-read the new head and verify fresh current-head CI and review gates.

For a rebase strategy, read REST `rebaseable`. Merge-state CLEAN does not mean GitHub can rebase a history containing conflict-resolution merges. If rebaseable is false, report recovery options without improvising a force-push or repository-setting change. Explicitly authorized linearization can use a single commit carrying the reviewed tree with the intended base parent, preserving author credits; verify identical reviewed content/diff, use a lease against the old head, record superseded approval provenance in a new comment, and require fresh CI. Alternative merge-method settings need separate authorization.

## Branch retention

For stacked PRs, record the heads, states and bases of other open PRs the user
requires left unchanged. Check which heads would become reachable from their bases
under the proposed strategy: a merge commit can indirectly mark an ancestor PR
merged and expose its branch to automatic deletion. A request to merge the child
does not waive those preservation constraints. An allowed squash can avoid that
ancestry effect when it preserves the reviewed tree and required PR states;
individual merge calls are not the boundary of the side effect. Explain the
strategy/dependency disposition and verify the resulting tree plus protected
PR states, heads, bases and refs after merging. Do not change repository settings,
retarget PRs or close the ancestor without the corresponding authorization.

When retention is required, record the actual head repository, branch and SHA,
and read the merge repository's live `delete_branch_on_merge`
(`deleteBranchOnMerge`) setting. `gh pr merge --delete-branch=false` does not
override GitHub's automatic deletion. If that behavior conflicts with the user's
constraint, complete other readiness work and resolve the conflict before merging.
Existing automation does not override user instructions; do not infer permission
to change settings or to delete and recreate the branch.
After a retention-sensitive merge, verify the source ref and its tip; report any
movement without overwriting it.

If an unexpected deletion has already occurred, report it accurately. Within
authorized recovery, restore only the recorded source ref at its recorded SHA
after verifying its absence and write access, using the shared write/readback
rules. Preserve any recreated or moved ref; never force-update it. Restoration
does not retroactively satisfy a no-deletion instruction or justify repeating the
known side effect.

A stacked sibling may remain based on the retained predecessor branch after
merge; read its base explicitly during handoff and retarget only if authorized.
