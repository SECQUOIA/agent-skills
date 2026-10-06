# Dependencies, APIs, and Test Selection

Use for dependency replacements, public-boundary changes, optional-backend behavior,
and changes to the CI cohort. These checks are conditional on those claims.

## Compatibility and parity

For a replacement/reimplementation, verify the replacement premise against the
current upstream version and compare the repository's actual call patterns with
that dependency. Include relevant boundary sizes/defaults and source contracts that
output diffs cannot reveal (retries, headers, parsed exception messages). Scope the
comparison and make durable parity evidence reproducible when the claim warrants it.
Do not treat tests written only for the replacement as proof of equivalence.

Verify claimed dependency rationale against metadata/lock/source use. Compare lock
environments structurally rather than interpreting reorder churn as a broad change.
If a file is claimed behavior-neutral and the claim matters, compare syntax trees
or another appropriate semantic representation; do not require AST checks for every
prose edit.

For tightened public validation, inventory existing callers, including notebooks
and examples, that could become invalid. For renamed API/defaults/sentinels, follow
the repository's compatibility policy and trace relevant producers/consumers.
Preserve deprecated aliases when policy requires them and test both warning and
returned behavior. Test reset/off/default transitions on a reused object when
state persists. Type changes need scrutiny at strict serializers and third-party
adapters; place conversions at the boundary that requires them. Call-chain-depth
constants such as warning `stacklevel` need representative entry-point paths, not
just the one with the expected depth.

## Optional dependencies

Distinguish minimal-install importability from backend execution. Place optional
imports behind the established skip mechanism when module import genuinely requires
them; keep production imports unconditional when collection itself is meant to
verify backend-free importability. Run the relevant minimal profile and identify
the backend-enabled lane rather than generalizing from a rich local environment.

For fallback changes, execute the missing-dependency path. An isolated environment
without the package is preferable when readily available; a targeted import blocker
is an alternative if its own behavior is verified. Patching `__import__` alone does
not block `importlib.import_module`; `find_spec` should emulate native absence
rather than unexpectedly raising during collection. Account for transitive optional
imports too. Report boundary-only stub coverage as such.

## CI selection

When CI invokes explicit node IDs, a new test in the same file may still be excluded.
Check the actual invocation and run its changed cohort. For marker/lane-expression
changes, verify relevant sibling collection boundaries with `--collect-only`.
A marker such as `serial` has no scheduling effect without supporting configuration.
Prefer real helper modules or fixtures over direct `conftest` imports unless the
repository explicitly supports that structure. Use configuration-contract guards
only for meaningful recurring selection risks, not as a universal extra test.
