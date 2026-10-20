# Changes in managed skill repositories

Read before changing a skill whose real path belongs to a shared repository,
contains a `.managed-skills` marker, or has a documented review cadence.

For delegated analysis or edits, first use the shared
[optional delegation contract](../../gh-workflow-conventions/references/delegation.md).
The same lessons pass remains complete in one agent; helpers return bounded
changes/evidence and do not independently sync, integrate, submit, or publish.

1. Resolve the skill's real repository, current branch, and status. For an owned
   copy, verify its installation marker and source using the linked sync procedure
   before editing; edit the managed source and refresh the owned copy afterward.
   Never edit the default branch in place. Identify the user's personal
   `learnings/<user>` branch and inspect dirty state without mutating it.
2. If the checkout is not writable or another session is using it, use an isolated
   worktree from the personal branch with the required filesystem permission.
   Record the original personal tip before synchronizing the isolated branch.
   Choose isolation before any sync/rebase or branch mutation, not after syncing
   a shared checkout. Preserve uncommitted work in the original;
   do not silently transfer unrelated changes or clear them during integration.
   Do not bypass file-edit restrictions with shell rewrites.
3. In the selected writable, exclusive checkout, validate and commit clearly
   related accumulated lessons separately before synchronization. Preserve unrelated
   or ambiguous dirty work and report it when it prevents a clean sync. Refresh the
   personal working branch with the sibling
   [sync procedure](../../sync-secquoia-skills/references/branch-sync.md) before new edits.
   In isolation, record the pinned upstream and post-sync tip separately so the
   new lesson commits can later be identified without replaying old work twice.
4. Commit focused validated changes using the observed message style. Stage only
   intended content. Recheck status and recent history before staging: if another
   session advanced HEAD, inspect its commits before deciding what remains.
   Include the concrete problem, changed/retired contracts, and validation in the
   commit body for consequential changes. Verify the staged snapshot and resulting commit; do not reclaim attribution
   by amending or rebasing someone else's work.
5. For isolated work, use [integration planning](integrating-isolated-work.md).
   Rebase can rewrite ancestry: fast-forward only when it is actually possible.
   Preserve the worktree/result and backup until integration is verified; report
   integration pending when the destination cannot safely be reconciled.
6. When adopting selected lessons from another contributor, copy only the agreed
   paths onto the user's personal branch; do not merge their entire branch.
7. Keep commits local. Pushing/opening a PR belongs to an explicit
   `submit-learnings` request, followed by the repository's review cadence.

## Private and installed skills

Prefer the existing user-owned source of an installed skill. Resolve symlinks
instead of editing a second copy. Keep agent-specific settings out of shared
frontmatter; validate supported fields with each intended consumer.

An explicitly chosen ignored local-skills directory is a valid edit target. Check
every file with `git check-ignore -v` before editing, and verify installed links
afterward. If any file is exposed, repair or clarify that privacy boundary before
editing. Never stage, publish, catalog, or copy private skills into shared locations.
Use a generic ignored directory instead of naming private skills in tracked ignore
entries. Personal lessons otherwise belong outside the managed repository.
