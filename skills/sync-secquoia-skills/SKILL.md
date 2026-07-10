---
name: sync-secquoia-skills
description: "Pull the latest merged skills from a managed shared-skills repo into the user's local clone and installed skill links. Use when the user wants to update their skills after the weekly merge, pick up everyone else's merged learnings, sync or rebase their learnings branch on main, or gives a terse invocation like `$sync-secquoia-skills`. Fetches the default branch, rebases the personal learnings branch onto it (handling the just-merged case), refreshes install symlinks or copies when skills were added or removed, and reports what changed. It does not push, review, or merge. Complements submit-learnings, which pushes the branch and opens the weekly PR."
---

# Sync Skills

## Overview

Use this workflow after the reviewer has merged the weekly `learnings/*` pull requests: it brings the user's local clone of a managed shared-skills repo (one marked with a `.managed-skills` file) up to date with the merged default branch, so their live skills are again "`main` plus their pending learnings". It is the counterpart of `submit-learnings` for the receiving side of the weekly cadence, and it automates step 1 of the weekly loop in CONTRIBUTING.md.

This skill only updates local state: it fetches, rebases the personal branch, and refreshes installed skill links. It does not push (`submit-learnings` owns pushing), does not review, and does not merge.

## Preconditions

1. Confirm this is a managed skills repo: the git repository root contains a `.managed-skills` file. The current working directory is often an unrelated project, not the skills repo — do not assume CWD is it. Resolve this skill's own base directory through any symlinks (`readlink -f`) to its real location, take that file's enclosing git root, and confirm the `.managed-skills` marker there; operate on that repo for the rest of the workflow. If no such repo is found, stop and report that this skill is only for managed shared-skills repos.
2. Determine the default branch with `gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name'`.
3. Determine the current branch. By convention it is a personal `learnings/<user>` branch; if it is the default branch, skip the rebase and only fast-forward it. If it is some other non-default branch, treat it as the learnings branch but say so in the final report.
4. Require a clean working tree. If it is dirty, stop and report the offending files — do not stash, commit, or discard changes here; uncommitted lessons belong to `apply-conversation-lessons`.

## Workflow

1. Record the pre-sync state.
   - `git fetch origin refs/heads/<default>:refs/remotes/origin/<default>` (an explicit refspec, so the remote-tracking ref itself is refreshed).
   - Record the old and new `origin/<default>` SHAs, and the branch's own commits (`git log --oneline origin/<default>..HEAD` before fetching may be stale — compute counts after the fetch).
   - Record the current skill directory set (`git ls-tree --name-only HEAD:skills`) to compare after the update.
   - If the old and new default-branch SHAs are equal and the branch is already based on it, report "already up to date" and stop after the install check below.

2. Update the branch.
   - On the personal learnings branch: `git rebase origin/<default>`. Commits already merged upstream are skipped automatically; if every local commit was merged (the usual case right after the weekly merge), the branch ends up even with the default branch — report that explicitly, it is the expected outcome, not an error.
   - On the default branch: `git pull --ff-only`; if fast-forward is not possible, stop and report instead of creating a merge commit.
   - If the rebase conflicts, stop and report the conflicting files and the exact state (`git status`), and leave the rebase in place for the user to resolve or abort (`git rebase --abort` restores the pre-sync state). Do not force resolutions or skip commits; conflicts usually mean the reviewer merged someone else's change to the same skill lines, and the user should decide whose wording survives.
   - Do not push. The remote personal branch is refreshed by `submit-learnings` on the next weekly submission.

3. Refresh the installed skills.
   - Compare the skill directory set from step 1 against `git ls-tree --name-only HEAD:skills` after the update.
   - Determine the install mode by inspecting an installed entry (for example `~/.claude/skills/<skill>` and `$CODEX_HOME/skills/<skill>`, default `~/.codex/skills`): a symlink into this repo means symlink mode; a real directory means copy mode.
   - Symlink mode: existing skills need nothing (the symlinks track the clone), but a skill directory that was **added** has no symlink yet — re-run `./install.sh` (idempotent) so new skills are linked into every target. For **removed** skills, also delete the now-dangling symlinks in each target directory (only symlinks that point into this repo and no longer resolve).
   - Copy mode: copies never track the clone, so re-run `./install.sh --copy` whenever the sync changed anything under `skills/`.
   - If `install.sh` is missing or fails, report the exact error and which targets were left stale rather than partially reinstalling by hand.

4. Report.
   - Summarize what came in: `git log --oneline <old-sha>..origin/<default>` and `git diff --stat <old-sha> origin/<default> -- skills/`, plus skills added or removed by name.
   - State whether the branch is now even with the default branch or still carries N unmerged local commits (list them), whether installs were refreshed, and that a fresh agent session is needed to pick up changed skill descriptions.

## Final Response

Return the repo path, the branch synced, the default-branch range applied (old..new SHAs with a one-line-per-commit summary), skills added/removed/changed, whether the rebase left the branch even with the default branch or N commits ahead, whether install links or copies were refreshed, and any conflict or error that stopped the sync. Keep it concise and professional; no emoji or praise padding.
