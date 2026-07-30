---
name: sync-secquoia-skills
description: "Safely pull the latest merged skills from a managed shared-skills repo into the user's local clone and installed skill links. Use when the user wants to update their skills after the weekly merge, pick up everyone else's merged learnings, sync or rebase their learnings branch on main, or gives a terse invocation like `$sync-secquoia-skills`. Warns about commits absent from the default branch, creates or reuses an unpushed backup branch before rebasing pending learnings, verifies the replay, refreshes installed skills, and reports what changed. It does not push, review, or merge. Complements submit-learnings, which pushes the branch and opens the weekly PR."
---

# Sync Skills

## Overview

Use this workflow after the reviewer has merged the weekly `learnings/*` pull requests: it brings the user's local clone of a managed shared-skills repo (one marked with a `.managed-skills` file) up to date with the merged default branch, so their live skills are again "`main` plus their pending learnings". It is the counterpart of `submit-learnings` for the receiving side of the weekly cadence, and it automates step 1 of the weekly loop in CONTRIBUTING.md.

This skill only updates local state: it fetches, protects pending commits with a local backup branch, rebases the personal branch, and refreshes installed skill links. It does not push (`submit-learnings` owns pushing), does not review, and does not merge. A successful submission is not required before syncing; the backup and replay checks protect committed local learnings that have not been submitted.

## Preconditions

1. Confirm this is a managed skills repo: the git repository root contains a `.managed-skills` file. The current working directory is often an unrelated project, not the skills repo — do not assume CWD is it. Resolve this skill's own base directory through any symlinks (`readlink -f`) to its real location, take that file's enclosing git root, and confirm the `.managed-skills` marker there; operate on that repo for the rest of the workflow. If no such repo is found, stop and report that this skill is only for managed shared-skills repos.
2. Determine the default branch with `gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name'`.
3. Determine the current branch. By convention it is a personal `learnings/<user>` branch; if it is the default branch, skip the rebase and only fast-forward it. If it is some other non-default branch, treat it as the learnings branch but say so in the final report.
4. Require a clean working tree. If it is dirty, stop and report the offending files — do not stash, commit, or discard changes here; uncommitted lessons belong to `apply-conversation-lessons`.
5. Keep skill identity changes separate from sync. If the user also asks to rename this skill or another skill, finish the sync first, then treat the rename as a distinct skill-edit task. Before changing directories, frontmatter `name`, docs, or installed links, confirm any requested name that contains a leading slash or appears to be a misspelling or near-duplicate of an existing skill id; skill ids themselves use lowercase letters, digits, and hyphens, not slash prefixes.

## Workflow

1. Record the pre-sync state.
   - Record the checked-out branch's pre-sync `HEAD` separately from the old `origin/<default>` SHA. They answer different questions: how the local branch moved versus what the fetch brought into the default branch.
   - `git fetch origin refs/heads/<default>:refs/remotes/origin/<default>` (an explicit refspec, so the remote-tracking ref itself is refreshed).
   - Record the old and new `origin/<default>` SHAs. After the fetch, inventory commits not contained in the refreshed default branch with `git log --oneline origin/<default>..HEAD` and classify their patches with `git cherry -v origin/<default> HEAD`: `+` means the patch is still unique to the personal branch, while `-` means an equivalent patch already exists upstream. Show this inventory and warn before any rebase; do not call a `-` commit lost when rebase drops its duplicate commit identity but keeps the content from the default branch.
   - Record the current skill directory set (`git ls-tree --name-only HEAD:skills`) to compare after the update.
   - If the old and new default-branch SHAs are equal and the branch is already based on it, report "already up to date" and stop after the install check below. An empty fetch range alone is not enough: a prior workflow may already have refreshed `origin/<default>` while the personal branch still needs to advance or rebase.
   - Before rebasing a non-default branch, count `git rev-list origin/<default>..HEAD`. When the count is nonzero, protect the recorded pre-sync `HEAD` with an unpushed local branch named `backup/sync-<sanitized-branch>-<UTC-timestamp>-<short-head>`. First use `git for-each-ref --points-at <pre-sync-head> refs/heads/backup/sync-*` to find an existing sync backup at the same commit; reuse and report it instead of creating a duplicate. Otherwise create the branch with `git branch <backup> <pre-sync-head>`, then require `git rev-parse <backup>` to equal the recorded pre-sync `HEAD` before continuing. Never push or automatically delete this backup.

