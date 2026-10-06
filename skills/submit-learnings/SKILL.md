---
name: submit-learnings
description: Submit accumulated skill learnings by pushing the personal branch and creating a PR or posting a new status comment. Preserves existing PR text; does not review or merge.
---

# Submit Learnings

Resolve this skill's managed source through its symlink or verified copy ownership
marker under the shared synchronization procedure; require `.managed-skills`. Use the user's
personal `learnings/<user>` branch; never submit from the default branch. If another
non-default branch is intentionally used, identify it in the handoff. Require a
clean working tree; do not stash, discard, or commit unrelated work.

Follow [GitHub conventions](../gh-workflow-conventions/SKILL.md), including permitted
publication surfaces and live-state/readback rules. This invocation authorizes the
branch push and one initial PR or current-state comment, subject to narrower user
instructions and repository policy.

1. Use the shared [safe synchronization procedure](../sync-secquoia-skills/references/branch-sync.md)
   before pushing. It owns backup creation, conflict handling, and replay proof.
   Preserve its local backup. After replay, stop with a verified no-op if no changes
   remain beyond the refreshed default branch.
2. Compare the remote personal head with the expected pre-sync remote head before
   pushing. Push with tracking. If only this verified rebase requires a
   non-fast-forward update, use `--force-with-lease=<branch>:<expected-remote-sha>`; never
   overwrite another session's intervening push or use plain force.
3. Reuse an open PR for this head or create one against the default branch with
   title `learnings: <summary>`. Read the repository template. Describe each changed
   skill's resulting behavior and relevant validation. Put a shared-layout change
   near the top, naming moved paths and the need for contributors to sync.
4. For an existing PR, preserve its title/body and earlier comments unless the user
   requested that edit. Post one new current-state comment with
   `<!-- submit-learnings:head=<HEAD_SHA> -->`; skip an exact marker match. Use a
   body file, live preflight, and exact readback. Do not create a duplicate PR.
5. Observe current-head checks with the shared bounded CI procedure when CI is
   configured. Report pending/absent/failing checks explicitly; do not infer green
   from a watch exit code. Submission does not authorize review or merge.

Report PR URL, branch/commits, skills changed, backup/replay result, publication
action, and CI or other remaining gates. The designated reviewer reviews and
merges; receiving contributors then run `sync-secquoia-skills`.
