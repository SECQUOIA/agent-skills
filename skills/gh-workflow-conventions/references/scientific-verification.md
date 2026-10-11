# Scientific and Numerical Verification

Use for changed scientific contracts, reported quantitative results, solver claims,
and requested benchmark work. Scope the audit to changed equations and relevant
call paths; generic code changes do not require a scientific audit.

## Equations, units, and independent checks

Trace input, intermediate, and output units across conversion boundaries. Name the
inventory/normalization basis (total, contacted, remaining, and similar distinctions)
and verify a hand-computable conservation or reference identity where useful.
Document units and assumptions at public boundaries and in nonobvious fixtures;
use repository notation and docstring conventions. Do not annotate every obvious
assignment mechanically, and do not change runtime labels/metadata strings merely
to enforce a comment notation.

For piecewise/reduced models, test applicable continuity, ordering, bounds,
endpoints, and singular regimes. When generalizing a constant into a parameter,
check reduction to the previous case and representative physical-range behavior.
Use repository consumers to settle sign/fraction conventions. For multiplicative
rates, use the stated domain convention; compound/log averaging must respect actual
interval lengths when intended to map first to last value.

Expected values should have an independent basis. Check an assertion's direction
against the model before tuning tolerance; derive tolerance from numerical error,
solver settings, or an accepted physical accuracy. Do not repeatedly loosen a
constant to fit one machine. After conflict resolution, revisit only units/contracts
whose inputs or call paths changed.

## Tables and literature

Parse committed parameter/provenance tables using their declared schema. Check
header/row widths, quoted delimiters, required dimensions, units, types, and missing
or assumed values; named readers can silently shift interior columns. Execute any
claimed consistency gate on the actual committed rows and consumer semantics.

Trace quantitative and attributed claims to primary sources and their precise
locations, following secondary references when necessary. Scope dataset-specific
ranges to that dataset. A replication claim requires comparing the source's
reported result with the run and an explicit justified error tolerance, not merely
matching its inputs. A discrepancy should be reported before assigning its cause.
If attributing a changed result to one input, rerun the old input under matched
conditions or qualify that attribution.

A DOI's valid redirect followed by publisher anti-bot 403/429 is not a broken DOI.
Verify mapping/title through the resolver or authoritative metadata, and distinguish
resolution from automated HTML accessibility. For BibTeX changes, check authoritative
author names and parser/style behavior for compound family names.

## Optimization claims

State objective sense, constraints, and decision-variable domains in optimization
problem statements, including binary versus spin conventions. Distinguish the
source problem from its encoded or penalized target before discussing guarantees.

Verify model class and algorithm guarantees. An `optimal` status, zero displayed
gap, or global MIP subsolver does not certify a nonconvex outer algorithm. Audit the
returned point against original equations, bounds, integrality, selection rules,
and selected disjuncts. Inventory required variables: restore recorded fixed choices,
but never invent missing free states from initial guesses or reference optima.
Call incomplete audits incomplete.

Completed exhaustive search establishes a global optimum over the enumerated
feasible domain. If a public status contradicts that guarantee or result metadata,
trace the getter and reproduce the discrepancy in the owning package. Treat a
confirmed status-reporting defect as upstream work within the authorized scope,
rather than rationalizing it as an intended algorithm limitation or preserving it
as the desired regression contract. Keep observed outputs truthful; a downstream
status override is not a substitute for repairing and testing the public contract.

Before attributing an invalid reformulated solution to automatic compiler behavior,
inspect explicit penalty/encoding overrides and check the supported default path.
A deliberately insufficient override establishes a configuration failure, not a
default-selection bug. Use valid formulations in normal-use demonstrations; reserve
deliberately broken settings for examples whose stated purpose is failure diagnosis.

Separate raw reported bounds from certified bounds. Local solver failure does not
prove global infeasibility or justify globally valid cuts. For an early-stopped
minimization relaxation, its valid solver best bound is the lower bound, not its
incumbent objective. Match strengthening, domains, budgets, and capable direct
baselines when evaluating decomposition; distinguish feasible solution quality,
valid gap progress, formulation gains, and computational advantage.

