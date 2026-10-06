# Notebook Outputs and Provenance

Use when committed notebooks/outputs, execution provenance, or cross-runtime
notebook parity are part of the deliverable.

Identify the published artifact first. A tracked source notebook may carry the
visible outputs while CI executes into an ignored `_output.ipynb`; green execution
there does not refresh what readers see. Reproduce the canonical invocation and
parameters recorded by the project or execution metadata, not an unrelated test's
parameter injection. Preserve each file's JSON serialization by checking an
unmodified round trip before rewriting it.

When outputs record the generating source SHA, commit sources first, execute that
revision, then make an output-only commit. Verify identical cell sources across the
output commit and that the recorded SHA actually contains the executed code. Native
extensions/executables also need verified source/build identity; matching notebook
cells alone is insufficient.

Verify refreshed-output or parity claims by execution and semantic comparison, not
by trusting committed values. Require no execution errors, coalesce split stream
chunks, and compare result-bearing outputs. Exclude setup output only under a stated
policy after confirming it contains merely transient timing/activation/host paths;
never normalize scientific values away. Assert the extracted result cohort is
nonempty. Distinguish byte identity from semantic equivalence and document legitimate
runtime-specific differences.

If a setup-only change produces new stochastic scientific samples during a paid or
credentialed run, separate execution evidence from publication. Retain the accepted
result set unless refreshing those results is in scope, report the differences,
and do not call retained samples reproduced by the new run. Inspect generated
outputs for secrets and unwanted local paths before committing.

For comparison tutorials, inventory canonical sources, generated artifacts, and
plot families. Use matched timing scope or state why timing comparisons are not
valid. For a parity guard, a representative divergent/missing-output case should
fail when coverage is consequential or disputed; use
[mutation testing](mutation-testing.md) for the relevant probe.

When a focused Python test needs one cell function, parse and compile the exact
AST node instead of splitting on the next `def` or executing unrelated live calls.
For pinned examples/doctests, generate expected text by running the example. Prefer
stable or uniquely determined outputs; keep nondeterministic warnings/logging out
of exact doctests. Validate stochastic assertions against the framework's RNG
contract and a justified stability margin rather than requiring a seed ritual for
every test.

Kernel/source-environment failures belong to
[environment troubleshooting](environment-troubleshooting.md), not to source findings.
