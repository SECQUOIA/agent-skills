---
name: sync-secquoia-skills
description: Sync merged shared skills into the local managed clone, preserving pending learnings and refreshing installed skills. Does not push or publish.
---

# Sync Skills

Update local shared skills to the merged default branch plus pending personal
learnings. Resolve this skill's managed source through its symlink or verified copy
ownership marker as described in the shared procedure; the task's current
directory may be unrelated.

Read [GitHub conventions](../gh-workflow-conventions/SKILL.md) for remote reads.
Use [branch-sync.md](references/branch-sync.md) for the shared fetch, backup,
rebase, and replay-verification procedure. This is the same procedure used before
submission. Require a clean tree; report uncommitted work instead of stashing,
committing, or discarding it. Sync never pushes, reviews, or merges PRs.

## Refresh installs

Record the pre-sync skill directory set and compare it with the resulting head.
Inspect actual installed roots and mode; use the installer's documented root
selection rather than assuming one client-specific directory.

- Symlink installs follow existing source files. Run the installer when skills
  were added or removed. It removes only retired links demonstrably owned by this
  clone; foreign entries remain untouched.
- Copy installs require `./install.sh --copy` after changes under `skills/`.
  The installer preserves retired owned copies in backups outside discovery.
  Preserve the selected root and mode. Report failures and stale targets;
  do not partially reinstall by hand.
- Do not install or change lifecycle-hook configuration without a separate request.
  Updating a symlinked runner changes its implementation without changing hooks.
- For private local skills, check link parity across the user's installed agent
  roots. Create missing links only to the existing ignored source and remove only
  its dangling links. Never copy private contents into tracked/shared directories
  or add their identities to shared catalogs.

Keep requested renames separate from synchronization. Clarify an ambiguous skill
identity before renaming directories or metadata; an explicit unambiguous rename
does not need another approval.

## Handoff

Report repository/branch, old-to-new default ref and local HEAD separately, retained
unique patches and skipped upstream equivalents, backup ref (or why unnecessary),
and replay result. State skills added/removed/changed and installed roots refreshed.
Count pending learnings against the refreshed default branch; distinguish a stale
personal tracking remote. Backups remain local and unpushed. If discovery has not
refreshed in the user's client, recommend a fresh session.
