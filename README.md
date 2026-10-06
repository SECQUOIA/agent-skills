# SECQUOIA Agent Skills

Shared workflow skills for Codex and Claude Code. Each folder in [`skills/`](skills/)
contains a `SKILL.md`; Codex also uses its `agents/openai.yaml` sidecar. This repository
is the source of truth, with changes reviewed through pull requests.

## Included workflows

| Skill | Purpose |
|-------|---------|
| `gh-triage-issue` | Reproduce a bug and publish evidence and acceptance criteria |
| `gh-issue-to-pr` | Implement an issue and open a focused draft PR |
| `gh-review-pr` | Post a maintainer review verdict |
| `gh-address-review-comments` | Implement requested fixes and reply to review feedback |
| `gh-verify-review-resolution` | Verify existing feedback; publish only when requested |
| `gh-merge-pr` | Verify readiness and merge a PR |
| `gh-julia-release` | Publish through Julia General or a documented URL-only release workflow |
| `gh-pages-deployment` | Investigate Pages or other documentation hosting; change configuration when requested |
| `gh-workflow-conventions` | Shared GitHub policy and reference routing |
| `explain-pr-to-me` | Explain a PR without publishing or editing project files |
| `apply-conversation-lessons` | Make requested, evidence-backed improvements to existing skills |
| `submit-learnings` | Safely sync and submit a personal learnings branch |
| `sync-secquoia-skills` | Sync merged skills while preserving pending local learnings |

See [the issue-to-release pipeline](PIPELINE.md), [contribution workflow](CONTRIBUTING.md),
and [behavioral evaluation guide](evals/README.md). Install the whole set: sibling
references connect these workflows and break if individual folders are installed alone.

## Installation and discovery

The installer requires Bash, Git, and Python 3.10 or newer. Use it from a POSIX shell
on Linux, macOS, or WSL:

```bash
git clone https://github.com/SECQUOIA/agent-skills.git ~/secquoia-agent-skills
cd ~/secquoia-agent-skills
./install.sh
```

A fresh default installation links skills into `~/.agents/skills` for Codex and
`~/.claude/skills` for Claude Code. Start a fresh client session to pick them up.
Existing legacy installations remain supported; the installer selects the Codex
root in this order:

1. An explicit `--codex-skills-dir /path/to/skills`.
2. The single populated root among `~/.agents/skills` and the selected Codex home's
   `skills` directory, preserving an existing installation.
3. A custom Codex home's `skills` directory when `--codex-home` or `CODEX_HOME`
   selects a nondefault home.
4. `~/.agents/skills` for a fresh default installation.

Codex configuration and hooks stay in `CODEX_HOME` (default `~/.codex`), independently
of skill discovery. `--codex-home` overrides that setting. `--user-home /path` supplies
an isolated user root, including default config locations, without changing `HOME`.

```bash
./install.sh --copy                         # copy instead of symlinking
./install.sh --codex-skills-dir /path/to/skills
./install.sh --codex-home /path/to/codex-config
```

The installer checks both clients' destinations before replacing any skill. It
refuses foreign entries and duplicate Codex discovery roots. Inspect unmarked legacy
copies before moving them outside discovery; they are not automatically adopted.
To move an owned installation to another root, uninstall the old set before installing
at the new root. Preserve custom root flags when updating or uninstalling.

Owned copies have a source marker. Copies differing from the source are backed up
outside the discovery directory before replacement or removal. Foreign files,
foreign symlinks, and unmarked copies are preserved. The repository's pre-push guard
is installed when no different hook already exists.

When a source skill is removed, install and uninstall recognize only its exact
owned link or source marker. They remove owned dangling links and back up every
retired owned copy outside discovery; a missing source cannot establish whether
the copy contains local edits. Entries belonging to another clone remain untouched.
Installation checks current-source conflicts before pruning retired entries.

## Optional encounter hooks

Hooks are a per-machine opt-in, separate from installing skills:

```bash
./install.sh --codex-hooks                  # audit mode
./install.sh --claude-hooks                 # audit mode
./install.sh --codex-hooks=enforce          # optional enforcement
./install.sh --claude-hooks=enforce
```

