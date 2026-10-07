# Client settings for resource allocation

Reviewed 2026-10-07. Read when translating a workload tier from
[resource allocation](resource-allocation.md) into an available client setting.
These are candidate starting points, not measured SECQUOIA optima or minimum
requirements. Preserve explicit user model/effort choices; this mapping does not
switch the primary agent automatically.

| Workload | Codex candidate | Claude Code candidate |
|---|---|---|
| Ordinary | GPT-6.1 Sol, `medium` | Opus 5.5, `medium` |
| Substantive | GPT-6.1 Sol, `high` | Opus 5.5, `high` |
| Exceptional | GPT-6 Astra, `high`; evaluate `xhigh` when useful | Opus 5.5, `high`; evaluate `xhigh` when useful |

Effort labels are not equivalent across models or vendors. Compare representative
tasks before claiming a gain from `xhigh` or higher effort; an existing setting is
not evidence that it is necessary. Other available models remain candidates.
See [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra),
[reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning), and
[Opus effort calibration](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5).

## Codex controls

Use the current runtime's supported spawn fields for helper model and reasoning
effort; prose requests alone do not configure a running agent. Where exposed,
full-history forks inherit the parent settings and reject overrides; use a
supported fresh or bounded-history fork when requesting different settings.

In the documented configuration flow, custom agent-file values override explicit
spawn values, then `[agents]` defaults, then parent settings. If an explicit spawn
or `[agents]` default selects a model and neither supplies an effort, use that
model's default effort. A custom file changing only the model preserves the
previously resolved effort.
Check model support and the actual client/tool contract before requesting a pair.
See [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).

## Claude Code controls

The Agent tool can request a helper model but has no per-call effort field.
Model resolution normally checks the call, helper definition, subagent-model
environment setting, then parent; forced settings or model availability can
override the request. A helper definition can set `effort`; otherwise the helper
uses session effort, subject to the effort environment override. Do not infer an
applied effort solely from a different model's saved settings.
See [Claude subagents](https://code.claude.com/docs/en/sub-agents).

Session model/effort controls and saved per-model settings belong to the client.
The `ultrathink` keyword adds an instruction for that turn; it does **not** change
the effort value sent to the API. See
[Claude model and effort controls](https://code.claude.com/docs/en/model-config).

## Applying and reporting a request

Distinguish requested settings from client-reported settings; missing values stay
unknown. Client reports do not independently prove every API turn's applied value.
Do not claim an override succeeded from its prompt alone. Report a material
substitution or unavailable control, and use the resource guide's fallback without
changing scope or required verification. Routine solo work needs no new metadata log.

Keep optional client-specific configuration in its supported configuration or
sidecar. Do not add model, effort, or fork fields to shared skill frontmatter that
another consumer does not support. Do not edit saved settings or install helper
definitions as a workflow side effect; an explicit configuration request is a
separate task. Recheck the linked documentation when updating this dated mapping
or encountering a different runtime contract.