2. Update the branch.
   - On the personal learnings branch: `git rebase origin/<default>`. Commits already merged upstream are skipped automatically; if every local commit was merged (the usual case right after the weekly merge), the branch ends up even with the default branch — report that explicitly, it is the expected outcome, not an error.
   - On the default branch: `git pull --ff-only`; if fast-forward is not possible, stop and report instead of creating a merge commit.
   - If the rebase conflicts, stop and report the conflicting files, exact state (`git status`), and backup branch. Leave the rebase in place for the user to resolve or abort (`git rebase --abort` restores the pre-sync branch state); the backup remains an independent recovery point either way. Do not force resolutions or skip commits; conflicts usually mean the reviewer merged someone else's change to the same skill lines, and the user should decide whose wording survives.
   - After a successful rebase with a backup, compare the old and new commit series with `git range-diff <old-merge-base>..<backup> origin/<default>..HEAD`, where `<old-merge-base>` is `git merge-base <backup> origin/<default>`. Re-run `git cherry -v origin/<default> HEAD`. Require every pre-sync `+` commit to appear as retained or rewritten in the range-diff; a pre-sync `-` commit may disappear because its patch is already upstream. If a unique commit has no post-rebase counterpart and no upstream patch equivalent, stop and report the discrepancy and backup instead of declaring the sync successful.
   - Compute "unmerged local commits" against the refreshed `origin/<default>`, not against the personal branch's tracking remote. Because this skill deliberately does not push, `git status` may say the local branch is ahead of a stale `origin/learnings/<user>` by many commits after a successful sync; report that tracking-branch difference separately instead of calling those commits pending lessons.
   - Do not push. The remote personal branch is refreshed by `submit-learnings` on the next weekly submission.

3. Refresh the installed skills.
   - Compare the skill directory set from step 1 against `git ls-tree --name-only HEAD:skills` after the update.
   - Determine the install mode by inspecting an installed entry (for example `~/.claude/skills/<skill>` and `$CODEX_HOME/skills/<skill>`, default `~/.codex/skills`): a symlink into this repo means symlink mode; a real directory means copy mode.
   - Symlink mode: existing skills need nothing (the symlinks track the clone), but a skill directory that was **added** has no symlink yet — re-run `./install.sh` (idempotent) so new skills are linked into every target. For **removed** skills, also delete the now-dangling symlinks in each target directory (only symlinks that point into this repo and no longer resolve).
   - Copy mode: copies never track the clone, so re-run `./install.sh --copy` whenever the sync changed anything under `skills/`.
   - If `install.sh` is missing or fails, report the exact error and which targets were left stale rather than partially reinstalling by hand.

4. Report.
   - Report the default-branch fetch range and the local branch movement separately. Summarize what the fetch brought in with `git log --oneline <old-default-sha>..origin/<default>` and `git diff --stat <old-default-sha> origin/<default> -- skills/`; summarize how the checked-out branch moved with the pre-sync and post-sync `HEAD` SHAs (use a symmetric log when rebase rewrote commits), plus skills added or removed by name.
   - State the pre-rebase `+`/`-` classification, whether a backup was unnecessary, created, or reused, its branch name and commit, and the replay-verification result. Do not delete the backup during this workflow; tell the user it remains local and unpushed until they explicitly clean it up.
   - State whether the branch is now even with the refreshed default branch or still carries N commits from `origin/<default>..HEAD` (list them), whether its personal tracking remote is stale, whether installs were refreshed, and that a fresh agent session is needed to pick up changed skill descriptions.

## Final Response

Return the repo path, branch synced, default-branch fetch range, and local branch `HEAD` movement as separate old..new SHA pairs; the pre-rebase `+`/`-` commit classification; backup branch name/commit or why none was needed; replay-verification result; skills added/removed/changed; whether the rebase left the branch even with the refreshed default branch or N commits ahead; any separate stale-personal-remote status; whether installs were refreshed; and any conflict or error that stopped the sync. Keep it concise and professional; no emoji or praise padding.
