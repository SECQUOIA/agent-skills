# Repository contracts

Read for policies, skill/refactoring instructions, discovery/install surfaces, workflow configuration, or generated docs.

## Instruction and policy changes

Check that referenced commands, markers, environments, paths, links, and heading anchors exist and match actual repository use. Define normative terms where readers need them to satisfy a gate. Consult relevant repository decisions when a policy or agent file may conflict with a documented refusal or boundary; do not invent local policy from a historical example.

For a progressive-disclosure split, account for original requirements as kept, consolidated, relocated, or deliberately retired. Compare clauses mechanically to locate candidates, then assess meaning rather than requiring verbatim retention. Audit routing at each action: can an agent reach the prerequisite before performing the operation? Check for unconditional duties made conditional, stop rules preceding their exceptions, orphan references, and stale “above/step N” pointers. New skill/plugin/command units also need consistent metadata, catalogs, installers, and discovery locations.

## CI and update configuration

Validate changed YAML and workflows with available repository tools. Verify referenced action/tool versions and unnecessary token/secret expansion. Treat privileged `pull_request_target` or `workflow_run` execution of contributor-controlled code as a concrete trust-boundary concern; inspect checkout refs, install steps, test hooks, and config-controlled tools. A safe design keeps untrusted execution unprivileged and treats its artifacts as untrusted inputs.

For renamed job/status contexts, compare emitted checks with live required contexts before declaring readiness. For Dependabot, compare configured directories and grouping with actual manifests, including explained exceptions; it is configuration, not an Actions workflow to run by name.

## Generated sites

Build the affected site when practical, or use an authoritative same-head build with focused static/artifact checks when that settles the claim. Inspect rendered markup, relative/base-path links, and shipped syntax rather than only source assertions. A changed block start can render intended HTML as escaped code while links still pass. Verify the intended deployment owner and distinguish preview URLs from the canonical site.

For citation files use the relevant schema validator when available, not YAML parse alone. Check that the author roster and provenance match the stated scope; do not broaden an author list by inference.

For DOI links returning access errors such as 403 or 429, use the [DOI verification guidance](../../gh-workflow-conventions/references/github-troubleshooting.md) before calling the citation broken.
