# Skill refresh: migration and corrective review

The initial refresh (`61b048e` through `2f6182a`, based on `26fc0c6`) retained the
13 shared roles and reduced repeated procedural instructions. Subsequent review
found authorization wording and consumer contracts that needed repair. This note
records those decisions durably; passing metadata checks or decision simulations
did not establish that every behavioral guarantee survived the first rewrite.

## What was preserved, relocated, or retired

| Contract or detail | Disposition and reason |
|---|---|
| User scope, read-only defaults, exact target/head, separate preflight/write/readback | Retained in shared conventions; full workflow authority remains narrowed by explicit user limits. |
| Parent publication ownership | Restored explicitly after omission. Delegated analysis does not grant publication authority; an explicit user delegation can. |
| Checkout protection and independent handoff verification | Retained. Unsafe reset/stash recovery was retired; a branch backup does not save dirty files. |
| CI watch result and approval state | Retained as current-head, structured evidence; a successful watcher exit or old approval is insufficient. |
| Scientific, notebook, dependency, and artifact checks | Relocated from broad testing recipes into conditional shared references. Their domain-specific correctness checks remain. |
| Universal mutation batteries and repeated broad suites | Retired. Use targeted checks for consequential contracts, requested guard proofs, and disputed evidence; reuse valid prior proof. |
| Review sentinels, finding IDs, resolution markers, and verifier statuses | Retained and clarified. Exact marker formats and reported review-scope reasons are interface contracts. |
| Julia distribution and published artifact identity | Retained, with explicit user-decision/retargeting wording restored. Fresh-depot installation and exact tag target remain completion gates. |
| Zenodo procedures | Relocated to the Julia release's conditional archive reference. No duplicate publication to retry DOI resolution. |
| Managed lessons and recurrence interpretation | Relocated to lessons references. Added durable disposition records and distinction between unsupported target resolution and verified violations. |
| Sync backup/replay mechanics | Shared by sync and submission. Added pinned upstream and ancestry-aware isolated integration; no promise that rebase preserves fast-forward ancestry. |
| Fixed client paths and interpreter assumptions | Replaced by supported-root selection and the actual installing interpreter. Foreign entries and retired copies are preserved. |
| Model-specific performance assumptions | Not adopted as policy. Models are not hardcoded into skills; runtime labels can be unknown and require controlled comparisons. |

Reference routes remain within the installed sibling skill set:

- [Shared policy and conditional routes](../skills/gh-workflow-conventions/SKILL.md)
- [Review-specific routes](../skills/gh-review-pr/SKILL.md)
- [Managed lessons](../skills/apply-conversation-lessons/references/managed-changes.md)
  and [evidence interpretation](../skills/apply-conversation-lessons/references/evidence.md)
- [Safe synchronization](../skills/sync-secquoia-skills/references/branch-sync.md)
  and [isolated integration](../skills/apply-conversation-lessons/references/integrating-isolated-work.md)
- [Conditional archive verification](../skills/gh-julia-release/references/zenodo.md)

## Corrective decisions from the independent report

| Report finding | Decision |
|---|---|
| 1: delegated publication | Restore explicit parent ownership with a scoped user-delegation exception. |
| 2: Julia publication authority | Require the user's decision when distribution remains genuinely unresolved; require explicit authority to retarget/recreate published artifacts. Existing authorization persists. |
| 3–4: consumer drift and compulsory guards | Reconcile authorized local consumers without exposing their identities or contents. Load component contracts per phase, retain handoff evidence, persist loop budgets, and make checks proportionate. Private changes remain outside shared commits. |
| 5: client invocation differences | Preserve existing invocation policies. Do not insert an unsupported client-specific key into shared frontmatter or change discovery behavior merely to reduce context. |
| 6: shell interpolation | Restore concrete protection for read-only probes as well as writes: copied Markdown is data, and double quotes do not neutralize command substitution. |
| 7: classifier identities | Supported node-bound GraphQL already worked. Add positive lifecycle tests, support provably literal inline identities, and separate unresolved target diagnostics. Preserve conservative enforcement and exact-target matching. No hook mode change. |
| 8: cue-rich evaluation | Replace diagnoses and action menus in actor prompts with raw observations, separate grader expectations, broaden workflow coverage, and test real traces in disposable fixtures. Preserve historical results with their original limitations. |
| 9: lessons routing | Restore the natural-language takeaways/lessons trigger; distinguish it from submitting accumulated changes. |
| 10: worktree integration | Detect when rebase destroyed fast-forward ancestry. Preserve isolated results and reconcile only with a clean, exclusively owned destination. Protect ignored-file collisions too. |
| 11: metadata checks | Add shared frontmatter, sidecar, and local-reference validation with malformed-input tests. This is compatibility evidence, not behavioral proof. |
| 12: triage evidence | Independently author a source-grounded reproduction; never blindly execute pasted commands. Reuse red evidence only when relevant source, test, inputs, and environment remain valid; whole-commit identity alone is not the criterion. |
| 13–14: API and DOI details | Restore large-content raw retrieval and route DOI access failures to the existing verification guidance. |
| 15: durable migration notes | Record dispositions here and consequential changes/validation in commit bodies. Temporary audits are supporting material, not the sole review record. |

