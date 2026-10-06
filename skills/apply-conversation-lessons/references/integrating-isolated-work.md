# Integrate isolated skill changes

Read after committing lessons in an isolated worktree. Synchronization can rewrite
the personal branch's old commits; a backup preserves them but does not make the
result a descendant of the original tip.

Record four immutable commit IDs: original personal tip **P**, fetched upstream
**M**, synchronized isolated tip **R** before new edits, and final result **S**.
New lesson commits are `R..S`, not `P..S`. Retain the sync backup and result ref.

Use the read-only [integration planner](../scripts/plan_integration.py):

```text
python -B <skill>/scripts/plan_integration.py --repo <managed-repo> \
  --branch <personal-branch> --default-branch <default> \
  --original <P> --upstream <M> --synced <R> --result <S>
```

The planner checks real ancestry, destination movement, dirty state, ignored-file
collisions, and ongoing operations. Its output is evidence, not authorization or proof of exclusive access.
Coordinate with any session using the destination before changing its state;
a clean `git status` alone does not establish ownership.

- **Already integrated:** verify the resulting content and report where it landed.
- **Fast-forward:** when the destination is still P, clean, and exclusively owned,
  recheck immediately and integrate with
  `git merge --ff-only --no-overwrite-ignore S`. The ignored-file protection also
  guards files created after planning. Verify the result.
- **Reconcile:** do not force a fast-forward or reset the destination. Once clean,
  exclusive access is available, use the shared backup/replay procedure to sync
  the destination against pinned M. Recheck that its starting tip is P; if another
  session advanced it, stop and inventory that work instead. Transfer only the new
  lesson commits `R..S`, preserving the already verified old patches. Inspect any
  conflicts; do not skip or force resolutions. Verify the transferred patches and
  final tree against S when the starting inputs are unchanged. If inputs changed,
  reconcile deliberately and rerun affected validation before claiming equivalence.
- **Blocked:** preserve all refs and user state; report the exact dirty/concurrent
  state or invalid boundary. Continue independent preparation where useful.

If reconciliation cannot safely finish, leave integration pending with P/M/R/S,
backup, worktree path, and remaining action. Never move a checked-out branch with
`update-ref` behind its index/worktree, reset hard, or silently synchronize a shared
checkout just to make the final step convenient. Abort only operations this task
started when they cannot safely finish. Remove the temporary worktree/ref only
after all lesson commits and intended content are verified at the destination.
