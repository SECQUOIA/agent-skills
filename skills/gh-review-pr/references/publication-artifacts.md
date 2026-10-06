# Publication artifacts

Read when the rendered figure, manuscript, report, or reproducible result is a deliverable. Use shared [artifact verification](../../gh-workflow-conventions/references/artifact-verification.md), [notebook guidance](../../gh-workflow-conventions/references/notebook-artifacts.md), and [scientific verification](../../gh-workflow-conventions/references/scientific-verification.md) only for the relevant artifact.

Inspect the actual displayed output and its data. For plotting changes, compare labels, legends, annotations, arrays, and domain effects against the claimed behavior; log axes can silently omit meaningful zero/negative observations. For parity, include downstream analysis and committed outputs rather than only matching replacement APIs.

For manuscripts, compile with the project toolchain and inspect the final log rather than intermediate-pass warnings. Check citations/references, figure/caption agreement, data-derived prose outside the diff, indexed formulas' boundary conventions, and affected rendered layouts. If changed navigation/fonts or submission requirements are relevant, validate bookmark destinations and font suitability. Compare suspected regressions with base before attributing pre-existing warnings to the PR; do not mandate a complete typography audit for unrelated text edits.

Trace changed dependencies into committed artifacts before rebuilding. A proof that committed inputs cannot reach the changed branch can justify reuse; otherwise check the affected artifact bytes or appropriate semantic layer. Preserve deliberate manual edits in the source generator before regeneration. Source AST identity alone does not prove generated output freshness.

For reproducible result tables, verify enough representative rows and edge cases to support the stated conclusion, identifying actual coverage. Use permitted configurable solver alternatives when they preserve the method; disclose the substitution. Time-limited results are load-sensitive, so distinguish resource variation from a method defect before alleging failed reproduction. Never describe pinned private aggregates or a golden-file check as independent recomputation.
