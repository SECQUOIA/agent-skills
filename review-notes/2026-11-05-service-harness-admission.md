# Service-harness admission lessons

An explicitly requested remote-run integration exposed an important boundary:
the experiment controller started solver cases as sibling user services. A
subreaper around only the controller would not own those workloads. The existing
launcher already documented service handoffs as outside its guarantee; the
integration route now explains where to place it before dispatch.

The core skill links a conditional service-harness reference. Launcher usage is
narrowed from wrapping the controller to wrapping the actual allocated workload.
No authorization, resource-exclusion, cancellation, persistence or conservative
recovery invariant is removed. The helper executable and its claim format are
unchanged. The new reference records admitted-start budgets, separate library
and solver threads, log joins and failure receipts, since silently changing any
of these can invalidate a scientific comparison.

The encounter ledger was inspected. Its two GitHub-write classifiers do not
measure these remote-run integration contracts; historical audit flags and mixed
runtime labels do not supply causal evidence for this change. Eligibility comes
from the explicit request and inspected service/descendant boundaries.

Validation and deployment evidence are recorded in the implementing commit.
The apply-conversation-lessons workflow itself is unchanged: its existing
eligibility, owner selection and local-only submission boundary already cover
this episode.

During host acceptance, automatic approval review rejected a broad raw-output
return. Setup verification needed only a strictly allowlisted receipt; that
safer export completed without returning raw commands, account paths, process
identities or license data. Retrieval guidance now distinguishes the minimum
evidence for the requested stage and rejects filename-only privacy inference.
It preserves existing agreed return authorization rather than adding a universal
confirmation step. The refusal itself is not evidence that every raw retrieval
is unauthorized or that the shared GitHub encounter classifiers detected a
remote-run violation.
