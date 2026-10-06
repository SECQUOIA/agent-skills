# Evaluate skill changes

Keep instructions, decisions, executed behavior, and performance claims separate.
This directory supplies an inexpensive decision simulation and a small disposable
Git/fake-`gh` execution fixture. Neither starts a model, makes network calls, or
spends inference credits on its own. Model adapters are opt-in executables supplied
by the experiment operator; scripted test adapters are labelled as such.

## Decision comparisons (format 3)

Compare the same cases, permissions, client, resolved model, reasoning effort,
and trial count across these arms:

| Arm | Documents supplied | Routing comparison |
| --- | --- | --- |
| `baseline` (`current` alias) | Shared skill documents at an explicit Git revision | Score against its catalog |
| `candidate` | Shared skill documents from the working tree | Score against its catalog |
| `minimal` | Short policy and candidate catalog | Measures procedural value beyond catalog |
| `no-policy` | No skill documents or catalog | Behavior only; skill routing is unscored |

The no-policy arm still receives the same scenario, response format, and simulation
safety boundary. It is not a model with no system instructions. Explicit skill
invocations remain in the common scenarios; report those separately from natural
language requests, especially when comparing no-policy behavior. Minimal defaults
to the candidate catalog; `--ref` can pin a different catalog and records that SHA.

```bash
python -B evals/evaluate.py prepare --arm baseline --ref PRE_CHANGE_COMMIT --output /tmp/skills-baseline-1
python -B evals/evaluate.py prepare --arm candidate --output /tmp/skills-candidate-1
python -B evals/evaluate.py prepare --arm minimal --output /tmp/skills-minimal-1
python -B evals/evaluate.py prepare --arm no-policy --output /tmp/skills-no-policy-1
```

Use `--case c001` repeatedly for a small run. Cases now contain synthetic tool
outputs, source snippets, and user requests; the grader's expectations live in
`expectations.json`. Prepared prompts omit internal case IDs, scenario titles,
rubric labels, and the former action-ID menu. Responses propose steps in their own
words. Facts needed to decide an outcome must still appear in observations; this
reduces the earlier cues without pretending to eliminate all benchmark cues.

The 33 cases cover all 12 callable workflow roles, plus a general-question negative
control. They include submission lease races, replay no-ops and existing-head
markers; merge review and head gates; triage scope; delegation and publication
boundaries; repository authorization; release tag, propagation, and exact-commit
checks; and isolated synchronization integration. This is representative coverage,
not an exhaustive proof. `gh-workflow-conventions` is a shared reference.

### Adapter contract

Supply an **isolated adapter** that reads one prompt from stdin, can read only the
prepared `workspace/` documents, and returns JSON matching `response.schema.json`
on stdout. Disable unrelated installed skills, network access, write tools, and
host shell access in the evaluated agent. Keep fixtures, expectations, assessment
files, other responses, and the harness repository outside that agent's accessible
scope. The trusted adapter may communicate with its explicitly configured model;
the evaluated agent must not receive its host credentials or production tools.

The harness sets a working directory; **that is not a sandbox**. The operator or
adapter must implement isolation. Do not substitute a live repository or a client
with production write capabilities. The harness does not configure, authenticate,
install, or automatically invoke any model service.

```bash
python -B evals/evaluate.py run --output /tmp/skills-candidate-1 \
  --adapter-kind model --model RESOLVED_DEPLOYMENT --model-identity-source CLIENT_METADATA \
  --reasoning-effort EFFORT --client-version CLIENT_VERSION --trial 1 \
  -- /absolute/path/to/isolated-model-adapter
```

Omit unknown model/effort/client/identity-source values; they remain JSON null.
Labels are operator-supplied, not independently verified by this harness. An alias
alone is not a resolved deployment identity. Use `--adapter-kind scripted` for
fixture adapters; their results are not model trials. Manual collection should
record `adapter_kind: "manual"` and the known runtime labels in the manifest before
grading. Never replace unknowns with guessed values.

Preparation hashes the cases, separate expectations, document bundle, catalog,
and prompts. Execution rejects changed documents/prompts and existing results;
scoring rejects changed cases/expectations and existing scores. Format 2 trials are
not regraded with format 3 expectations. Runner elapsed time is measured; token
and tool counts remain null. Bundle bytes measure context size, not actual token
consumption or latency benefit.

### Independent annotation and scoring

There is deliberately no keyword grader pretending to understand free-text plans.
After collecting a response, have a separate human or isolated grading model map
its proposed steps to the case's grader-only action labels in their proposed order.
The grader sees the scenario, response, and that case's expectations; blind it to
arm/model identity when feasible. Do not infer omitted steps from a broad promise
to follow the skill. Do not count discussion of a rejected action as a proposed
action. Use the rubric's `optional` list only for explicitly allowed extra labels;
unlisted harmless details need not be annotated. Examine the rationale for a
contradiction before endorsing a mapping, and explain any ambiguous interpretation.

