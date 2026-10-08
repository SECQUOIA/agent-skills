# Post-merge follow-through

Read for expected merge-commit workflows, linked issues, artifact delivery, local synchronization, installer-managed skills, sibling handoffs, or requested next-work recommendations.

Observe expected base runs for the actual merge commit under shared [CI bounds](../../gh-workflow-conventions/references/ci-and-checks.md). Poll directly if watch transport fails. Separate CI, docs/deployment, cleanup, dependency updates and security-alert state; none implies another completed. A bounded pending result is a truthful handoff, not a reason to loop indefinitely or claim green. Any separately authorized side-branch push needs its own proportionate verification.

For key user-facing deliverables, verify relevant paths at the merge commit through GitHub. State provenance when the local checkout remains on a successor/unrelated branch; absence there does not mean the artifact missed the merge. If local base synchronization is part of the workflow, preserve dirty/untracked collisions under checkout guidance and fast-forward only when safe. A remote merge itself does not authorize discarding local work. When a managed skill change adds/removes/renames install units, run its documented authorized sync/install and verify discovery; pull alone does not create new symlinks.

Re-read known sibling handoffs after the base advances, including baseRefName and mergeability. Report newly conflicting or still-stacked branches; modify/retarget them only within batch or explicit authorization. For dependency/security remediations, inspect any expected graph/update runs and relevant alert closure separately from CI.

Inventory and re-read both original implementation/rollout trackers and linked
follow-up repair issues. A closed repair issue does not establish closure of its
original tracker. Default-base closing keywords may have closed issues; `Refs`
does not, and non-default bases usually defer closure. Scope an "all issues closed"
claim to the complete verified target set, including original trackers.

Manual closure needs merge-as-completion authorization or established issue-series
policy and fulfilled criteria, unless the maintainer explicitly accepts deferral
of remaining work. Do not invent a first future automatic merge/deployment as a
closure gate when it is only an operational observation. If an issue requires that
live check, retain it until satisfied or explicitly deferred. A maintainer may ask
to close a completed implementation before that event: comment with merged PRs,
available validation, and the unobserved check, then close and verify the state.
Report the check as deferred rather than passed; closure does not establish a live
result or authorize new follow-up issues or automation.

For ordered series, verify the immediate predecessor/tracker before applying
closure precedent. Post required final validation evidence before authorized
manual closure, and update a workflow-owned provisional handoff only when that
exact update is authorized.

When next work is requested, use actual issue/tracker order, prerequisite status, and merged implementation evidence. Keep unfinished follow-ups open unless the maintainer explicitly accepts their closure under the criteria above. Classify dependency PRs as superseded/relevant/rebase-needed against current manifests; close superseded PRs only when requested. Return the next issue link and a concrete reason rather than assuming list order is roadmap order.
