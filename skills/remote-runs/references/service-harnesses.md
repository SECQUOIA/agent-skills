# Integrating a service-spawning experiment harness

Read when a controller delegates cases to systemd, a scheduler, containers, or
another service manager. A resource supervisor around that controller cannot
track sibling services started by the manager. The claim would outlive neither
their work nor the controller's failure, even if ordinary subprocess tests pass.

Place the shared helper inside the case's existing allocation:

```text
case service/cgroup -> shared helper -> scientific worker -> native descendants
```

Retain the project's manifests, case expansion, native-call limits and auditors.
Use its injectable command-runner seam where available. Keep its duplicate-run
guard as well as the common host resource namespace. Freeze a new adapter/profile;
do not rewrite an already measured campaign's source or evidence.

## Controls and identities

Run the helper with an interpreter that actually supports its pidfd/subreaper
requirements; execute the scientific worker with the project's pinned interpreter.
Record both identities and both helper-script hashes. Bind the worker to the
actual claim's run ID, nonce, boot/start identity and granted physical cores.
Replace hard-coded affinity assumptions with that verified grant, preserving
the agreed core/thread count. Do not widen affinity after admission.

The helper's `--threads` sets native-library/runtime environment variables. It
does not mean the solver-native thread count. Preserve distinct settings such as
single-thread BLAS with a separately declared multithreaded solver; setting both
to the solver count can silently change an established study.

Keep actual resident-memory/no-swap limits in the case cgroup and require the
helper to verify them. Its declared memory reservation also includes supervisor
overhead; include a separate controller's allowance in the aggregate plan.

## Clocks and shutdown

Keep submission, resource waiting, admitted work and cleanup clocks separate.
A preexisting experiment `started_at` may mean submission; retain that meaning
and add admitted-start evidence rather than relabeling historical fields.
Initialize per-case scientific deadlines and native-call ledgers after admission.
Queue waiting must not consume the declared scientific solve allowance or create
a fictional native-call attempt. Bound admission separately.

The service's hard ceiling must cover admission waiting, helper startup, bounded
scientific work, cancellation/reaping and receipt writing. Leave enough time
between the helper's soft deadline and the service's hard kill for cleanup and
durable quiescence evidence. A hard kill or OOM can legitimately leave a retained
claim; a dead unit is not permission to delete it. Abort subsequent dispatch when
either descendant quiescence or allocation release cannot be established.

## Logs and failure evidence

The helper captures its child's stdout/stderr. Join those paths, and any nested
scientific logs, into the project's existing manifests and parsers; service-client
output may contain only launcher messages. Preserve the scientific return code,
helper terminal state and cgroup outcome separately. Record the dispatch intent
and failure receipt even when the project runner raises before writing a result.
Admission failure is not solver failure or successful experiment completion.

Validate the adapter with refused admission, conflicting/SMT claims, thread and
memory mismatches, delayed admission, detached descendants, interruption, missing
receipts and scientific-log collection. Test the intended SSH/disconnect regime
separately: correct process ownership and persistent claims do not make the user
manager survive last-login teardown. Keep native dependency smoke attempts
separate from the measured scientific matrix.
