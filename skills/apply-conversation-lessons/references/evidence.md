# Evidence for skill changes

Use when interpreting encounter reports or evaluating a substantial skill/model
change. These are separate sources of evidence:

- **Encounter episodes:** recurrence across independent workflow episodes, which
  may revisit the same target. Time/target deduplication is a heuristic, not proof
  of independence. Discount superseded revisions and unsupported operation shapes.
- **Hook observations:** what a recognized operation did under an observed model,
  reasoning setting, client version, and skill revision. Unknown metadata stays
  unknown. A mixed-agent/model episode is not attributable solely to its last
  participant; observations are not independent episodes.
  Unresolved target identities are coverage diagnostics, not demonstrated
  missing-read violations. Exclude them from recurrence eligibility; retain and
  explain any legacy inference rather than rewriting historical outcomes.
- **Behavioral evaluations:** controlled requests, recorded actions, artifacts,
  and scored outcomes under the evaluated conditions.

Audit mode never prevents a write: an `escaped` flag does not prove an enforced
guard failed. Repeatedly prevented mistakes may show a working guard; confirmed
escaped deterministic mistakes may call for enforcement or a classifier repair,
not more prose. The ledger's two GitHub-write rules do not measure review quality,
scope judgment, or overall task success. Its counts are not model failure rates.

For worker publication diagnostics, use the separate
[remote-write audit](worker-publication-audit.md). It records recognized attempts,
not unauthorized or completed writes; explicit publisher handoffs may permit a
worker to write. Unknown client role metadata remains unknown. These observations
do not enter violation counts or the recurrence threshold.

For a model-upgrade comparison, keep user requests, organization policy, fixtures,
tool permissions, and grading criteria constant. Compare current instructions,
the candidate, and a minimal policy baseline. Record model, effort, client version,
skill revision/content hash, trial, elapsed time, token/tool usage when exposed,
and missing metadata. Repeat representative cases before making comparative claims.
Include implicit/explicit activation and negative controls, authorization limits,
dirty workspaces, stale heads/CI, ambiguous writes, domain defects, and trivial
changes that should not trigger broad testing.
Give the actor raw observations, not a diagnosis embedded in the scenario title
or evidence. Keep answer keys and semantic action labels outside its workspace.
Include every publishing workflow and consumers of changed output contracts;
synthetic successful decisions do not establish safe execution of those workflows.

Score correctness, completion, preservation of user work, external-write scope,
unnecessary questions, and work performed. Critical permission/data-loss failures
must not disappear inside an average score. Distinguish a decision-only simulation
from a tool-using workflow evaluation and either from an actual production run.
The repository's `evals/` tools provide a starting point; they need not be installed
in every consuming repository.

## Resource allocation comparisons

Compare effort within one fixed model/client and instruction revision first,
using paired solo tasks with the same tools, permissions, and grading. Test helper
count and helper model separately afterward; keep the primary setting fixed.
Use multiple representative task instances, including procedural gates, misleading
feedback, seeded defects and decoys, scientific evidence, and explicit solo limits.
Additional effort and agent count are separate hypotheses, not quality guarantees.

Record requested settings and client-reported model/effort with their provenance.
An omitted flag plus a documented default only supports an inference when the
relevant configuration/environment is known. Missing fields stay unknown; an
initialization event may report client state without confirming every API turn.
Preserve enough sanitized configuration to reproduce precedence without recording
credentials. Historical plans and hook observations are not controlled effort arms.

Define absolute acceptance criteria before comparing arms. Measure completion,
defect recall, false findings, gate decisions, unnecessary work/rework, elapsed time,
and total usage across the primary and helpers. Report critical failures separately
and variability across trials; majority success must not hide intermittent defects.
The highest-effort arm can also fail the acceptance criteria. Small pilots screen
for regressions; zero observed failures does not establish a reliable safety floor.
Claims of non-inferiority need predefined tolerances and adequate independent cases,
with held-out validation before broad adoption. Proposing trials does not authorize
paid batches, external writes, or configuration changes.