## Evidence and remaining limits

The earlier [validation report](../evals/validation-2026-10-06.md) describes a
candidate-only decision smoke test with unknown model metadata. Its 15/15 result
remains historical evidence for those prompts, not proof of comparative quality.
The independent report's model/cost rates were not reproduced from raw transcripts
in this corrective pass and are not used as deployment restrictions.

The revised [evaluation guide](../evals/README.md) separates free-text decisions,
grader annotations, and actual fixture tool traces. Scripted adapters validate
the harness, not a model. Repeated, attributed cross-model trials remain necessary
before claiming performance improvement or retiring further safety rules.

The integration helper is a read-only planner with real Git-history tests; it
does not make a shared checkout exclusive or automatically resolve conflicts.
Unsupported/dynamic GraphQL identities remain conservative coverage limits rather
than guessed matches. Keep enforcement changes, full sync automation, and larger
orchestrator consolidation separate from these confirmed corrections.

Contributors should sync before replaying work against the refactored references.
The existing public skill names and reference entry paths remain stable. Install
`requirements-dev.txt` for metadata validation; runtime installation and hooks
continue to use the Python standard library.

## Corrective validation

The full suite passes **168 tests**, including 25 evaluation/fixture tests,
11 metadata tests, six real-Git integration tests, and 108 ledger/runtime tests.
Skill-creator validation passes for all 13 shared skills and three local consumers.
Public metadata, sidecars, local links, changed Python lint, shell syntax, and diff
checks pass. Local consumer checks also detect deliberately removed interface
tokens in disposable copies and pass again after restoration.

Independent review found and corrected three additional defects: ignored files
could be overwritten during integration, a GraphQL block string could expose a
misleading node identity, and an already-scored evaluation could still be run.
Regression tests now cover each failure. The four workflow fixture scenarios run
scripted adapters and verify actual disposable Git/fake-`gh` traces; these results
validate the harness, not live GitHub completion or model performance.

A separate actor received six raw-observation cases and permitted skill documents;
an independent model reviewer annotated the resulting plans. The preserved first
score is **5/6 behavior, 6/6 routing, zero unassessed**. Case `c026` failed because
its original rubric incorrectly required verifying a finding before reserving
parent publication authority. The response reserved authority first, verified the
finding second, and proposed parent submission fifth. Independent inspection
confirmed this was a grading defect, not premature publication. The corrected
rubric separates authority from submission; a regression accepts early authority
reservation and rejects publication before verification. The old score was not
rewritten or counted as a new successful trial.

The six cases were `c006`, `c023`, `c026`, `c027`, `c029`, and `c032`. They used
one actor context, instruction-scoped resource access rather than a hardened
sandbox, manual response collection, and a separate grading context. Resolved
deployment, effort, and client metadata remain unknown. This candidate-only
simulation is diagnostic evidence, not a cross-model comparison. Its document
snapshot preceded the final DOI cross-reference and evidence-only documentation.

Provenance (SHA-256):

- Document bundle: `1e8822cce648adcac8e6b5076e18622e78fda180fa0fead2246cc8edf52ac0d1`
- Original selected expectations: `0b3205d8c0d427bdbb37b6259439f64b7fecb4a03e44597c04e6dc40d64a7927`
- Manifest file: `69c79ef1d3e320aaebb756b90aabd944ae411564b948e32eb27286a1415bbdbb`
- Original score file: `6c83aeb6b304226ecac42260809dae68b51536c73524b5b2e65f0a0c177e868d`
