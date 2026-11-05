# Dantzig

Read for Dantzig runs. This is an evidence-backed starting point, not a standing
allocation or permission to launch work. Resolve the requesting user's configured
SSH alias/account and project paths; do not copy another researcher's account,
environment or scratch directory from an old command.

## Host observations

A read-only SSH inspection on **2026-11-05 at 16:02 UTC** found:

- 48 physical cores, 96 logical CPUs, one socket and one reported NUMA node. The
  inspection's affinity allowed logical CPUs 0–95. SMT siblings mapped `i` and
  `i+48`; rediscover topology rather than computing future selections from this.
- Total RAM 1,068,149,796,864 bytes (about 995 GiB). Available RAM, disk and load
  are transient and must be refreshed for each launch. A 2026-11-04 project
  hardware receipt identified an AMD EPYC 7643.
- `taskset`, `flock` and `systemd-run` available. Slurm/PBS commands (`sbatch`,
  `squeue`, `srun`, `qsub`, `qstat`) absent from the inspected account's PATH;
  the queried usual Slurm/PBS services were inactive. This supports direct-host
  operation observed in the projects, not a claim that no scheduler or other
  site policy can exist. `numactl` was absent from this PATH.
- The user systemd manager answered but reported `degraded`; `Linger=no`.
  Verify required resource controls and survival after SSH/logout for the chosen
  supervisor. Availability of `systemd-run` alone does not establish either.

If user-manager persistence is unverified, do not promise that transient user
units survive the last login session. Use a verified persistent host supervisor,
or retain tested attached execution when the task permits dependence on a live
connection and disclose that dependency. If disconnect survival is required and
unavailable, prepare the run and keep dispatch pending. `nohup`, `setsid` or a
terminal multiplexer alone does not prove survival of the relevant login/cgroup
policy. Changing linger or site services remains separate host configuration.

Do not infer an idle CPU allowance from these machine totals. No established
cross-user CPU-lock namespace was demonstrated by the inspected projects.
Existing local locks protect particular controllers/phases, not all Dantzig work.
For new direct-host work, use the [bundled launcher](launcher.md) or the site's
verified equivalent. Resolve one common account-wide or trusted-group namespace
before starting participating projects; do not create a fresh namespace per run.
The helper's availability in the skill does not establish that a host-wide
namespace has been provisioned or adopted by other users.

Before provisioning a new account-local deployment, check the requesting
account's `~/.config/secquoia-remote-runs/host.json` when present. A deployment
profile records the common namespace, pinned helper/probe hashes, capable helper
interpreter, aggregate memory accounting budget and execution/persistence mode.
Verify that binding and the live namespace instead of inventing a new per-project
state directory. Its presence establishes neither adoption by other accounts nor
exclusive host allocation. Keep account-specific absolute paths and raw host/run
records private; resolve them from the current account rather than copying them
from another project's deployment.

A later implementation check on 2026-11-05 found system `/usr/bin/python3` at
3.9.25 with both `os.pidfd_open` and `signal.pidfd_send_signal`. The inspected
account's Python 3.11.14 build lacked both APIs. Use the verified system
interpreter for the helper and retain the project's own interpreter in its
wrapped command. Verify those capabilities before deployment; version alone is
insufficient. Do not install another runtime as an implicit launch step.

## Reuse the project harness

Local project records provide the operational evidence below. Paths are relative
to each named repository; consult the current checkout and remote run record.
Historical evidence is useful when a launcher has since moved or disappeared.

| Project evidence | Reusable behavior | Limits of the evidence |
| --- | --- | --- |
| `qubo-preprocessing-benchmarks`: `results/codex-campaign-2026-11-03/full-watch/initial/controller.sh.txt` and its frozen plan | Retained controller identity; source/runtime/package-tree verification; duplicate-controller guard; explicit cohort plan; bounded process-group cleanup and retained failures | Its load-based capacity gate estimates headroom. It does not reserve selected cores; no per-worker memory cap was established by this controller. |
| `RBFopt_Test`: `experiments/dsda_grid_target_stop/README.md` and `launch.py` | Sealed inputs/source; distinct smoke/full phases; detached controller with recorded paths; validated resume; checksummed return | A PID proves dispatch only. Check the actual launcher for descendant cleanup, duplicate guards and current resources. |
| `RBFopt_Test`: `cpu_affinity.py`, `docs/dantzig_cpu_rerun.md` | Allowed-CPU validation; physical-core/SMT identity; explicit native thread counts | Earlier campaigns overlapped on CPU 0 and required replacement timings. CPU 0/2/4 assignments from that rerun are not current reservations. |
| `RBFopt_Test`: `results/pr56_dantzig_return_20261031/README.md` | Six physical-core workers, one-thread libraries, returned evidence verification | That campaign's concurrency was not a global host limit. Exit status, solver outcome and completeness remain separate checks. |
| `Reproducible_state_task_network_problem`: `docs/DANTZIG_PARALLEL6.md`, `scripts/dantzig_preflight.py` | Per-worker systemd scopes, affinity, effective child cgroup verification, source/input provenance | Six workers, 4 GiB per worker, no swap, idle thresholds and a separate 24-thread authorization were study-specific. Do not import those numbers as defaults. |

Other RBFopt launchers use different concurrency, retry and affinity practices.
Review the actual harness rather than assuming every project has the strongest
controls above. In particular, a missing final marker can describe a dead run,
and counting output files does not validate optimizer success.

For QUBO monitoring, inspect the existing controller again before replacing a
capacity-waiting run: one recorded campaign completed while a lower-concurrency
replacement was being considered. A new SSH session or a gap in logs is not
evidence that the old controller needs relaunching.

## Before a Dantzig dispatch

1. Inspect the current run/controller and other relevant jobs, including other
   projects under the same account. Read current site/project instructions.
2. Discover topology and effective affinity, sample relevant physical cores/SMT
   siblings, and refresh memory/disk/load observations. Record a timestamp.
3. Choose the task's approved workers, native-thread settings and memory/time
   budget. Preserve existing experiment design; do not inherit six, sixteen or
   twenty-four workers/threads from unrelated projects.
4. Use the project's pinned snapshot/environment and duplicate guard. Check the
   chosen supervisor's effective limits, reconnect behavior and descendant cleanup.
   Keep direct-host runs explicitly identified as such; affinity is not a host
   reservation.
5. Verify early progress after launch and retain exact identities for status,
   bounded cancellation, validated recovery, and checksum-verified collection.

Read-only inspection to maintain this reference is distinct from changing host
coordination. Installing a common CPU wrapper, provisioning shared locks, changing
linger/system services or updating other users' project instructions is separate
work; this skill does not silently deploy such changes.
