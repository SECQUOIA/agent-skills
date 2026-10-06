# Refresh validation — 2026-10-06

The refactor retains all 13 workflow roles. It removes duplicated recipes and
universal testing rituals, routes specialized domain checks to conditional
references, and preserves substantive publication and verification safeguards.
Discovery descriptions shrink from 8,336 to 2,217 characters; core instructions
shrink by approximately 75%, and all skill Markdown by approximately 65%.
These are context-size measurements, not performance measurements.

Validated the changes with:

- 126 deterministic tests: the original 88 plus runtime metadata, installation
  ownership/retirement, interpreter portability, and evaluation-integrity cases.
- Skill metadata validation for all 13 skills, relative-reference and sidecar
  checks, Python lint, shell syntax, and Git whitespace checks.
- One independent delegated decision trial on all 15 scenarios: 15 passed.
  The evaluator did not read answer keys or execute the proposed workflows.

The decision trial used harness format 2, fixture hash
`84f323a51a1f780bdbc9f09167ed0801f9eb034878fa78d67554f45ed2a09c8f`,
and skill-document bundle hash
`ca2d6031609369e3b8ec81c5029c9d31d800944eca5b5385ef7f368a72f98ea7`.
Exact model deployment, reasoning effort, and client version were unavailable and
remain unknown. The subsequent sync documentation adjustment describes installer
cleanup of retired owned links/copies; that behavior is covered by installer tests.

An earlier author smoke trial passed 14 of 15 expanded assertions. Its remaining
structured action-order mismatch exposed an ambiguous action ID combining
pre-rebase inventory and post-rebase proof; the rationale described both correctly.
The fixture now names those actions separately. The later trial used the revised
fixture without access to the earlier responses or grader.

Current-revision and minimal-policy bundles were prepared successfully, but no
comparative multi-model experiment was run. Decision selection does not prove
actual GitHub/tool execution, latency improvement, or superior model performance.
Use [the evaluation guide](README.md) for repeated comparisons and disposable
workflow trials before making those claims. No live installation, hook settings,
encounter database, or GitHub publication was used for these checks.
