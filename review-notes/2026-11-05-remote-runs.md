# Remote-runs review and implementation, 2026-11-05

The first `remote-runs` draft was independently reviewed by the requested Astra
subagent and by Claude and Gemini through the installed Antigravity CLI. Review
covered the installed instructions and three separately supplied MIT GPU design
inputs. The GPU scripts are not installed with this skill. The executable
implementation added after that review is described below.

## Evidence and limits

The frozen seven-file source manifest had SHA-256
`896140fac8aafb8f240542f151938d7b37a59f807ec939ace25f09248230e416`.
Raw reports and client traces remain local; only this reviewed summary belongs
in the shared repository.

| Reviewer/check | Observed evidence | Limit |
| --- | --- | --- |
| Astra | Subagent requested as `gpt-6-astra`, high effort; read the seven frozen files, matched their hashes, resolved references, and checked shell syntax; reviewed the instruction revisions | The subagent did not expose an authoritative runtime model ID. Selection is supported by the coordinator's spawn record, not inferred from the review's name. No workload execution. |
| Claude Code 2.1.292 | Native initialization listed `remote-runs` as a skill and slash command | Its configured account returned `usage_limit_reached` before inference. Direct client execution of the skill was not verified. |
| Claude review through Antigravity | Requested `claude-opus-4-6-thinking`; backend log selected `Claude Opus 4.6 (Thinking)`; completed a static review from embedded source contents | This is a Claude model review through Antigravity, not a completed Claude Code review. |
| Antigravity/Gemini | Requested `gemini-4-argon-high`; backend log selected `Gemini 4 Argon (High)`; completed a static review from embedded source contents | Planning-mode shell requests stopped earlier attempts; embedding the files allowed the review to complete. No remote execution. |
| Antigravity discovery | Native client discovered the installed symlink, read `SKILL.md`, and read both supporting references | Skill loading is verified. SSH authorization, detached survival and exclusive allocation were not tested by this review. |

## Incorporated findings

- Make the absence of a bundled allocator/supervisor explicit in the entrypoint.
  A resource snapshot and separate project locks cannot close simultaneous
  cross-project admission races. Where the user requires nonoverlap, leave
  dispatch pending until a mechanism with that scope is available.
- Distinguish observations, common atomic locks for participating launches, and
  configured enforced allocations. Require physical-core/SMT identity and one
  maintained namespace across participating clients/projects. Cover compute-heavy
  pilots and preflights, not just the final campaign.
- Give an operational fallback when persistence of Dantzig user services is
  unverified. Attached execution can be used where the task permits reliance on
  a live connection; otherwise a required disconnect-safe run remains pending.
  Do not change linger or assume terminal detachment defeats login/cgroup policy.
- Clarify process-name-aware start-time reading, descendant identification before
  cancellation, retention of the allocation during worker shutdown, solver-native
  thread settings, and effective cgroup v2 limit inspection.
- Make the GPU provenance paragraph self-contained. The original probe can fail
  open, the wrapper can lose locks while children survive, and duplicate device
  IDs or per-lock waits need validation. These are input-script defects; no CPU
  helper carrying them is shipped by this skill.

## Recommendations not adopted

An extra occupancy sample or shared-readable manifest does not create atomic
exclusion. Neither is presented as a fix for the admission race. A future shared
launcher needs an actual allocation primitive, a validated lifetime model and
concurrent-launch/failure tests before deployment; implementing that host service
is separate from this instruction review.

Closing all child lock descriptors is not a universal solution to lifetime
problems. Blind whitespace extraction of `/proc/<pid>/stat` is unsafe for process
names containing spaces/parentheses. Terminal multiplexers and `nohup` are not
universal guarantees against logout policy. Those proposed shortcuts were rejected.

The OpenAI sidecar already contains supported optional UI metadata; it needs no
invented tool-binding or `instructions_file` schema. Host observations remain
dated and are refreshed before resource decisions; a seven-day TTL would weaken
that rule. An exhaustive catalog of every solver's thread controls is unnecessary.

