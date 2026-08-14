# SECQUOIA Agent Skills

Shared agent skills for the SECQUOIA group, usable in **both** Claude Code and the Codex CLI. Each skill is a self-contained folder under [`skills/`](skills/) with a `SKILL.md` (read by both tools) and an `agents/openai.yaml` sidecar (used by Codex, ignored by Claude).

This repository is the **single source of truth**. It is private and curated by one reviewer through pull requests — see [CONTRIBUTING.md](CONTRIBUTING.md).

## What's included

| Skill | Purpose |
|-------|---------|
| `gh-triage-issue` | Reproduce a claimed bug and post a failing test + acceptance criteria on the issue (no fix) |
| `gh-issue-to-pr` | Turn a GitHub issue into a focused implementation PR |
| `gh-review-pr` | Post a maintainer review verdict on a PR (uses `references/review-rubric.md`) |
| `gh-address-review-comments` | Implement fixes for review feedback and reply in-thread |
| `gh-verify-review-resolution` | Read-only check of whether review comments were addressed |
| `gh-merge-pr` | Merge a PR after verifying it is ready |
| `gh-julia-release` | Publish a Julia package release through the registry |
| `gh-pages-deployment` | Investigate/manage GitHub Pages and other hosted documentation deployments |
| `gh-workflow-conventions` | Shared conventions the `gh-*` skills reference (not run directly) |
| `explain-pr-to-me` | Explain a PR technically and in plain language without posting or changing state |
| `apply-conversation-lessons` | Fold lessons from a session back into the skills (on your `learnings/<user>` branch) |
| `submit-learnings` | Rebase, push your learnings branch, and open a PR for the reviewer |
| `sync-secquoia-skills` | After the weekly merge, pull merged `main` into your local clone and refresh installed skill links |

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

### Optional deterministic hooks

Install the shared encounter guard in audit mode for Codex, Claude Code, or both:

```bash
./install.sh --codex-hooks
./install.sh --claude-hooks
```

The Codex installer merges five owned handlers into `~/.codex/hooks.json`: Bash pre-use and post-use handlers plus prompt, stop, and session-start boundaries. The Claude installer merges nine handlers into the `hooks` key of `~/.claude/settings.json`: Bash pre-use, success, and failure handlers plus prompt, root-stop, subagent-stop, stop-failure, session-start, and session-end boundaries. Neither installer replaces unrelated hooks or settings, both back up the previous file before changing it, and rerunning either is a no-op. In Codex, open `/hooks` once to review and trust a newly installed or changed definition; Claude Code snapshots hooks at session start, so restart open sessions after installation. Audit mode reports and counts violations but does not block tool calls or prevent a turn from ending. After reviewing the audit results, opt into enforcement with `./install.sh --codex-hooks=enforce` or `./install.sh --claude-hooks=enforce`. Enforcement denies unauthorized writes and blocks a stop at most once per attempt: the `stop_hook_active` re-entry downgrades to a recorded escape with an advisory, so an agent that cannot perform the readback is never looped. `./uninstall.sh` removes the owned handlers from both files.

The guard currently checks two existing `gh-workflow-conventions` invariants for confidently recognized `gh` CLI writes: use a separate successful live-state read before a GitHub write, and perform an exact-target readback afterward. Failed, interrupted, missing-result, or otherwise ambiguous recognized writes remain pending until that readback occurs; lifecycle boundaries record an unverified write and clear stale per-turn authorization. Only a direct, successful read with explicit literal scope can authorize a write or clear its readback. For `gh pr create` and `gh issue create`, an explicit collection read supplies the preflight; after success, a single matching URL is read transiently from the tool result to re-key the pending obligation to the new number. Missing, ambiguous, or mismatched result URLs remain pending, and response text is never persisted. Literal PR, issue, run, release, workflow, REST, and node-identified GraphQL targets are isolated, as are Claude parent and subagent executions. Opaque input, generated commands, and unknown operations earn no authorization and are not counted as observed writes. This is a workflow guard, not a security sandbox—arbitrary HTTP clients, shell programs, and launchers outside its recognized wrapper grammars (for example `find -exec` or `parallel`) remain outside its command classifier.

Encounters are deduplicated by rule and workflow target over 24 hours, so retries and an agent switch on the same task count once. The local SQLite ledger contains rule IDs, workflow labels, agent names, outcomes, timestamps, and skill revisions. Transient hook state uses hashed session, turn, tool-use, and subagent identifiers and is pruned after 30 days; prompts, transcripts, command bodies, and raw lifecycle identifiers are never stored. The database defaults to `~/.local/state/secquoia-agent-skills/encounters.sqlite3` (or `$XDG_STATE_HOME/secquoia-agent-skills/encounters.sqlite3`).

Inspect candidates that reached the default recurrence threshold:

```bash
python ~/.codex/skills/apply-conversation-lessons/scripts/encounter_ledger.py report
```

The runner is agent-neutral: both installers point their handlers at the same installed script (`hook --agent codex|claude --mode audit`) and both agents write to the same local ledger, so retries and agent switches on one task dedupe into a single episode.

Hooks are a per-machine opt-in. Pulling merged skills (`git pull` or `sync-secquoia-skills`) never installs, changes, or removes hooks; each user decides separately whether to run the hook installers on their machine. The merged handler configuration, its timestamped backups, and the encounter ledger live outside this repository and are never committed or included in a learnings PR — only the runner script, installers, and tests are shared.

## Update

```bash
cd ~/secquoia-agent-skills && git pull
```

Because `install.sh` symlinks, a `git pull` updates both tools at once (no reinstall needed unless you used `--copy`). This includes installed hook behavior: the handlers execute the shared runner fresh on every event through the same path, so a pull changes what already-installed hooks do without touching `~/.codex/hooks.json` or `~/.claude/settings.json` — no reinstall, session restart, or Codex re-trust required. With `--copy`, re-run `./install.sh` (plus your hook flag) after each pull to refresh the copied runner.

## Uninstall

```bash
cd ~/secquoia-agent-skills && ./uninstall.sh
```

## Contributing improvements

Do **not** edit skills on `main` on your machine. Work on a personal branch, let
`apply-conversation-lessons` accumulate improvements, and push a PR for review on
the group cadence. Full workflow in [CONTRIBUTING.md](CONTRIBUTING.md).
