# Conditional implementation checks

Read only the routes relevant to the requested behavior.

- Scientific algorithms, units, solver guarantees, papers, or formalizations: use [scientific verification](../../gh-workflow-conventions/references/scientific-verification.md). Separate desired outcome from a cited mechanism; verify assumptions/resource constraints against the primary source. Trace and document units in changed expressions and tests.
- Notebook, parity, or live-service work: use [notebook guidance](../../gh-workflow-conventions/references/notebook-artifacts.md). Inventory corresponding source/target workflows including downstream outputs; decide execution/output scope explicitly. Preserve useful diagnostics and safe local configuration when replacing credential setup. Never commit secret-bearing output.
- Shared setup/configuration: inspect sibling artifact families, but verify each shares the defective contract before expanding the fix. Current base may already satisfy parts of a stale example.
- Dependencies/adapters, compatibility bounds, or dependency security mitigations: use [dependency contracts](../../gh-workflow-conventions/references/dependency-contracts.md). Preserve existing compatible allowances unless evidence requires narrowing, and validate pinned runtime objects rather than copying assumed field names.
- CI/workflow/Dependabot changes: validate with available appropriate tools; verify changed action tags and permission/event boundaries. Compare update directories with manifests, and changed status names with enforced contexts. Dependabot configuration is not an Actions workflow. Text-based config tests should normalize checkout line endings.
- Recovered deleted code: re-derive assumptions against current callers/data before trusting old tests. Correct case-specific assertions with evidence rather than assuming every failure means the restoration is wrong.
- Generated deliverables: use [artifact verification](../../gh-workflow-conventions/references/artifact-verification.md), preserve intentional edits in generators, and report any intentionally unexecuted output target.

Use repository documentation style for changed source contracts. Test helpers need extra explanation only where setup is non-obvious or policy requires it. For migrations, investigate relevant deprecation warnings and skipped lanes; do not expand a focused fix into a repository-wide style campaign.
