# Client settings for resource allocation

Reviewed 2026-11-14. Read when translating a workload tier from
[resource allocation](resource-allocation.md) into an available client setting.
These are candidate starting points, not measured SECQUOIA optima or minimum
requirements. Preserve explicit user model/effort choices; this mapping does not
switch the primary agent automatically.

| Workload | Codex candidate | Claude Code candidate | Antigravity candidate |
|---|---|---|---|
| Ordinary | GPT-6.1 Sol, `medium` | Opus 5.5, `medium` | Gemini 3.8 Flash |
| Substantive | GPT-6.1 Sol, `high` | Opus 5.5, `high` | Gemini 3.8 Flash (High) or Gemini 4 Argon |
| Exceptional | Evaluate GPT-6 Astra at `high` or `xhigh` when justified | Retain Opus 5.5 at `high` pending comparison; candidates: `xhigh`, or Fable 5.1 when available and within billing authorization | Gemini 4 Argon, Gemini 4 Carbon, or Gemini 4 Hydrogen |

Effort labels are not equivalent across models or vendors. Compare representative
tasks before claiming a gain from `xhigh` or higher effort; an existing setting is
not evidence that it is necessary. Exceptional describes the workload, not an
automatic escalation. Other available models remain candidates. Fable is a
candidate for demanding work or when Opus at higher effort falls short; see
[Claude model selection](https://platform.claude.com/docs/en/models/overview).
See [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra),
[reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning), and
[Opus effort calibration](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5).

## Codex controls

Use the current runtime's supported spawn fields for helper model and reasoning
effort; prose requests alone do not configure a running agent. Runtime instructions
observed in the reviewed Codex session require full-history forks to inherit the
parent settings and reject overrides, with overrides available for fresh or
bounded-history forks. This is a runtime observation, not a claim from the public
subagents page; recheck the active tool contract before using a different setting.

In the documented configuration flow, custom agent-file values override explicit
spawn values, then `[agents]` defaults, then parent settings. If an explicit spawn
or `[agents]` default selects a model and neither supplies an effort, use that
model's default effort. A custom file changing only the model preserves the
previously resolved effort.
Check model support and the actual client/tool contract before requesting a pair.
See [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).

Use the active session's reported capacity and counting convention. The reviewed
runtime reported four total slots including the primary; that is an observation,
not a portable default. A terminal binary may differ from the interactive client;
check the client that will actually execute the request, not only the one on PATH.

## Claude Code controls

The Agent tool can request a helper model but has no per-call effort field.
Model resolution normally checks the call, helper definition, subagent-model
environment setting, then parent; forced settings or model availability can
override the request. A helper definition's `effort` overrides the session level
but not the effort environment override. This suggests session inheritance when
omitted, but the documentation does not establish the effort for a helper on a
different model. Keep unreported helper effort unknown; a different model's saved
settings alone do not establish what ran.
See [Claude subagents](https://code.claude.com/docs/en/sub-agents).

That page documents defaults of 20 concurrent subagents and three nesting layers,
not a task allowance. At the depth limit, Agent is withheld except for forks, where
it remains listed but spawning fails. A concurrency-limit error says not to retry.
The concurrency guard has exceptions (including ultracode and resumed helpers),
so it does not enforce the skill's budget. Check current runtime limits separately.

Opus 5.5 requires Claude Code 2.1.280+, Sonnet 5.5 requires 2.1.284+, and Fable 5.1
requires 2.1.257+. Check the executing client and provider support before requesting
a model; an installed terminal client and an IDE extension can differ. Do not
upgrade clients as a workflow side effect. Fable can consume separately billed
usage credits, and headless or SDK requests may bill without an interactive prompt.
Apply the resource guide's existing-authorization rule before selecting it; see
[Claude versions and billing](https://code.claude.com/docs/en/model-config).

Session model/effort controls and saved per-model settings belong to the client.
The `ultrathink` keyword adds an instruction for that turn; it does **not** change
the effort value sent to the API. See
[Claude model and effort controls](https://code.claude.com/docs/en/model-config).

## Antigravity controls

A requested reviewer missing from the active client's catalog may be available
through another installed client. Check those catalogs before reporting it
unavailable. On 2026-11-14 (`agy` 1.5.9), `agy models` listed
`gemini-3.8-flash-{low,medium,high}`, `gemini-4-argon-{low,medium,high}`,
`gemini-4-carbon-{low,medium,high}`, `gemini-4-hydrogen-{low,medium,high,xhigh}`,
orchestrator aliases (`gemini-pro-orchestrator`, `gemini-pro-orchestrator-argon`),
and hosted third-party models (`claude-sonnet-4-6`, `claude-opus-4-6-thinking`,
`gpt-oss-120b-medium`). Recheck that live catalog and select the exact ID with
`agy --model <id>` (with `--effort low|medium|high|xhigh|max` where supported);
for a model-specific Carbon or Hydrogen request, do not infer its identity from
a `pro` or orchestrator alias. Keep requested and client-reported identities
distinct as described below.

Antigravity's `run_command` tool accepts `{CommandLine, IsDaemon, WaitMsBeforeAsync, toolSummary}`
(there is no model-supplied `BypassSandbox` argument). Terminal sandboxing
(`--sandbox` or project Sandbox Mode), non-workspace file access, and external
network access (`gh`, git remotes) are governed by client/project permission
policies and runtime approval prompts. Each `run_command` executes in a fresh
shell session (working-directory changes and exported variables do not persist
across calls); backgrounded commands notify reactively on completion without
polling, and delayed timers use `schedule` rather than shell `sleep`.

For headless `agy`, inspect startup warnings before treating a requested mode as
an applied restriction. An observed invocation on 2026-11-05 warned that
`--mode plan` has no effect with `--disable-slash-commands`; do not count that
combination as read-only enforcement. Recheck the installed client's behavior
and retain sandboxing and supported tool or filesystem restrictions when
enforcement is required. A no-tools prompt or a response reporting no tools does
not establish which permissions were available.

Subagents in Antigravity are invoked via `invoke_subagent` with explicit parameters:
- `Model`: `inherit` (default, keeping the active session model), `flash_lite`, `flash`, or `pro` (for larger reasoning review and complex verification tasks). Native `swarm` (`action: "models"` / `"add"`) additionally accepts exact catalog model IDs when multi-worker board coordination or exact helper model pinning is explicitly warranted.
- `Workspace`: `inherit`, `branch` (isolated copy/branch), or `share` (shared repository worktree).
- Coordinator-worker communication uses `send_message` with reactive notifications (no polling needed).

Skills are discovered via `~/.gemini/config/skills/` globally, `.agents/skills/` in workspaces, or declared in `skills.json`. Lifecycle hooks live in `~/.gemini/config/hooks.json` or `.agents/hooks.json` under named hook keys (`PreToolUse` and `PostToolUse` grouped under `"matcher": "run_command"`; `SessionStart` and `Stop` as flat handler lists).

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
