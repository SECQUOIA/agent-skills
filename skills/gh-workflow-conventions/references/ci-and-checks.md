# CI and Checks

Use when judging checks, reruns, required gates, or workflow changes. CI evidence
belongs to a repository, exact head SHA, event, run, and attempt.

## Observe the actual head

1. Resolve current `headRefOid`. After a push, if the rich PR view still shows the
   old head, check the remote branch ref and narrow REST PR head before watching.
2. Read current-head checks and applicable workflow triggers. Empty checks just
   after a push can mean they have not registered; poll within the workflow's
   bounded window. A watch exit code is never the verdict.
3. After every watch, separately read structured state and conclusion for the
   verified head. Distinguish passed, failed, pending, skipped, gated, and not
   triggered. Do not substitute local tests or a manual dispatch for an absent
   required PR event/context.

`statusCheckRollup` contains both `CheckRun` (`status`, `conclusion`) and
`StatusContext` (`state`). A completed CheckRun or terminal context state is
finished; do not treat a context's null `status` as pending forever. The legacy
combined `/commits/<sha>/status` endpoint omits Actions CheckRuns. Use rollup or
`/commits/<sha>/check-runs`; run IDs in check URLs can help when run-list data lags.

Use bounded watches/polls within the client's per-command duration. Inspect
current state after a harness timeout; it does not prove the run is stuck. Switch
from noisy watch output to compact run/job polling when useful. Keep queued jobs
with no runner, external statuses, and zero-run integration suites distinct.
An inert suite is not code CI: establish whether a code producer or required
context should exist before classifying absence. Missing steps in an in-progress
job are not evidence those steps were omitted.

When several agents need the same CI result, designate one watcher for the
repository/head and relevant run set; the coordinator may assign that read-only
role to a helper. Share observations with head, run/attempt, and observation time
instead of starting duplicate polls. A changed head or rerun needs updated
evidence. The publisher still refreshes live gates immediately before acting.
Use [rate-limit recovery](github-troubleshooting.md#rate-limits) when throttled;
do not multiply retries across workers.

## Events and actual execution

- After draft → ready, inspect whether `ready_for_review` is a configured trigger.
  If it is, require the new run set even on the same SHA; group duplicate names by
  run ID/time. If it is not, do not wait for a nonexistent transition run, but
  disclose any heavy tests the draft condition skipped.
- A green lane with `continue-on-error`, draft gates, or conditional steps may not
  have tested the change. Verify relevant tests executed before citing that lane
  as coverage. Checks restricted to schedules/manual dispatch do not guard PRs.
- A downstream status can fail because its producer was label-gated or skipped.
  Establish that producer condition before proposing code changes; apply labels
  or rerun gates only within the authorized workflow and report permission limits.
- A green `workflow_dispatch` does not validate a job gated on `push` or another
  ref/event. After fixing an external prerequisite, rerun the qualifying event
  when authorized. Use a full rerun when an upstream artifact is required.
- After reruns, read `run_attempt`, latest job IDs (`jobs?filter=latest`), and logs
  for that attempt. Do not mix prior failures with carried-forward successful jobs.
- Changes to `GITHUB_TOKEN` merge automation must account for suppressed downstream
  push workflows. Verify the authorized deployment path on the actual merge SHA.
  Keep privileged `pull_request_target` listeners on trusted metadata/base code;
  do not execute contributor code with privileged credentials.

## Failure attribution

Read failed-job metadata, annotations, and nonempty logs before editing code.
Missing runners, failed dependency installation, precompile instability, or a
`gh-pages` non-fast-forward deploy collision may be environmental. Compare an
appropriate base run, tool/dependency versions, and execution phase; matching
manifests alone do not prove the PR cannot cause an install failure. One authorized
bounded rerun can test a suspected transient failure. Preserve a still-red required
check as a merge gate even when its likely cause is infrastructure.

For warning-only docs builds changed by the PR, compare relevant warnings with
base evidence when needed to establish a regression. Read final build logs rather
than intermediate-pass output. For a new strict gate, separate repository-owned
errors from third-party reachability; demonstrate any authorized suppression and
retain meaningful local validation. Never weaken CI solely to turn it green.
Validate workflow edits with `actionlint` when available; a YAML 1.1 parser can
interpret `on` as a Boolean and does not validate Actions semantics.

## Live merge requirements

Resolve the live `baseRefName`; URL-encode branch names in REST paths. Consult the
branch object, detailed protection when accessible, and applicable branch rules:

- `branches/<base>` exposes `protected` and summary protection.
- `branches/<base>/protection` may require Administration read access.
- `rules/branches/<base>` exposes applicable rules.

A detailed endpoint's 404 does not override `protected: true`. Report an exact
approval count/context only from a successful settings/rules response. A specific
plan-feature error can establish a plan limitation; generic 403 remains ambiguous.
Use live `reviewDecision`, merge state, threads, and checks without inventing gates.
`BLOCKED` can reflect unresolved conversations, not approval count; replies do not
resolve threads. For required code-owner review, inspect CODEOWNERS at the proper
ref and use its last matching rule to identify eligible owners.

When a review exception is requested, distinguish PR authorship from the actor
performing the merge. GitHub's classic `bypass_pull_request_allowances` applies to
the actor across PRs and can also bypass required PR creation. An author-only
request does not by itself authorize that broader allowance; explain the scope
and obtain authorization for it or use a mechanism matching the requested scope.
Preserve existing bypass entries and unrelated protections. Read back both the
exception and the required CI checks after an authorized settings change.

An aggregate `REVIEW_REQUIRED` or `BLOCKED` can remain after an actor-specific
review exception is configured. Establish its applicability from the live policy
and authenticated actor, not the aggregate label alone. The exception does not
waive CI or unresolved blocking feedback. For a client-only merge refusal after
these gates pass, follow [CLI troubleshooting](github-troubleshooting.md);
do not turn a review exception into a blanket admin bypass.

Stacked PR gates and CI branch filters depend on the current base. After a parent
merges, re-read siblings' bases: keeping the parent branch can leave them targeting
that branch. Retarget only within authorized scope and re-evaluate gates and event
coverage. `gh pr merge --auto` can merge immediately when nothing is enforced;
verify expected required contexts before enabling it.

For Pages runtime/build-source mismatches and published-content evidence, use
[gh-pages-deployment](../../gh-pages-deployment/SKILL.md); a successful custom
build does not validate a separate legacy Pages publisher.