For exhaustive samplers and enumeration oracles, enforce conservative limits on
compiled state dimensions, assignments, and memory before unchecked exponentiation,
state allocation, or solver dispatch. Compilation can add encoded/slack variables;
source variable counts are insufficient. Reject work outside the validated limits
and record the refusal; a timeout alone does not prevent memory exhaustion. Apply
guards to independent references too. Test oversized input and exhausted budgets
without allocating their state spaces, and prove the child was not invoked.

Compare total work across decomposition calls, not just child-call counts: binary
enumeration costs `2^n` assignments per child, with evaluation/storage costs that
can also depend on its model. Reserve work before each call against a shared run
allowance; report limits, reserved work, actual completed work, and failures. Choose
caps for the validated implementation and environment rather than generalizing
one fixture's safe size to other solvers.

## Requested performance/benchmark evidence

Define a bounded comparison and pin source, versions, resources, threads, settings,
and raw artifacts. Warm JIT paths symmetrically; distinguish setup from solve timing.
Pair median/selected duration with metadata from that repetition or state each
aggregation. Report confounders and mixed gains.

For seeded stochastic benchmarks, confirm the effective seed at backend dispatch,
including the compiled boundary when native forwarding is claimed, and reconcile
it with public metadata. A stored attribute, parent label, or zero-call control
does not prove forwarding. Exact repeatability controls must match solver-facing
inputs, initialization, schedules and completed work; use symmetric warmups and
nonbinding algorithm deadlines under a separate safety bound. Preserve sample
multiplicities when ignoring harmless row ordering. Equal seeds with unequal work
do not establish or refute exact repeatability. Later seeded controls do not
retroactively relabel earlier unseeded measurements.

A reusable benchmark validation gate must bind executable dependencies, including
shared scoring/conversion code, runtime/backend identity and retained evidence,
rather than only modified adapter files. Exercise the actual parsed gate and
artifact hashes, rejecting missing or stale prerequisites before optimization.
Reuse measured evidence only when those bound inputs remain unchanged; gate
plumbing, documentation and derived audits can be checked without another solve.

Scope attempt counters and failure records to the producing run or campaign.
Carry earlier failed attempts into a continuing campaign's budget with explicit
provenance; a fresh reproduction records its own attempts instead of injecting
historical failures as new observations. Preserve the original campaign ledger
with its retained evidence, separately from new-run output.
Within a continuing campaign, retain each attempt's raw outputs before a retry
can overwrite them. Audit successful-attempt result rows separately from
cumulative reserved or consumed work, including failed attempts.

Compute each paired difference before aggregating across repetitions;
subtracting per-mode medians yields a different statistic. Retain aggregation/audit
code with reproducible benchmark evidence and check published tables, including
units, against the raw attempts.

Attribute costs to the operations actually inside the timing boundary. A broad
setup phase may include construction, conversion, copying and checks; isolate
the suspected operation before naming it a bottleneck. Keep ordinary, instrumented
and profiled runs distinct in job identity, exports and reports; verify the
exported groups rather than relying on richer raw metadata. Compare instrumentation
against ordinary controls and report its overhead. When profiling materially
perturbs runtime, use stacks for qualitative investigation, not ordinary-time
shares. Inclusive stack counts overlap and cannot be added as phase durations.

For attribution to one setting, compare solver-facing equations, bounds, ordering,
and initialized values, not just parameter names or dimensions. Separate explicit
model scaling from automatic solver scaling and retain matched default controls
within the authorized budget, or narrow the conclusion. Distinguish archived
execution inputs from later reconstructions.

Staged savings use absolute time deltas over baseline-to-final savings; measurements
against different baselines are non-additive. A process launched before an artifact
writer fix continues using old code: classify outputs by producing revision/process
and recapture or exclude affected artifacts explicitly.
