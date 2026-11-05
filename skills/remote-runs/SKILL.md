---
name: remote-runs
description: Prepare, launch, monitor, stop, resume, and retrieve experiment runs on external servers, including CPU-heavy Dantzig work and shared GPU hosts. Use existing project harnesses and preserve resource budgets and run evidence.
---

# Remote Runs

Manage the requested stage of a remote experiment using the project's existing
harness. Reading status does not authorize a restart; preparing a package does
not authorize launching its full experiment. A request to run a defined campaign
covers its ordinary preflight, bounded pilot, launch, and verification. Honor
existing authorization without asking again for each phase.

The bundled Linux [launcher](references/launcher.md) atomically allocates CPU
cores, GPUs and declared memory across participating projects and clients, and
supervises the full descendant tree. Use the host's established scheduler when
available; otherwise use this launcher or a verified equivalent with one common
host namespace. Idle checks and project-local locks alone cannot provide
exclusion. Jobs bypassing the common protocol remain outside its protection;
where the requested isolation exceeds that scope, keep dispatch pending.

## Establish the run and host

Resolve the project, SSH alias/account, remote checkout and run directory from
current configuration and project records before asking the user. Inspect the
existing launcher, status, stop/resume, and collection procedures. Reuse them
where they provide the needed guarantees; identify gaps before relying on them.
Keep authentication material and solver licenses outside packages and logs.

If the harness dispatches work through services or another scheduler, read
[service-harness integration](references/service-harnesses.md) before placing
the resource supervisor. Its claim must cover the actual workload descendants.

For Dantzig, read [the host reference](references/dantzig.md). For allocating CPU
or GPU resources, read [shared-host coordination](references/shared-hosts.md).
Read [launcher usage and recovery](references/launcher.md) before using or
deploying the bundled helper; it covers namespace permissions, persistent claims,
required runtime controls and conservative crash recovery.
These references distinguish observations from current policy; refresh live
state before a resource decision. Missing or failed probes mean unknown state,
not an idle host or a completed run.

Identify any existing run before making another one: recorded run ID, controller
or scheduler ID, process start identity, source/input hashes, effective resources,
logs, output location, and latest progress. A checkout-local lock prevents only
the launches that use that same lock; include other projects sharing the account
and relevant host activity in the resource budget.

## Prepare and launch

Make the run concrete before dispatch. Record these in the existing manifest or
a small run record alongside its evidence:

- Unique run ID, purpose, host/account, remote working/output directories, and
  requested timing regime (exploratory, shared-host throughput/comparison, or
  controlled benchmark).
- Source revision plus any dirty-source snapshot, input/configuration hashes,
  exact command/arguments, runtime and solver identities, seeds and case plan.
- Allocation/coordination mechanism; CPUs and physical-core/SMT mapping or GPUs;
  worker count, threads per worker/library/solver, memory and time budgets;
  relevant shared-host observations and their UTC timestamps.
- Controller/job identity and ownership (for Linux PIDs, boot ID and process
  start ticks), log/progress/exit paths, completion
  checks, stop/resume method, and intended local return location.

Freeze the executable source and inputs without discarding local changes. Use
the project's pinned checkout, Git bundle, or sealed archive, verifying hashes
after transfer. Avoid changing an active remote checkout beneath its workers.
Verify the environment actually loaded by the worker; a package version or Git
HEAD alone can miss a different import path, development package, or dirty tree.

Set the smallest resource plan that serves the task within its approved budget.
Preserve scientific choices such as cases, time limits, seeds, retry rules and
comparison regime. Do not change them to fit available capacity or a desired
deadline. A small preflight should exercise real dependencies and enforcement;
exclude pilot attempts from final results unless the experiment specifies
otherwise. Do not install or upgrade shared software as a launch side effect.

Immediately before dispatch, recheck capacity, conflicting runs, and duplicate
guards. Acquire the existing allocation/coordination mechanism, then recheck
occupancy where cooperative locks cannot exclude uncoordinated jobs. Keep the
allocation until the actual workload and its descendants have stopped.

Use the existing scheduler or tested detached supervisor. Record the returned
identity, then verify the worker's source, effective affinity, thread settings
and resource limits from inside the execution context. Verify logs and early
progress. An SSH return, printed PID or created output directory confirms neither
completion nor scientific success. Do not silently fall back to an unconstrained
launch when a required affinity, memory limit, or probe fails.

## Monitor, stop, and recover

Report process liveness, progress, process exit, result completeness, and scientific
acceptance separately. Resolve these against the run record and live state;
neither a missing finish marker nor a count of result files establishes liveness.
Use bounded polling appropriate to the run; keep the user informed without
promising monitoring beyond the active task.

If SSH drops or a launch response is ambiguous, reconnect and inspect the exact
run before retrying. A delayed controller may be waiting for resources, and may
finish while a replacement is being prepared. Reinspect immediately before any
replacement, resume, or stop.

For a requested stop, prefer the recorded scheduler job or verified run-specific
unit/cgroup. Otherwise verify current-user ownership, process start identity,
command/cwd and process-group/session membership, including separately detached
workers. A saved PID or PGID alone is insufficient because it can be reused.
Use a process-name-aware reader for Linux start ticks; whitespace-splitting
`/proc/<pid>/stat` can misread names containing spaces or parentheses. Establish
the verified descendant set before signaling, and do not terminate a sole
lock-holding supervisor before its workers can be stopped without losing their
allocation. Send TERM, allow a bounded grace period, and escalate only for
verified surviving members of that same run. Confirm descendant quiescence before
releasing guards or launching replacements. Never use broad process-name kills
or stop someone else's job to obtain capacity.

Use the experiment's validated resume procedure. Check source/input/resource
compatibility and validate completed records before reuse; retain interrupted
and failed attempts with their original identities. If resume semantics are
ambiguous, preserve the run and report the uncertainty. Do not infer that a
missing result authorizes unlimited retries. Bound recovery to the requested
cases and existing retry policy; repeated identical failure needs diagnosis
before another attempt.

## Retrieve and hand off

Collect the evidence needed for the requested stage within its authorized return
scope. Setup checks may need only explicitly allowlisted validation receipts.
Filename suffixes do not establish privacy: logs and manifests can contain input
records, commands, account paths or license identifiers. Reuse authorization for
an agreed payload/destination; do not silently broaden it.

Collect into a fresh local destination after confirming whether the run is
complete or the transfer is a partial snapshot. Retain raw logs, manifests,
resource observations, solver outcomes, failures and exit statuses. Verify
transfer hashes, expected case/seed coverage, duplicates and missing/partial
outputs. Distinguish files actually returned from files represented only by an
inventory, and disclose exclusions. If packaging provides a frozen auditor or
report entry point, run it against an extracted copy using its documented
environment before claiming the return is usable. A checksum proves transfer
integrity, not experiment validity.

Do not overwrite prior evidence, delete remote results, or publish artifacts as
part of retrieval. Keep timings from different contention/threading regimes
identifiable. Report what ran, current/final status, effective resources, any
contention or enforcement limitations, verified local artifact paths, and the
precise next step when work remains.
