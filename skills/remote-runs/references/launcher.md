# Shared Linux launcher

Use the bundled [remote_run.py](../scripts/remote_run.py) and its sibling
[resource_probe.py](../scripts/resource_probe.py) when the host has no suitable
scheduler or shared launcher. They use Python 3.9+ and Linux subreaper/pidfd
facilities. Run them on the compute host; a local macOS/Windows client can invoke
them over SSH. Keep both files together in a pinned, trusted helper directory.
Codex, Claude Code and Antigravity use the same executable and namespace.

## Scope and initialization

The helper serializes admission through one stable `flock` gate, then atomically
records a persistent claim for all requested resources. CPU identities represent
physical cores, so requests for SMT siblings conflict. GPU identities use driver
UUIDs. Declared memory is accounted for in the same transaction. Multiple
resources are acquired together; there is no partially acquired GPU/core set.

Every participating project must use the **same absolute state directory on the
same host**. Separate checkouts, cloned helpers or different clients do not create
different allocations when they use that namespace. Independent namespaces do
not coordinate. The namespace is host-bound; do not reuse it across machines.

Initialize once with an explicitly agreed memory budget. These example values
are illustrative, not a Dantzig allocation:

```bash
PYTHON=/absolute/verified/python3
RUNNER=/absolute/trusted/bin/remote_run.py
STATE=/absolute/persistent/path/compute-claims
"$PYTHON" "$RUNNER" init --state-dir "$STATE" --memory-budget-mib 16384
```

The default namespace is private to one Unix account and coordinates that
account's projects. Cross-user coordination requires a prearranged trusted Unix
group and common path:

```bash
"$PYTHON" "$RUNNER" init --state-dir "$STATE" --memory-budget-mib 16384 \
  --group trusted-compute-group
```

Use an authorized group and parent directory; do not invent group membership,
change site services, or alter other users' projects. The helper creates its own
namespace with restrictive user/group permissions; it does not repair arbitrary
existing directories. The directory must not be sticky. Keep claims on persistent
host storage, not ephemeral temporary storage, so a supervisor failure cannot
erase reservations. Never remove/recreate the admission lock or delete a claim
because its recorded PID is dead. Group members are trusted participants, not
security-isolated tenants.

## Run a project command

Keep the project's cases, seeds, solver settings, limits and evidence procedures.
Wrap the process whose actual descendants perform the allocated work. When a
controller dispatches sibling services, use [service-harness integration](service-harnesses.md)
to put the helper inside each allocation; do not replace the experiment logic.

```bash
"$PYTHON" "$RUNNER" run --state-dir "$STATE" --cores 4 --threads 1 \
  --memory-mib 8192 --time-limit 7200 --wait 600 \
  --run-dir /absolute/new/run-directory -- \
  /absolute/project/environment/bin/python /absolute/project/run_study.py
```

`--cores` selects allowed, idle and unclaimed physical cores. `--cpus` instead
selects an explicit logical CPU list; it still reserves each whole physical core.
The runner applies the selected affinity to the command and its ordinary
descendants and sets common native-library/runtime thread variables. Set
solver-native thread parameters in the project command as well. A command that
widens affinity, hands work to another service, or otherwise bypasses the protocol
falls outside this cooperative guarantee.

`--memory-mib` is a declared reservation against the namespace budget, not a hard
resident-memory cap. For a required cap, run under an already verified cgroup
mechanism and add `--require-memory-cap`; add `--require-no-swap` when required.
The worker checks its actual effective cgroup limits before starting user code.
Unknown, unsupported, unlimited or insufficient required controls block startup.
Do not silently fall back to unrestricted memory. Include supervisor overhead in
the chosen cap and keep the regime consistent with the study.

GPU runs additionally select physical device indexes, for example `--gpus 2,4`.
All driver queries and response validation must succeed. Compute-process presence,
excess utilization or excess allocated device memory blocks dispatch. The idle
device-memory allowance defaults to zero; a nonzero
`--max-gpu-memory-mib` needs a verified idle baseline for that host. Device roles,
thermal defects and scratch exceptions come from its profile; none are built in.
CPU-only work never requires `nvidia-smi`.

`--wait` is one overall admission deadline, not a fresh timeout per resource.
Without it the runner fails promptly when resources are unavailable. Runtime
`--time-limit` and cancellation `--kill-grace` are separate bounds. Admission also
applies to resource-consuming pilots/preflights; the launcher performs its own
lightweight probes before project work starts.

The private run directory contains the run identity, effective resource evidence,
logs and terminal/quiescence receipts. Existing evidence directories are not
overwritten. Avoid credentials in command-line arguments or recorded paths; pass
authentication through the host's existing secret mechanisms. Shared claims omit
full argument lists and environment dumps.

## Status, cancellation and recovery

```bash
"$PYTHON" "$RUNNER" status --state-dir "$STATE"
"$PYTHON" "$RUNNER" stop --state-dir "$STATE" --run-id RUN_ID
"$PYTHON" "$RUNNER" recover --state-dir "$STATE" --run-id RUN_ID
```

The runner becomes a Linux child subreaper and retains the claim until the kernel
reports no remaining children. Main-command exit alone is insufficient: detached
and double-forked descendants still count. Timeout/TERM/INT trigger bounded
identity-checked descendant termination through pidfds, then reaping. It retains
the allocation while shutdown is incomplete. Exit receipts distinguish command
failure, timeout, cancellation and completed cleanup.

If the supervisor is SIGKILLed, its persistent claim remains even if every worker
closed inherited file descriptors. Later cooperating launches cannot reuse those
resources. `status` reports a dead/unknown supervisor with a retained reservation;
it does not call that run complete or its resources free. `stop` signals only a
matching current-user supervisor identified by boot ID/start time, never a reused
PID or an unrelated job.

`recover` releases a dead supervisor's claim only with a matching durable
quiescence receipt or proof that the host rebooted since the claim. A same-boot
crash without such proof stays reserved for operator investigation. There is no
automatic liveness-only reclamation or unsafe force-release switch. This favors
preventing overlap over reclaiming capacity whose worker state is uncertain.

## Remaining host boundaries

The helper prevents conflicting claims among participants; it cannot exclude a
job that bypasses it, prevent a user from changing their own affinity, reserve
memory bandwidth/cache, or defeat administrator/login policy. Use enforced host
allocation where those guarantees are required. Occupancy probes remain current
observations about uncoordinated work, not durable reservations against it.

Persistent claims prevent resource reuse after supervisor death; they do not make
a process immune to logout or host failure. Use a verified persistent supervisor
or keep the SSH session attached when the task permits that dependency. Do not
enable linger or change system services as an implicit deployment step.
