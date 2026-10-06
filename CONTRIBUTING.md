# Contributing

This is a managed skills repository: the default branch is the reviewed shared set.
Contributors accumulate focused improvements on personal `learnings/<github-login>`
branches and submit them for the designated reviewer. Do not commit daily work to
the default branch.

## Set up a personal branch

Use an existing personal branch when present. In a new, clean checkout, create one
with your GitHub login substituted below:

```bash
cd ~/secquoia-agent-skills
git switch -c learnings/YOUR_GITHUB_LOGIN
```

Installed symlinks follow this clone, including your pending improvements. Copied
installations need an explicit refresh; see [installation and root selection](README.md#installation-and-discovery).
The installer adds the repository's pre-push guard when no different hook exists.
That local guard is an additional check, not a substitute for reviewed PRs.

## Accumulate, sync, and submit

1. Invoke `apply-conversation-lessons` when you want durable lessons folded into the
   skills. It validates and commits focused changes locally; it does not push.
2. Run `sync-secquoia-skills` to incorporate merged work. Its
   [safe synchronization procedure](skills/sync-secquoia-skills/references/branch-sync.md)
   is authoritative: require a clean tree, inventory unique patches, preserve a
   verified local backup before rebasing pending commits, and verify their replay.
   It never auto-stashes or discards work. Conflicts are reported with the backup
   retained; unattended rebases are aborted rather than forced through.
3. On the group's review cadence, invoke `submit-learnings`. It uses the same sync
   procedure, rechecks the remote personal head, and pushes with a specific lease
   when the verified rebase requires one. It opens or updates one learnings PR;
   it does not review or merge it.
4. The reviewer uses `gh-review-pr` and `gh-merge-pr`. After merging, contributors
   run `sync-secquoia-skills` again to pick up the reviewed result.

Keep each lesson small enough to review independently. Leave backup branches local.
Avoid replacing this workflow with a bare `git pull` or unprotected rebase on a
personal branch. Synchronization refreshes installed skills as needed while
preserving their roots and copy/symlink mode; lifecycle-hook configuration remains a
separate opt-in.

## What earns a shared change

Follow [the lessons skill](skills/apply-conversation-lessons/SKILL.md) and its
[evidence guidance](skills/apply-conversation-lessons/references/evidence.md).
Explicitly requested improvements, missing safeguards, and repeated failures can
justify edits. An execution miss already covered by a clear rule may require no
new prose. Keep permission boundaries and domain knowledge in the core, with
substantial conditional procedures in linked references.

Use [the evaluation guide](evals/README.md) for model upgrades or substantial routing
and permission changes. Compare the previous skills, candidate, and a minimal
baseline carrying the same organizational policy. Record actual runtime metadata;
report missing fields as unknown. Hook observations are not independent episodes,
causal model attribution, or an overall measure of workflow quality.

Before submission, validate changed skill metadata and links, run tests for changed
executable behavior, and explain material relocated or retired rules. Runtime checks
can be run from the repository with:

```bash
python3 -m unittest discover -s tests
bash -n install.sh uninstall.sh
```

Behavioral evaluations provide different evidence from these deterministic tests.
Report what actually ran and any untested model/client combinations.

## Keep personal data separate

Reusable shared improvements belong on the personal branch and in its PR. Personal
preferences and private workflows belong in an ignored local source or a user-owned
skill directory outside this repository; verify ignore coverage before editing.
Use the discovery root supported by your client, without introducing duplicate
skill names across modern and legacy locations.

Do not commit local encounter databases, hook configuration, hook backups, private
skill identities, or evaluation traces containing credentials or private content.
Only share deliberately reviewed fixtures, aggregate evidence, and implementation.
