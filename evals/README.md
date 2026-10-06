# Evaluate skill changes

Use the same tasks, permissions, client, model, reasoning effort, and trial count
to compare three arms: a pinned **current** revision, the **candidate** working
tree, and a **minimal policy** baseline. Record missing metadata as unknown.
Smaller prompts and stronger models are hypotheses, not evidence of success.

## Decision simulations

The included 15 cases test routing and proposed actions around write scope,
pending human reviews, dirty checkouts, stale CI, scientific oracles, proportional
testing, safe synchronization, release policy, and attribution. Each includes
private-to-the-grader expectations, not production credentials or real targets.

Prepare a new directory per arm and trial outside this repository:

```bash
python -B evals/evaluate.py prepare --arm current --ref PRE_CHANGE_COMMIT --output /tmp/skills-current-1
python -B evals/evaluate.py prepare --arm candidate --output /tmp/skills-candidate-1
python -B evals/evaluate.py prepare --arm minimal --output /tmp/skills-minimal-1
```

Use `--case CASE_ID` repeatedly for a smoke run. Preparation snapshots only shared
skill Markdown/YAML, hashes the document bundle, catalog, and cases, and writes
one prompt per case. The minimal arm keeps the candidate catalog with a short
policy; it measures procedural value beyond that catalog, not a skill-free model.
No private skills or local encounter database enter the experiment.

Supply an **isolated model adapter** that reads the prompt from stdin, can read
only the prepared `workspace/` documents, and returns JSON matching
`response.schema.json` on stdout. Disable unrelated installed skills and network,
shell, and write tools in the adapter. A working directory alone is not a sandbox.
The harness does not install, authenticate, configure a model, or enforce tool
isolation. Do not run the adapter against a live repository or with production
write tools. Keep answer keys (`cases.json`) outside the model's accessible scope.

```bash
python -B evals/evaluate.py run --output /tmp/skills-candidate-1 \
  --model MODEL_ID --reasoning-effort EFFORT --client-version CLIENT_VERSION \
  --trial 1 -- /absolute/path/to/isolated-model-adapter
python -B evals/evaluate.py score --output /tmp/skills-candidate-1
```

An adapter using Codex can consume `--json` event output and `--output-schema`,
but it must still enforce the isolation above and extract only the final object.
Never infer the model from an alias without recording the resolved identity when
the client exposes it. For manual trials, save `CASE_ID.response.json` and fill
the manifest's runtime labels; retain unknowns rather than inventing values.
Omit unavailable model, reasoning-effort, or client-version flags; those labels
remain JSON null. Trials are immutable: the runner rejects any existing response
or metrics before changing labels, and execution/scoring verify prepared document
and prompt hashes. Prepare a fresh directory instead of replacing responses. The runner records elapsed time; token/tool counts remain null unless
independently measured. Bundle bytes are a context-size proxy, not token usage.

Scoring checks routing, required actions, forbidden actions, and relevant ordering.
Missing/malformed responses, unknown action IDs, changed case definitions, and
altered prepared documents/prompts fail. Inspect rationales
and actual traces as well: selecting the correct action ID cannot prove the agent
would execute it correctly. Report safety failures individually, not hidden in an
average. Repeat trials and compare each case across all arms before deciding
whether instructions can be retired. Do not commit raw transcripts or private data.

## Workflow trials and adoption

Decision simulations are an inexpensive first gate, **not end-to-end tests or
proof of model superiority**. For a release candidate, run representative workflows
in disposable local repositories with a fake `gh` executable or dedicated test
repositories. Capture actual tool traces and compare:

- task outcome and exact target/head;
- authorized writes, live preflight, and readback ordering;
- preservation of dirty files, unique commits, and unrelated pending reviews;
- appropriate tests and their source/environment provenance;
- tool calls, tokens, elapsed time, duplicate work, and unnecessary clarifications.

Include explicit invocation, natural-language routing, negative controls, and
untrusted instructions in issue/PR text. Test helper scripts independently with
`python -B -m unittest discover -s tests -q`. A scripted mock proves the mock and
assertions, not model performance; label it accordingly. Keep production audit
observations separate from both decision and workflow experiments.

Use this process when models or clients change, after substantive permission or
routing edits, and before deleting a safety-critical rule. Keep model-specific
adaptations in a measured profile rather than hardcoding a model into every skill.

The design follows OpenAI's guidance on [skill evaluations](https://developers.openai.com/blog/eval-skills)
and [revisiting prompts and skills](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra).
