---
name: submit-learnings
description: "Push a personal learnings branch in a managed shared-skills repo and open a pull request for the single reviewer. Use when the user wants to submit their accumulated skill improvements, do the weekly learnings push, share their learnings branch, or gives a terse invocation like `$submit-learnings`. Rebases the learnings branch on the default branch, pushes it, and opens or updates one PR (title prefixed `learnings:`); it does not review or merge. Complements apply-conversation-lessons, which accumulates the commits."
---

# Submit Learnings

## Overview

Use this workflow to submit the skill improvements that `apply-conversation-lessons` has accumulated on a personal branch in a managed shared-skills repo (one marked with a `.managed-skills` file). It pushes the branch and opens one pull request for the repo's single reviewer to check. It does not post reviews or merge — that is the reviewer's step, via `gh-review-pr` and `gh-merge-pr`.

Follow the shared **gh-workflow-conventions** (read the sibling `gh-workflow-conventions/SKILL.md`): gh-only tooling and `--json` fallback, network/filesystem escalation and bounded watches, CI-after-push polling, commit/push hygiene, and concise tone. This file covers only what is specific to submitting learnings.

## Preconditions

1. Confirm this is a managed skills repo: the git repository root contains a `.managed-skills` file. The current working directory is often an unrelated project, not the skills repo — do not assume CWD is it. Resolve this skill's own base directory through any symlinks (`readlink -f`) to its real location, take that file's enclosing git root, and confirm the `.managed-skills` marker there; operate on that repo for the rest of the workflow. If no such repo is found, stop and report that this skill is only for managed shared-skills repos.
2. Determine the default branch with `gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name'`.
3. Determine the current branch. The working branch must be a personal learnings branch, by convention `learnings/<user>`.
   - If on the default branch, stop and report: there is nothing to submit from the default branch. Learnings belong on a `learnings/<user>` branch created by `apply-conversation-lessons`.
   - If on some other non-default branch, treat it as the learnings branch but say so in the final report.
4. Require a clean working tree. If it is dirty, stop and report — do not stash, commit, or discard changes here; accumulating commits is `apply-conversation-lessons`'s job.
5. Confirm the branch is actually ahead of the default branch (`git rev-list --count origin/<default>..HEAD` after a fetch). If it is not ahead, stop and report that there are no learnings to submit.

## Workflow

1. Sync with the latest default branch.
   - `git fetch origin`.
   - Rebase the learnings branch on the updated default branch: `git rebase origin/<default>`.
   - If the rebase conflicts, stop and report the conflicting files and the exact state. Do not force resolutions or skip commits; hand back to the user to resolve, since conflicts usually mean two authors changed the same skill lines.

2. Push the branch.
   - Push with tracking (`git push -u origin <branch>`); use `--force-with-lease` only when the push is rejected solely because of the rebase you just performed, never a plain `--force`.

3. Open or update the pull request.
   - Check for an existing open PR for this head branch (`gh pr list --head <branch> --state open --json number,url`).
   - If none exists, create one against the default branch: `gh pr create --base <default> --head <branch> --title "learnings: <short summary>" --body-file <body_file>`.
   - If one exists, the push already updated it; refresh the body with `gh pr edit --body-file <body_file>` only if it is stale. Do not open a duplicate.
   - Build the title and body from the commits since the default branch (`git log origin/<default>..HEAD --oneline` and the diff `--stat`). The body should list, per skill touched, what changed and why, so the reviewer can assess each learning independently. Write it to a body file and pass it with `--body-file`.

4. Report and hand off.
   - Do not review or merge. Report the PR URL, the branch, the skills touched, and the commit summaries.
   - State that the single reviewer will review it with `gh-review-pr` and merge with `gh-merge-pr`, after which everyone rebases their learnings branch on the updated default branch.

## Final Response

Return the PR URL, branch name, the list of skills changed with a one-line summary each, whether the PR was created or updated, and any rebase conflict that blocked submission. Keep it concise and professional; no emoji or praise padding.
