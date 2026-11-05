# Shared-host coordination

Read when choosing or checking a run's resources. Prefer the host's established
scheduler/allocation protocol. A resource snapshot guides admission decisions;
it is not an exclusive reservation.

## What prevents overlap

Two clients can both observe an idle core and then launch onto it. Sampling,
affinity and per-project duplicate guards do not close this admission race.

| Mechanism | What it establishes | Scope to verify |
| --- | --- | --- |
| Current occupancy checks and affinity | Evidence about activity and placement | Other jobs can start after the check or share an SMT sibling. |
| Common atomic resource locks | Cooperating launches cannot hold the same resource concurrently | Every participating client/project uses the same remote namespace and physical-core/device identities; jobs bypassing the protocol remain outside it. |
| Enforced scheduler or administrator-managed CPU allocation | Disjoint resources within the configured enforcement domain | Verify actual granted exclusivity, binding and enforcement; the presence of a scheduler or cgroup alone is insufficient. |

Use the [bundled launcher](launcher.md) or a verified equivalent at one maintained
host location with a common namespace; independently copied project locks do not
coordinate. Its persistent claims survive supervisor death, and its subreaper
waits for the descendant tree before normal release. Verify the chosen host
setup with an isolated smoke check before real work. Apply admission to
resource-consuming pilots and preflights as well as the final campaign. Installing
the skill in several clients does not provision a common remote namespace. If the
requested exclusion exceeds the mechanism's scope, keep the launch pending and
explain the missing guarantee.

## CPU and memory

Discover online CPUs, effective allowed affinity/cpuset, socket/core IDs, SMT
siblings and NUMA topology. Intersect online and allowed CPUs when selecting
placement. For physical-core timing isolation, account for every online SMT
sibling, including siblings outside this process's allowed set. Unknown topology
or hidden occupancy cannot support a claim that a core is uncontended.

Budget concurrent workers times each worker's actual native thread demand,
including solver, BLAS/OpenMP and language-runtime threads or subprocesses that
can run simultaneously. A one-worker Python/Julia command can create many native
threads. Use explicit application settings and relevant variables such as
`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`,
`NUMEXPR_NUM_THREADS` and `JULIA_NUM_THREADS`; verify actual behavior. Do not set
every layer to the full host CPU count. Existing one-thread study designs remain
one-thread unless the requested experiment changes them.

Set solver-native thread parameters as well; numerical-library variables do not
cap every solver. Check live runnable thread/process activity under representative
load; merely counting all threads also includes idle runtime helper threads.

Budget peak aggregate worker memory, controller/build overhead and host headroom;
check the effective cgroup limits and current `MemAvailable`. Include disk space
for intermediate solver files, results, archives and extraction. A cgroup memory
cap bounds consumption; it does not reserve that memory or prevent host pressure.
Do not introduce swap policy or hard caps that change a study without recording
and validating that regime. Where memory caps are required, verify the child
cgroup's actual limits rather than trusting launcher arguments. See
[systemd resource controls](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html).

On cgroup v2, resolve the worker's actual unified cgroup from `/proc/<pid>/cgroup`
and inspect its `memory.max`, `memory.swap.max`, `cpuset.cpus.effective` and
applicable ancestor limits. Treat `max` as unlimited and an absent/unsupported
control as unverified; do not guess a cgroup path from a unit name.

With a scheduler, request CPUs, RAM, wall time and binding through the host's
configuration and inspect the granted allocation. Slurm's CPU identifiers and
sharing/exclusivity behavior depend on its configuration; do not equate hardware
CPU numbering with the scheduler's abstract IDs. See the
[Slurm CPU guide](https://slurm.schedmd.com/cpu_management.html).

Without a scheduler, use existing agreed host limits and coordination when
available, plus per-run duplicate guards, explicit concurrency, placement and
fresh occupancy/memory checks. Load average alone does not identify idle physical
cores. For core-sensitive measurements, sample per-CPU activity over an interval
and inspect SMT siblings and other relevant jobs. CPU affinity controls placement;
it does not reserve cores, shared cache, memory bandwidth or the whole host.

Shared-host throughput runs can be appropriate within the requested budget;
record their contention regime. Controlled timing claims require the intended
conditions to be established and monitored. If they cannot be established, report
the limitation and obtain a suitable window/allocation or an explicitly accepted
shared-host design before changing the requested benchmark. A scratch run with
wall-time stopping rules can change outcomes under contention even if no runtime
is reported.

## Cooperative locks

Use one agreed namespace and resource granularity across participating projects
and users. For CPU-core locks, all SMT siblings of a physical core must refer to
the same resource. Independent lock directories or per-logical-CPU locks do not
prevent physical-core overlap. CPU locks do not allocate RAM or isolate NUMA/cache
traffic; those still need a budget and appropriate measurement conditions.

Validate/deduplicate resource IDs and acquire multiple locks in a deterministic
order, with a defined overall waiting deadline or explicit nonblocking mode.
Keep lock-file inodes stable: never delete/recreate an active or apparently stale
lock file. Owner records are advisory; a dead recorded PID does not prove a
resource is available. Use the lock state and actual workload state.

The supervisor must retain resource ownership until all work ends, including
timeout/cancellation paths. Inherited descriptors can retain locks after a
controller exits; closing them in workers can release locks too early if the
controller dies while workers survive. Inspect the supervision model instead of
assuming either descriptor pattern is universally safe. These lifetime rules
follow [Linux flock semantics](https://man7.org/linux/man-pages/man2/flock.2.html).

For a new cross-user protocol, agree ownership, permissions, trusted helpers,
filesystem semantics and rollout before using it as host-wide coordination.
Sticky shared locations such as `/tmp` or `/dev/shm` can prevent reopening
another user's lock under `fs.protected_regular`; private per-run locks are a
different case. Do not create a world-writable shared service or alter other
projects' agent files merely to run one experiment.

## GPU extension

Use a verified host profile for physical device IDs/UUIDs, benchmark versus
scratch roles, exclusions and the installed wrapper/lock paths. After allocation,
check the actual device's processes/utilization with successful, well-formed
driver queries. Probe failure means unknown occupancy. Set and verify the
worker's visibility/mapping; its CUDA index can differ from the physical ID.
Keep CPU and RAM budgets even for a GPU job.

The MIT GPU protocol that informed this skill illustrates per-device locks,
advisory ownership, post-lock occupancy checks and a separate scratch role. Its
GPU 5 cooling defect, device assignments and `/data/workspace/gpu-locks` paths are
host-specific examples. Its original shell helpers are not distributed with this
skill or validated as implementations of these requirements: their driver-probe
failure handling and supervisor-death behavior need correction before reuse.
Do not import their device exceptions or treat them as portable CPU launchers.