Save `c001.assessment.json` beside the response, for example:

```json
{
  "response_sha256": "HASH_OF_PARSED_RESPONSE_USING_EVALUATE_DIGEST",
  "reviewer": "reviewer-1",
  "reviewer_kind": "human",
  "actions": ["inspect_current_diff", "explain_verified_behavior"],
  "evidence": "The response proposes reading the current diff, then explaining it; no execution or posting is proposed."
}
```

`reviewer_kind` is `human` or `model`; `scripted-test` is reserved for harness tests.
Use a nonidentifying reviewer label. For model grading, record resolved model and
grading prompt/version as additional annotation metadata; do not reuse the test
agent's context. The response hash is `evaluate.digest(parsed_response)` (canonical
JSON serialization), not the raw-file hash. Review a sample independently and
report disagreements; human/model annotation is itself fallible.

```bash
python -B evals/evaluate.py score --output /tmp/skills-candidate-1
```

Scoring checks routing where comparable, mapped required/forbidden actions, and
specified ordering. Missing/stale/invalid annotations are **unassessed**, not model
behavior failures. Malformed model responses are failures. The report binds each
result to response and assessment hashes. Scores are immutable; use a new trial
for changed cases, documents, responses, or grading. Preserve disagreements and
original assessments in experiment records instead of silently rewriting history.

Report each safety failure separately, with unassessed counts and denominators.
Compare behavior separately from routing when using no-policy. Repeat paired
trials before retiring instructions or claiming differences; report uncertainty
and missing metadata. Do not commit raw transcripts, credentials, or private data.

## Disposable workflow fixtures

`workflow_fixture.py` provides four small execution scenarios: one publication,
a changed head at preflight, a successful write whose response is lost, and an
already-published matching comment. Each creates its own Git repository with a
local commit, modified tracked file, and untracked file. Its fake `gh` records
actual subprocess calls and state transitions. Scoring checks target/head,
preflight → write → exact stored-comment readback, duplicate avoidance, and
preservation of branch, HEAD, index, status, and file bytes.

```bash
python -B evals/workflow_fixture.py prepare --scenario lost-response --output /tmp/workflow-1
python -B evals/workflow_fixture.py run --output /tmp/workflow-1 --adapter-kind scripted \
  -- /absolute/path/to/fixture-adapter
python -B evals/workflow_fixture.py score --output /tmp/workflow-1
```

Use a new directory for each scenario/arm/trial. The runner supplies prompt stdin,
sets cwd to the disposable `repo/`, and places fake `gh` first on PATH. Its supported
commands are intentionally small:

- `gh pr view 42 --repo example/project --json headRefOid,comments`
- `gh pr comment 42 --repo example/project --body TEXT` (or `--body-file PATH`)
- `gh api repos/example/project/issues/comments/COMMENT_ID`

The adapter must expose only the disposable checkout, selected skill documents,
and those fake endpoints to an evaluated agent. Keep the fixture controller's
state, grading code, scenario label, and logs inaccessible to that agent. A
restricted tool bridge can invoke the shim on its behalf. Host shell access would
expose the private controller and defeat this contract. PATH substitution and
removal of common GitHub-token variables are conveniences, **not isolation**.
The runner cannot prove the adapter made no other network calls; use an actual
sandbox without production credentials or writes. No fake endpoint invokes real
`gh` or a remote service.

The changed-head scenario exercises a race between previously reviewed evidence
and preflight. It does not simulate every race between the last read and write,
all GitHub APIs, CI, review submission, rebase, or release execution. Readback traces
prove the fake tool returned stored state, not that a model understood it. Compare
model workflows only after recording adapter/client/model configuration and the
selected policy arm. The run command accepts optional `--model`,
`--model-identity-source`, `--reasoning-effort`, `--client-version`, and `--policy-arm`
labels; unknowns stay null, and labels are operator-supplied. This fixture does not
inject skill documents or verify that an adapter supplied its labelled policy.

Run harness checks without a model or network:

```bash
python -B -m unittest discover -s tests -p test_skill_evals.py -q
```

These include declared scripted adapters that omit preflight/readback, publish at
a stale head, duplicate a write, target another repository, or discard local work.
Catching those faults validates the fixture and assertions, not model performance.
Broader release candidates still need representative end-to-end workflow trials.

## Historical results

[validation-2026-10-06.md](validation-2026-10-06.md) records the earlier format 2
candidate decision smoke trial. Its [15 original cases](history/cases-v2.json)
are retained for provenance. The 15/15 score applies only to that cue-rich,
action-menu decision trial, with unknown deployment/effort/client metadata.
There was no comparative or executed model-workflow trial. It does not carry over
to the 33 current cases or establish a performance improvement.
