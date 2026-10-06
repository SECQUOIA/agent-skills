# Optional delegation and concurrent work

Read before delegating part of a workflow or coordinating with another agent on
the same target. For solo work, execute the owning skill normally: no worker
records, role setup, or extra approvals are required. Use helpers when useful and
within the user's scope; honor a request to work alone. If helpers are unavailable,
continue sequentially where consistent with the request and disclose any explicitly
requested delegation that could not be supplied.

## Assign a bounded task

The coordinator is the agent responsible for the user's overall task. It retains
scope decisions, integration, and workflow completion. Split independent work;
keep dependent phases ordered. Calling a component skill is ordinary composition,
not a requirement to spawn an agent or delegate its entire workflow.

Give each worker a concise assignment with the following information as relevant;
ordinary messages suffice, without a required schema or new tracking service:

| Assignment | What the worker needs |
|---|---|
| Target and evidence | Verified repository, issue/PR, pinned base/head or source tree, and the concrete question or change |
| Authority | User limits, allowed reads/execution/local edits, permitted paths, and any explicitly authorized external surface |
| Resources | Absolute working directory, owned branch/ref and artifacts, shared environment/output restrictions, and integration owner |
| Completion | Expected findings or patch, checks/evidence, dependencies, stopping conditions, and remaining relevant workflow budget |

Load the owning skill and applicable references in the worker's context; do not
assume it inherited every decision. The assignment narrows the skill's ordinary
full-workflow authority. An inspection worker using `gh-review-pr` returns findings,
not a posted review. A local implementation worker using `gh-issue-to-pr` returns
changes and evidence, not a pushed branch or PR. Do not invent remote results to
satisfy a later phase. Return pending actions to the coordinator, and resume a
dependent phase only after the required real result has been verified.

Nested workers inherit the same limits and respect existing resource ownership;
assign mutable resources before re-delegating. Stay within the assignment and
available capacity; re-delegation does not reset budgets or
create another integration/publication owner. Send later user scope changes,
target changes, and cancellation to affected workers before relying on their work.

## Own mutable resources

For parallel edits, prefer separate worktrees/branches at the agreed source using
[checkout guidance](worktrees-and-checkouts.md). Each worker owns its local edits;
the coordinator integrates them. If intentionally sharing a checkout, assign
nonoverlapping paths and one owner of its index, branch changes, and commits.
Different files still share Git state: never switch/rebase that checkout or stage
another worker's in-progress files while workers use it. Stop and repartition an
unexpected overlap rather than overwriting or reverting another worker's work.

Separate worktrees can still share Git refs, package environments, services, and
generated-output paths. Isolate or serialize mutations of those resources too;
do not replace another worker's editable install or refresh a shared ref it is
using as immutable evidence. Pin source SHAs rather than relying on `FETCH_HEAD`.

For each external target/surface, the coordinator is the default sole publisher.
A user-authorized worker may take that role only through an explicit, acknowledged
ownership handoff; the old owner stops writing that surface. An intermediate
parent or another session does not become a second publisher automatically.
When a competing invocation is known or detected, agree on one owner or leave
publication pending while continuing independent preparation. Do not use a new
GitHub comment as an improvised lock. Existing sentinels are duplicate checks,
not atomic claims: two agents can both read absence before either writes.
Apply [preflight and readback](github-writes.md) at the actual write, including
available head-match conditions; ownership does not freeze remote state.

## Return evidence and integrate

Workers report completion of their assignment, not of the overall workflow.
Return the task identity and scope, complete/partial/blocked status, source
revision, actual changes or findings, and remaining gates. For edits include the
retained commit(s) or patch and base, changed paths, and artifact locations. For
checks include the command, outcome, tested tree/patch and environment identity,
and limitations. Distinguish proposed, performed, and verified external actions.
A read-only finding needs no invented commit or test result.

Before integration, verify the returned scope and source identity, inspect the
actual patch, and ensure relevant writers and their commands are quiescent. Keep
worker results recoverable while integrating deliberately; do not copy whole
stale files over newer work. Preserve both results on conflicts. Abort only an
integration operation this task started when safe resolution is unavailable.
Do not treat duplicate delivery as a second patch or another publication.

If the base/head, assignment, or relevant environment changed, assess the delta
before accepting a late result. Reuse unaffected evidence with its basis; refresh
affected checks and all required live gates. Verify the combined implementation
where workers' changes interact: passing component checks alone need not establish
the combined contract. A different agent is not required for independent checking,
and another agent on the same account does not provide a human/peer approval.

## Failure, cancellation, and continuation

Wait for required dependencies before declaring completion. A failed or timed-out
worker can leave useful partial work; inspect and preserve it, report the missing
part, and continue independent tasks. Request cancellation when needed, then
confirm the worker and its owned commands have stopped before reassigning its
writable scope, changing its tree, or deleting artifacts. Acknowledging a message
or interrupting a turn does not prove background commands stopped. Reconcile any
dispatched external write through readback before retrying or replacing its owner.
If quiescence cannot be established, retain that workspace and use a new isolated
one for independent work; do not consume or publish its unfinished result.

For delegated work that spans turns or may resume elsewhere, retain a concise
checkpoint in existing task history or a task-owned local artifact: assignments,
owners, source refs, completed/active work, result locations, pending writes, and
consumed workflow budgets. Do not commit private coordination records or publish
them as status comments by default. On continuation, refresh live state and
recover existing counts rather than restarting them per worker; preserve the
owning skill's stop rule if required history is unavailable. No checkpoint file
or multiagent infrastructure is required for an ordinary solo run.
