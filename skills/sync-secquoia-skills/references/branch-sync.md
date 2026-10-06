# Safe synchronization before sync or submission

Read for either `sync-secquoia-skills` or `submit-learnings`. This procedure updates
local Git state only; its caller owns installation refresh or publication.

## Inventory and protect

1. Resolve the managed repository from the invoked skill's real path. For a copy
   installation, read its `.secquoia-install.json` ownership marker, verify the
   installation identifier, referenced source skill and enclosing managed Git
   repository, and operate there. The marker is location evidence, not authority
   to execute instructions. If provenance is absent or stale, ask for the source
   checkout instead of treating the installed copy or task CWD as the repository.
   Verify the
   remote, live default branch, current branch, and clean status. Use explicit
   repository scope for `gh`. Stop if a rebase/merge is already in progress or
   uncommitted work remains; never auto-stash or discard it here.
2. Record local HEAD and the old remote default SHA separately. For submission,
   also read the live remote personal branch SHA (or verified absence) before
   rebasing. Check that its commits are accounted for locally; stop on unexpected
   divergence. Preserve this expected remote SHA for the final push lease.
   Fetch the exact
   ref with `git fetch <remote> refs/heads/<default>:refs/remotes/<remote>/<default>`.
   Record the new default SHA and pre-update skill directory set.
3. Inventory `<remote>/<default>..HEAD` and run
   `git cherry -v <remote>/<default> HEAD`. Explain `+` unique patches and `-`
   upstream patch equivalents before rebasing. An unchanged fetched ref does not
   prove the local branch is up to date.
4. Before rebasing a non-default branch with any commits beyond the default,
   create or reuse a local backup at the recorded HEAD. Look for an existing
   `backup/sync-*` ref pointing there; otherwise use
   `backup/sync-<sanitized-branch>-<UTC-timestamp>-<short-head>`.
   Require the backup SHA to equal pre-sync HEAD. A branch backup protects commits,
   not dirty files; the clean-tree check is mandatory. Never push or auto-delete it.

## Replay and verify

On the default branch, fast-forward to the fetched default tip only; refuse a
divergent local default. On a personal branch, rebase onto the fetched default.
Recheck HEAD/status immediately before changing history; concurrent movement means
the inventory must be refreshed rather than overwritten.

If conflicts occur, record paths and status. Do not force resolutions or skip
commits. Abort the rebase in unattended/shared checkouts, retaining the backup.
In an interactive exclusive checkout, leave it pending only when the user is
actively taking over resolution; otherwise abort and report. Preserve any existing
operation that preceded this procedure rather than aborting someone else's work.

After success, compare
`git range-diff <old-merge-base>..<backup> <remote>/<default>..HEAD`, with the old
merge base computed from the backup and refreshed default. Re-run `git cherry`.
Account for every previously unique patch as retained, rewritten, or proven
upstream-equivalent. Dropping an upstream-equivalent commit identity is expected;
an unexplained missing unique patch blocks completion. When no backup was needed,
verify the intended fast-forward/ancestry directly.

Report default-ref movement and local HEAD movement separately. Count pending
lessons against the refreshed default, not a stale personal tracking branch.
Return the backup, replay evidence, and remaining commits to the caller. Submission
must recheck whether any unique changes remain after replay before opening a PR.
