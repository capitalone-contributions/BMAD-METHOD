# Headless

No interactive user: infer everything, ask nothing, but never invent — record inferences as `assumptions[]` and gaps that need a human as `open_questions[]`. Detect headless from a `headless: true` flag, a non-interactive / no-TTY invocation, an activation hook that declares it, or a first message that pre-supplies all inputs and asks for an artifact path back; when ambiguous, default to interactive.

## Inputs the caller is expected to provide

- `intent` — `"create"` or `"update"`. If absent, infer from whether a roadmap already exists at the target workspace.
- **Current-state source** — a path to a `bmad-project-context`-maintained `AGENTS.md`, or an inline current-state description. If absent and undiscoverable, do not scan the codebase yourself — record `open_questions[]: "no current-state source; run bmad-project-context first"` and proceed only with what the conversation supplies.
- **Target-state source** — a path to `ARCHITECTURE-SPINE.md` or an inline target description. If absent, same handling: record the gap rather than inventing a target.
- `doc_workspace` if a specific run folder is required (otherwise the workflow binds the default from `{workflow.roadmap_output_path}`).
- For **update**: the existing roadmap's workspace path and a change signal (what changed and why).

## General

Do not ask. Complete the intent using what is provided, what exists in `{doc_workspace}`, or what you can discover from the named sources. Do not invent component scope, drivers, or strategy rationale to fill a gap — record it as an `assumption` or `open_question` instead.

Use `status: "partial"` when the roadmap was produced but `open_questions[]` is non-empty or a critical input (current or target state) was missing and worked around. Use `status: "blocked"` when neither current nor target state could be resolved at all — no roadmap is produced.

End with JSON only, omitting keys for artifacts not produced:

```json
{
  "status": "complete | partial | blocked",
  "intent": "create | update",
  "doc_workspace": "<resolved run folder>",
  "roadmap": "{doc_workspace}/MODERNIZATION-ROADMAP.md",
  "memlog": "{doc_workspace}/.memlog.md",
  "assumptions": [],
  "open_questions": [],
  "reason": "<one line, only when blocked>"
}
```

`complete` stands alone · `partial` means review before downstream use · `blocked` means no roadmap produced — return only `status`, `intent`, `reason`, and `doc_workspace` (if bound).
