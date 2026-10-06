# Specialized review routes

Load only the matching reference; these are conditional checks rather than a second universal review pipeline.

| Change or claim | Read |
|---|---|
| Notebook/figure/parity or executed output | Shared [notebooks](../../gh-workflow-conventions/references/notebook-artifacts.md); [publication artifacts](publication-artifacts.md) for rendered figures/manuscripts |
| Generated artifact freshness | Shared [artifact verification](../../gh-workflow-conventions/references/artifact-verification.md) |
| Scientific quantities, solver guarantees, result tables | Shared [scientific verification](../../gh-workflow-conventions/references/scientific-verification.md) |
| Dependency, lockfile, adapter, SDK, vendored provenance | [Dependency and adapter review](dependency-adapter-review.md) |
| Policy/skill split, discoverability, CI, Dependabot, docs build | [Repository contracts](repository-contracts.md) |
| Removed/replaced tests or disputed evidence | [Testing and evidence](testing-and-evidence.md) |
| Base drift, path removal/rename, full-tree output | Shared [checkout/merge-result guidance](../../gh-workflow-conventions/references/worktrees-and-checkouts.md) |

For path removals/renames, inspect current-base consumers and verify the relevant merge result when base drift could introduce breakage. State which tree was tested. For shared setup or canonical-guidance claims, search sibling artifact/language families for active contradictory copies; verify their contracts before expanding scope.