Codex handlers live in the selected Codex home's `hooks.json`; Claude handlers live
in `~/.claude/settings.json`. Installation preserves unrelated hooks and settings,
backs up changed files, and is repeatable with the same arguments. In Codex, review
and trust the definition through `/hooks`; restart client sessions as needed.
Generated commands retain the Python interpreter used during installation, with
interpreter and script paths quoted so spaces remain valid.

The guard checks two rules for recognized `gh` operations: a separate successful
live-state read before a write, and a matching readback afterward. Audit mode records
and reports missing checks. Enforcement denies recognized writes lacking an eligible
preflight and blocks a stop at most once per attempt. A failed or ambiguous write
remains pending until readback; a lifecycle boundary records outstanding work.

Only a successful read with explicit literal scope supplies evidence. For creation,
a scoped collection read supplies the preflight and an unambiguous result URL can
identify the new issue or PR. Response text is inspected transiently. The classifier
does not cover arbitrary HTTP clients, generated commands, or every shell wrapper;
its flags are workflow observations, not a security boundary or model failure rate.

## Encounter evidence and model comparisons

The SQLite ledger defaults to
`~/.local/state/secquoia-agent-skills/encounters.sqlite3`, or the corresponding
`$XDG_STATE_HOME/secquoia-agent-skills/` directory. Rule-and-target episodes deduplicate
retries and agent/model switches over a rolling 24-hour window. Each newly recorded
observation retains its own outcome, skill revision, event, and agent.

Optional runtime labels are `model`, `reasoning_effort`, `client_version`, and
`harness_version`. Hooks accept explicit top-level labels, including `model_slug`;
missing or invalid labels stay null. A manual `record` command also accepts
`--model`, `--reasoning-effort`, `--client-version`, and `--harness-version`. Supply
observed labels only; do not infer them from a default configuration.

From the repository:

```bash
python3 skills/apply-conversation-lessons/scripts/encounter_ledger.py report --json
```

Reports retain episode totals and add `runtime_observations` grouped by recorded
context. Cohorts can share episodes, and a boundary event's model is the observer,
not necessarily the writer. Legacy attempts have no reconstructed attribution or
per-attempt outcome; they appear as `unattributed_legacy_observations`. Reports include
all observations belonging to episodes active in the selected window.

Hooks do not persist prompts, transcripts, command bodies, or raw lifecycle IDs.
Transient identifiers are hashed and pruned after 30 days. Runtime parsing accepts
bounded identifier labels, ignoring nested metadata and tool output. Keep manual
workflow labels and `--detail` limited to abstract task information. Local ledgers,
hook configuration, and their backups must not enter shared commits.

See [evidence guidance](skills/apply-conversation-lessons/references/evidence.md)
for interpreting classifier flags, and [evaluations](evals/README.md) for controlled
comparisons. Passing script tests or shortening instructions does not establish
better model behavior.

## Updating and removing

Use `sync-secquoia-skills` to update the managed clone and refresh installed skills.
Its [safe synchronization procedure](skills/sync-secquoia-skills/references/branch-sync.md)
protects committed learnings before replay and requires a clean working tree.
Symlinks follow source changes; rerun `./install.sh` when skills are added or removed.
Copied installations require `./install.sh --copy` after source changes. Keep the
same root flags; the installer reconciles added and retired owned entries.
Start a fresh session if the client has not refreshed its skill catalog.

Updating a symlinked hook runner also updates the implementation used by existing
handlers. Sync does not change hook configuration or opt anyone into hooks. Review
configuration changes separately rather than assuming every client reloads them.

```bash
./uninstall.sh                             # preserve foreign entries and changed copies
./uninstall.sh --codex-skills-dir /path/to/skills
```

Uninstall removes this checkout's owned skill entries and hook handlers associated
with its source or currently owned installed scripts. It preserves hooks belonging
to another checkout and retains the local encounter history. See
[CONTRIBUTING.md](CONTRIBUTING.md) before changing shared skills.
