# Worker publication observations

Use this view when investigating whether assigned workers attempted remote writes:

```bash
python -B <skill>/scripts/encounter_ledger.py report --remote-write-audit --json
```

The existing optional hooks record recognized `PreToolUse` attempts in a separate
table. This adds no publication rule, denial, or hook installation. Existing
GitHub preflight/readback decisions remain unchanged in both audit and enforce
modes. Default `report --json` retains its existing rule-candidate list.

## Interpret the evidence

- `gh-write` uses the existing GitHub mutation classifier, excluding the local
  `gh repo set-default` operation. Audit preprocessing excludes shell comments
  and simple literal heredoc data before examining executable command segments;
  it does not alter the shared enforcement classifier. `git-push` recognizes common literal commands,
  Git global options, push flags, supported execution wrappers, and inline shell
  commands. Recognized dry runs and help requests do not count as pushes.
- These are attempts, including commands subsequently denied or failed. A push
  to a local bare repository also counts: the classifier does not establish the
  destination, successful publication, network access, or authorization.
- `reported_role=worker` requires the Claude client label and a nonempty string
  `agent_id`. This follows Claude's documented subagent tool-event field, but
  neither the label nor field verifies authority. `agent_type` alone does not
  establish a worker role. [Claude hook input fields](https://code.claude.com/docs/en/hooks#common-input-fields)
- Missing metadata stays `unknown`; it does not prove a solo/root agent. Other
  clients' `agent_id` fields are marked unvalidated and retain unknown role until
  their actual payload contract is verified. Existing activity keys named `root`
  are bookkeeping defaults and are not publication evidence.
- An explicitly authorized worker publisher may legitimately produce these
  observations. The runner does not read assignments, infer publisher grants, or
  assess authorization. Observations never contribute to rule violations,
  opportunities, or the lessons threshold.

Coverage is bounded. Scripts, Git aliases, dynamic Git arguments, unsupported
options/wrappers, and tool channels that do not deliver these hook events can
escape observation. Heredoc delimiters must be plain identifiers or wholly quoted
literal words; unsupported or unterminated heredocs skip recognition for that
shell command. Expansions within heredoc bodies and here-strings are outside
coverage. Commands following a supported heredoc and substitutions outside its
body remain observable. The GitHub classifier has its own documented limitations.
An empty report is not proof that no remote writes occurred. Runtime/model labels
describe the observed event only and cannot justify a model-wide prohibition.

The audit stores hashed lifecycle identifiers, client/role provenance, operation
kind, skill revision, and explicit runtime labels. It does not store commands,
push arguments, prompts, transcripts, or raw lifecycle identifiers. Repeated
events with a tool ID deduplicate per session, agent, and operation kind; events
without tool IDs cannot deduplicate. The same tool can contribute both operation
kinds. Observations older than 30 days are pruned when the hook database opens
for writing; read-only reports never migrate or prune the database.

## Before adding enforcement

Validate real main-agent and worker payloads for each supported client, including
missing/malformed metadata, tool matching, and lifecycle correlation. Separately
design and test trusted publisher grants scoped to the task and target, their
handoff/revocation, command coverage, and explicitly authorized worker publishing.
Do not turn an observed worker attempt into a denial or treat absent metadata as
a grant. Runtime permissions should constrain workers where available; this
classifier is not a universal security boundary.
