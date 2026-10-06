# Batch merges, conflicts and strategy

Read for ordered batches, authority instructions, missing expected PRs, conflicting/stale bases, or rebase-only repositories. Apply shared [checkout](../../gh-workflow-conventions/references/worktrees-and-checkouts.md), [change hygiene](../../gh-workflow-conventions/references/change-hygiene.md), and [write rules](../../gh-workflow-conventions/references/github-writes.md) before branch or GitHub mutations.

Resolve the actual requested set. If an expected count differs, inspect relevant PRs/branch heads against fresh base: report already-merged/absorbed work, and ask only when an ahead branch's intended role remains ambiguous. Do not invent a missing PR.

Respect explicit dependencies or authoritative branches. When no dependency fixes order, consider landing a CI gate before changes it should validate. Test the combined tree where that interaction matters; identical content in both orders does not establish identical validation history.

An explicitly authorized ordered sequence can include append-only base merges needed to update its PRs. Preserve distinct compatible work from both parents; authority governs overlapping semantics, not deletion of unrelated additions. Reuse a reviewed successor resolution only after verifying it preserves the sequence's invariants. Ambiguous conflicts require a concrete decision. Recheck current-head CI/reviews after every resulting push. A single-PR merge request does not automatically authorize editing unrelated siblings.

For a rebase strategy, read REST `rebaseable`. Merge-state CLEAN does not mean GitHub can rebase a history containing conflict-resolution merges. If rebaseable is false, report recovery options without improvising a force-push or repository-setting change. Explicitly authorized linearization can use a single commit carrying the reviewed tree with the intended base parent, preserving author credits; verify identical reviewed content/diff, use a lease against the old head, record superseded approval provenance in a new comment, and require fresh CI. Alternative merge-method settings need separate authorization.

Do not delete branches by default. A stacked sibling may remain based on the retained predecessor branch after merge; read its base explicitly during handoff and retarget only if authorized.
