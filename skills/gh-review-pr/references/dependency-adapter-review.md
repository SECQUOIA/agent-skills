# Dependency and adapter review

Read for dependency/lockfile changes, solver or SDK adapters, vendored implementations, or advertised install paths. Use shared [dependency contracts](../../gh-workflow-conventions/references/dependency-contracts.md) for runtime test mechanics.

Check actual resolved versions and changed compatibility bounds against fresh base. Run a locked install or equivalent when lock/manifest agreement matters. Inspect mixed-ecosystem locks for duplicated packages in one prefix; successful import alone does not prove that competing artifacts are sound. Re-solve only when a suspicious resolution or outdated mapping needs evidence, not for every unrelated lock change.

For a newly advertised/renamed distribution, verify index identity and project ownership. A package name can install another project; a distribution rename retaining the import namespace may leave two ownership records. Test the affected upgrade/uninstall path in scratch and require accurate migration instructions. For a security remediation, verify advisory state, patched versions or removal of the vulnerable installed path, and any intentionally unsupported optional path.

Test thin adapters against the pinned dependency's actual result/request objects when practical. Verify accessor names, status/termination, finite values, success/failure handling, and backend-independent public results. Do not present a partial/stale result as success. For vendor-parity claims, compare generated payloads with the exact cited upstream version, including a matching control; offline self-consistent tests may merely repeat a wrong payload assumption. State unavailable service or license limits without treating an untested path as verified.

For generated external-tool input, validate with the consuming tool when available; text assertions alone do not establish acceptance. Probe through the project's driver before declaring a tool absent. Preserve deterministic tie-breaks where published results depend on alternate optima.

For vendored/derived code, compare shipped content with the exact pinned upstream revision and document deliberate deviations. Resolve mismatched pins through relevant file history, and verify cited issue/PR identities separately from commit subjects. Cross-check inherited numeric claims against the repository's own validated artifacts.
