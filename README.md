# SECQUOIA Agent Skills

Shared agent skills for the SECQUOIA group, usable in **both** Claude Code and the Codex CLI. Each skill is a self-contained folder under [`skills/`](skills/) with a `SKILL.md` (read by both tools) and an `agents/openai.yaml` sidecar (used by Codex, ignored by Claude).

This repository is the **single source of truth**. It is private and curated by one reviewer through pull requests — see [CONTRIBUTING.md](CONTRIBUTING.md).

## What's included

| Skill | Purpose |
|-------|---------|
| `gh-issue-to-pr` | Turn a GitHub issue into a focused implementation PR |
| `gh-review-pr` | Post a maintainer review verdict on a PR (uses `references/review-rubric.md`) |
| `gh-address-review-comments` | Implement fixes for review feedback and reply in-thread |
| `gh-verify-review-resolution` | Read-only check of whether review comments were addressed |
| `gh-merge-pr` | Merge a PR after verifying it is ready |
| `gh-julia-release` | Publish a Julia package release through the registry |
| `gh-pages-deployment` | Investigate/manage GitHub Pages deployments |
| `gh-workflow-conventions` | Shared conventions the `gh-*` skills reference (not run directly) |
| `apply-conversation-lessons` | Fold lessons from a session back into the skills (on your `learnings/<user>` branch) |
| `submit-learnings` | Rebase, push your learnings branch, and open a PR for the reviewer |

These skills chain into one issue → PR → merge pipeline — see [PIPELINE.md](PIPELINE.md).

> **The skills reference each other by relative sibling paths** (e.g. every `gh-*`
> skill reads `../gh-workflow-conventions/`). They must be installed **together**;
> installing one folder in isolation will break those references.

## Install

Requires `bash` and git. Works on macOS/Linux/WSL.

```bash
git clone https://github.com/SECQUOIA/agent-skills.git ~/secquoia-agent-skills
cd ~/secquoia-agent-skills
./install.sh          # symlinks every skill into ~/.codex/skills and ~/.claude/skills
```

Start a fresh Codex or Claude session and the skills appear (e.g. `/gh-review-pr`, or trigger by description).

- **Windows without symlink support:** `./install.sh --copy` (then re-run after each `git pull`).
- **Custom Codex home:** set `CODEX_HOME` before running.

## Update

```bash
cd ~/secquoia-agent-skills && git pull
```

Because `install.sh` symlinks, a `git pull` updates both tools at once (no reinstall needed unless you used `--copy`).

## Uninstall

```bash
cd ~/secquoia-agent-skills && ./uninstall.sh
```

## Contributing improvements

Do **not** edit skills on `main` on your machine. Work on a personal branch, let
`apply-conversation-lessons` accumulate improvements, and push a PR for review on
the group cadence. Full workflow in [CONTRIBUTING.md](CONTRIBUTING.md).