One reviewer asserted that Antigravity cannot expose custom slash commands.
Current [Antigravity skill documentation](https://antigravity.google/docs/skills?app=cli)
describes `/skill-name` invocation and CLI slash-command conversion. That claim
was not adopted. [Claude Code documentation](https://code.claude.com/docs/en/skills)
also documents `/skill-name` invocation and the personal skill directory used here.

## Validation and remaining work

The revision retains the existing lifecycle and host-specific references and adds
decision case c054 for simultaneous cross-project admission with separate locks.
The skill-creator validator, public metadata/local-link validator, and all 221
repository tests passed on the revised candidate. Astra's final delta review
reported no actionable residual findings. These checks and static reviews do
not prove a live exclusion or supervision mechanism. Dantzig still has no newly
deployed common CPU allocator; the revised skill must report that limitation
rather than promise it.

## Executable implementation follow-up

The submitted skill now bundles `scripts/remote_run.py` and
`scripts/resource_probe.py`, with usage and recovery in
`references/launcher.md`. The new code replaces the role of the original GPU
helpers without importing their host paths, defective-device exceptions or
failure behavior.

- One stable admission gate publishes atomic durable claims for normalized
  physical CPU cores, GPU UUIDs and declared memory. Participating projects and
  clients share one explicit host-bound namespace; a trusted group can share it
  across Unix accounts.
- CPU/GPU probes fail closed on missing, malformed, inconsistent or timed-out
  observations. Multiple resources have one admission deadline. A gated worker
  verifies affinity, native thread settings and required cgroup limits before
  user code starts. Memory accounting is a reservation, with hard-limit checks
  explicitly requested and verified rather than silently assumed.
- A Linux subreaper waits for the kernel's complete descendant-tree quiescence,
  including detached children. Cancellation uses pidfds plus fresh ancestry and
  start identity. Supervisor SIGKILL retains the durable claim, independently of
  worker descriptor inheritance. Recovery requires a matching quiescence receipt
  or evidence of a different host boot.

Astra independently reviewed the frozen implementation and reproduced two
residual cancellation defects: arbitrary non-UTF8 process-name bytes broke the
ancestry reader, and TERM did not interrupt waiting for the admission gate.
The reader now parses raw bytes, and gate acquisition checks cancellation before
each attempt and after acquisition. Cleanup gate acquisition remains independent
of cancellation. Both reproductions passed after correction; the final delta
review found no actionable residual findings.

The requested Claude/Antigravity follow-up reviews of the much larger executable
snapshot timed out after five minutes without producing review output. They are
not counted as completed executable reviews. The earlier completed instruction
and client-discovery reviews remain scoped to their original snapshots.

### Final verification

- `/usr/bin/python3 -B -m unittest discover -s tests`: **282 tests passed** on
  Python 3.12.3, including all **28** real lifecycle tests and **33** resource-probe
  tests; the Linux lifecycle tests executed rather than being skipped.
- The skill-creator validator, public metadata/local-link validator, and
  `git diff --check` passed; `bash -n install.sh uninstall.sh` passed.
- An isolated Dantzig smoke on system Python **3.9.25** passed eight checks:
  namespace initialization, detached-descendant release, competing same-core
  refusal, cancellation with a verified non-UTF8 process name, TERM during gate
  contention, failed GPU driver refusal, SIGKILL claim retention/conservative
  recovery, and retained-reservation status. Only tiny sleeping Python processes
  and a private test namespace were used. An earlier short-sample attempt refused
  startup under transient activity; the final run used the normal sample interval
  and retained the same strict occupancy threshold.

The final tested runtime hashes are:

| File | SHA-256 |
| --- | --- |
| `remote_run.py` | `c57a2fd482d6a62200fa5c670e11580694c701f955b25516ac114a5a57a46c88` |
| `resource_probe.py` | `2df61243b8123f4fa263b2afdfac2bfe529803051153e4bc08a14e78f1087c90` |

This verifies the private host test and cooperating-launch behavior, not exclusion
of jobs bypassing the protocol, an actual GPU-hardware campaign, or production
deployment of a cross-user namespace. Persistent claims prevent unsafe resource
reuse after a crash; they do not make processes immune to host/logout policy.
