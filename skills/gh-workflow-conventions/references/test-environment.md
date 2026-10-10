# Verification Environment

Use when selecting or recording an execution environment. For a concrete setup
failure, load [environment troubleshooting](environment-troubleshooting.md).

Use the repository's documented commands, dependency profile, runtime, tool
versions, and flags. Select an existing suitable project environment before
installing anything; optional-backend, docs, and benchmark environments may differ.
Do not mutate a shared/base installation to make a check pass. If setup is needed,
prefer an isolated scratch environment and already-compatible local caches.

Pin the working directory/project to an absolute path. Verify the selected
interpreter, imported source, native build identity, and relevant subprocess PATH
when those determine the result; [worktree guidance](worktrees-and-checkouts.md)
covers source contamination. Preserve the same environment when a command needs
additional permissions. Scope any install/cache writes and avoid installer changes
to shell profiles; inspect and undo only side effects created by the task.

Bound local work that can exhaust a shared machine — proof checkers and builds,
dense simulations, solvers, enumerations — with an operating-system limit, not
only a timeout. Prefer a resident-memory limit with swap disabled (for example a
`systemd-run --user --scope -p MemoryMax=… -p MemorySwapMax=0` scope) over a
virtual-address limit, which some toolchains exceed at startup; choose caps for
the machine and keep concurrent capped jobs within its memory. Apply the limit to
every invocation of such a tool, including quick probes and auxiliary binaries.
An unfamiliar flag such as `--help` may start real work, and an uncapped process
can outlive a killed session; read the tool's documentation or source instead of
running it to learn its interface.

A local result supports CI parity only when relevant runtime/tool versions,
dependencies, and invocation flags match. For floating CI versions, resolve what
that run installed before rewriting files with a local formatter. Do not change
configuration just to reconcile an older local tool with CI. An environment that
claims a lock can still drift; compare a failing check against appropriate clean
source before attributing it to the PR, and rebuild a disposable environment from
the lock instead of rewriting user manifests to accommodate contamination.

Capture long-running output unfiltered to a log when practical; filter at read
time. Preserve the process exit status, failure detail, and actual summary. Report
counts only from captured output, scoped to the exact command and selected cohort.
Record source SHA/tree, environment, command, and material limitations so the next
workflow can reuse valid evidence. A changed SHA alone does not require repeating
all tests when the relevant behavior and environment are demonstrably unchanged;
CI/merge evidence must still meet its live exact-head contract.

Permission failures before a check starts are environment-blocked attempts, not
failed tests. Use only supported, authorized escalation; if unavailable, report the
specific verification gap. Do not replace the intended check with a weaker one and
label it equivalent. Existing paid/live-service evidence remains tied to its
original revision; a new fixture test does not make it current-head live evidence.
