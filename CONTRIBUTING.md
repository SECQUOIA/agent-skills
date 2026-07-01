# Contributing

This is a **managed** skills repo: `main` is the canonical set everyone installs, and
all changes land through pull requests reviewed by a single reviewer. The goal is that
everyone tracks the same `main` and no two people ever edit it directly — so the skills
never silently diverge and merge conflicts stay rare and reviewable.

## The model

- **`main` is read-only for daily use.** You install it, you `git pull` it, you don't commit to it locally. Because this repo is private on a free plan, GitHub branch protection isn't available, so `install.sh` installs a **pre-push hook** that blocks accidental `git push origin main`. Reviewer merges via `gh pr merge` (server-side) are unaffected; override intentionally with `git push --no-verify`.
- **Each person works on a personal branch** named `learnings/<your-github-username>`.
- **`apply-conversation-lessons` is managed-repo-aware.** In this repo (it detects the `.managed-skills` marker) it commits improvements to your personal branch, never to `main`, and never pushes on its own. It just accumulates.
- **Weekly cadence:** after ~a week of use, push your branch and open a PR. The reviewer checks it with `gh-review-pr`, and merges with `gh-merge-pr`. Everyone then pulls the merged `main`.

This dogfoods the very skills in this repo: improvements flow through `gh-issue-to-pr` → `gh-review-pr` → `gh-merge-pr`.

## One-time setup

```bash
cd ~/secquoia-agent-skills
git checkout -b learnings/<your-github-username>
```

Your install symlinks point at this clone, so your live skills are always "`main` plus your pending learnings" — which is what you want.

## Weekly loop

```bash
# 1. Pick up everyone else's merged updates first (surfaces conflicts early)
git fetch origin
git rebase origin/main

# 2. Push your accumulated learnings and open a PR
#    Easiest: run the skill, which does the rebase, push, and PR for you:
#      $submit-learnings
#    Or by hand:
git push -u origin learnings/<your-github-username>
gh pr create --base main --title "learnings: <short summary>" --fill
```

Then the reviewer reviews and merges. After a merge, everyone runs the rebase in step 1.

Keep each lesson **small and self-contained** — one focused improvement per commit — so PRs are easy to review and rarely conflict.

## What goes where

- **A genuine, reusable improvement to a shared skill** → your `learnings/<user>` branch → PR. This is the normal path.
- **A one-off personal quirk not meant for everyone** → put it in a skill *outside* this repo (your own `~/.codex/skills/<something>/`), so `main` stays canonical.

## For the reviewer

- Review incoming `learnings/*` PRs with `gh-review-pr`; merge with `gh-merge-pr`.
- Tag releases (`git tag vX.Y`) when you want a stable pin students can check out.
- Adding a new student is just: grant repo access, then they clone + `./install.sh`.
