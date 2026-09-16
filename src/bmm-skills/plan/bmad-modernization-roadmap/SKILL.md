---
name: bmad-modernization-roadmap
description: 'Turn a legacy system''s current state and a target architecture into a phased, risk-tiered modernization roadmap — per-component strategy (rehost, replatform, refactor, rebuild, replace, retire), rollout mechanism (direct cutover, parallel-run validation, or progressive ramp), wave sequencing by real dependency, and decommission criteria. Use when the user says "modernize this", "modernization roadmap", "legacy migration plan", "migrate off X", "strangler fig this", or "decommission plan"'
---
# BMad Modernization Roadmap

## Overview

You produce a **modernization roadmap**: the bridge between what a system *is* and what it should *become*, expressed as sequenced, risk-tiered work rather than a wish list. This skill does not perform discovery or target-architecture design — those belong to `bmad-project-context` (current state) and `bmad-architecture` (target state), and re-implementing either here would drift out of sync with the real thing. What earns a place in the roadmap is the **diff and the plan**: which components move, under which strategy, in what order, and what "done" means for the thing being retired.

One test decides what belongs:

> Does moving this component block or unblock another? Sequence on that dependency only. Where no real dependency exists, say so and let the waves run in parallel — ordering that exists to "read well" invites a big-bang rewrite by accident.

Scope is deliberately **code and architecture modernization** — legacy stacks, monoliths, unsupported frameworks, tightly-coupled services. Process or tooling modernization (CI/CD, team workflow, dev tooling) is a different problem shape with no component inventory or target spine to diff against; point the user at a plain planning conversation or `bmad-correct-course` for that instead of forcing it through this shape.

## Conventions

- Bare paths resolve from the skill root; `{skill-root}` is this skill's installed directory.
- `{project-root}`-prefixed paths resolve from the project working directory.
- `{workflow.<name>}` resolves to fields in `customize.toml`; `{doc_workspace}` is the bound run folder.

## How you work

Every component that moves gets a **strategy** — Rehost, Replatform, Refactor, Rebuild, Replace, or Retire — and every strategy gets a **reason**: the load-bearing calls (why Refactor over Rebuild, why this pair moves together) are shown, not silently made, the same way `bmad-architecture` shows its load-bearing calls. Lay out the realistic alternatives and why one wins; that rationale lives in the memlog, never bloating the terse roadmap.

**Strategy and rollout mechanism are two different axes — decide them separately.** Strategy answers *what changes about the component*; rollout mechanism answers *how you prove the change is safe before it's fully live*: a direct cutover, a parallel-run validation phase before any traffic shifts, or a progressive percentage ramp with a rollback path at each step. The same strategy can pair with different mechanisms depending on whether the change is visible to the component's callers and how costly a bad cutover would be to detect and reverse. One test decides it: **if the contract changes underneath existing callers, or a bad cutover would be expensive to detect or reverse, validate before it's live and ramp gradually; if not, a direct cutover is proportionate and a parallel-run phase would just be overhead.**

A gap only counts if it's load-bearing: it blocks a capability, violates a target invariant (`AD` from the target spine), or carries a real compliance/EOL driver. "This uses an older pattern" is not by itself a gap — churn for its own sake is the failure mode this skill exists to avoid. When current and target genuinely don't conflict on a component, say so and leave it out of scope rather than manufacturing work.

Retirement is a first-class outcome, not an afterthought: every component marked Retire gets explicit decommission criteria (traffic drained, data migrated and verified, rollback window elapsed) before it's considered done. A roadmap that migrates without ever retiring anything usually means the modernization never actually lands — flag that pattern if you see it forming.

Two habits keep the roadmap falsifiable instead of aspirational: pair every assumption with the concrete consequence if it turns out false (not a bare list of things believed true), and pair every claimed guarantee (e.g. "safe to roll back," "no customer impact during validation") with the specific mechanism that provides it — a guarantee with no named mechanism behind it is a hope, not a decision.

## On Activation

**Forwarded activation:** if a caller invoked you with a stated intent and pre-resolved customization fields, honor them verbatim — skip your own intent inference, use the supplied values for those named fields, and resolve only the remaining fields from your own `customize.toml`.

1. Resolve customization: `uv run {project-root}/_bmad/scripts/resolve_customization.py --skill {skill-root} --project-root {project-root} --key workflow` (on failure, read `{skill-root}/customize.toml` directly, use defaults). Run `{workflow.activation_steps_prepend}`, then `{workflow.activation_steps_append}`. Hold `{workflow.persistent_facts}` as standing context and consult `{workflow.external_sources}` on demand.
2. Resolve config: `uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}` (merges `_bmad/config.toml`, `_bmad/config.user.toml`, and `_bmad/custom/` overrides). Resolve `{user_name}`, `{communication_language}`, `{document_output_language}`, `{project_name}`, `{planning_artifacts}`, and `{date}`; missing keys take neutral defaults, never block.
3. Headless → follow `references/headless.md` for the whole run. Otherwise greet `{user_name}` in `{communication_language}`.
4. Check prerequisites — **do not perform discovery or target design yourself**:
   - **Current state.** Look for a `bmad-project-context` block in `AGENTS.md`, or a current-state input supplied directly (a scan, an inventory, a prior roadmap's memlog). If neither exists, tell the user and offer to invoke the `bmad-project-context` skill first; proceed without it only if the user explicitly wants a narrower, conversation-scoped pass.
   - **Target state.** Look for `ARCHITECTURE-SPINE.md` or an equivalent target description supplied directly. If absent, offer to invoke the `bmad-architecture` skill first; proceed with a target expressed inline in conversation only for a single-component modernization where a full spine would be overkill.
5. If a run folder already exists under `{workflow.roadmap_output_path}` for this target, offer to resume from its memlog rather than restart.
6. If the real ask is discovery, target design, or turning already-scoped work into stories, invoke `bmad-project-context`, `bmad-architecture`, or `bmad-create-epics-and-stories` instead of proceeding here.
7. Detect intent: **Create**, **Update** (see **Update**), or **Validate** — critique an existing roadmap without changing it. Validate runs the gate and reports; it never edits the roadmap or appends to the memlog.

For a new roadmap, bind `{doc_workspace}` (see **Workspace**), seed `MODERNIZATION-ROADMAP.md` from `{workflow.roadmap_template}`, run `memlog.py init`, and tell the user the path.

## Workspace

`{doc_workspace}` = `{workflow.roadmap_output_path}/{workflow.run_folder_pattern}/`.

```text
{doc_workspace}/
  MODERNIZATION-ROADMAP.md   ← distilled from .memlog.md, never hand-edited
  .memlog.md                 ← canonical, append-only decision record
  reviews/                   ← one review-{slug}.md per gate lens; scratch, not deliverable
```

The memlog is the run's working memory — every inventoried unit, gap, strategy decision, and decommission criterion lands as one append-only line as the conversation unfolds. The roadmap file is **distilled from the memlog at the end**, not written as you go. Resume a prior run by reloading its memlog, never the rendered roadmap.

Writes go through the shared script (don't read the file back except on resume):

- `uv run {project-root}/_bmad/scripts/memlog.py init --workspace {doc_workspace} --field scope="…" --field current_state_source="…" --field target_state_source="…"`
- `uv run {project-root}/_bmad/scripts/memlog.py append --workspace {doc_workspace} --type <inventory|gap|decision|dependency|wave-criteria|decommission-criteria|assumption|question|event> --text "…"`

## Reviewer Gate

Used by Validate and Finalize. Mechanical floor first: `uv run {skill-root}/{workflow.roadmap_linter} --workspace {doc_workspace}` settles cutover cycles, orphaned components, retirements with no criteria, ramps with no advance/rollback thresholds, and surviving placeholders — reviewers then spend judgment on the semantic half. **Opt-in, lens-selectable** — reviewers are costly (parallel subagents). At **Finalize**, ask whether to run the gate; default offered, easy skip, and scale by stakes (a single-component migration may skip; a platform-wide roadmap earns the full menu). At **Validate** the user already opted in — skip that question. Headless never skips the gate. Menu: `{workflow.finalize_reviewers}` + ad-hoc lenses the roadmap's risk tiers warrant. Picked lenses dispatch as parallel subagents against `MODERNIZATION-ROADMAP.md` → each writes `{doc_workspace}/reviews/review-{slug}.md` and returns only a compact summary (verdict, top findings, path); the parent never holds full review text. Surface findings tiered: gate verdict, then critical + high, with medium/low rolled into a tail. At Finalize apply the clear fixes yourself and log each as a `decision` entry; under Validate, report and change nothing — write the report to `{workflow.validation_report_path}` when it is set, otherwise surface it in chat.

## The Operation

### Step 1 — Inventory components

Enumerate the units in scope (services, modules, libraries, infra pieces — whatever the current-state input resolves to). For each, capture: current stack/version, known EOL or support-window dates, coupling to other units, test-coverage signal, and why it's in scope at all (compliance driver, EOL, performance, cost, developer velocity). A unit with no driver behind it doesn't belong in scope — ask rather than include it by default. Log each as an `inventory` entry.

### Step 2 — Gap analysis

For each unit, diff current vs. target: paradigm mismatch, boundary violations, data-ownership conflicts, missing capabilities. Cite the target spine's `AD-n` a gap violates when one applies. Apply the load-bearing test from **How you work** — skip anything that's a stylistic difference rather than a real conflict. Log each as a `gap` entry.

### Step 3 — Strategy and rollout mechanism per component

For every unit with a gap, assign a strategy (Rehost / Replatform / Refactor / Rebuild / Replace / Retire), a rollout mechanism (direct cutover / parallel-run validation then cutover / progressive ramp with rollback steps — see **How you work** for the test), and a risk tier (max across business criticality, blast radius, and rollback difficulty — use `{workflow.risk_rubric}`). Show the alternatives considered and why this one wins. Log as `decision` entries, each naming the strategy, the rollout mechanism, the tier, and the rejected alternatives.

When the rollout mechanism includes a parallel-run or comparison phase, the thing doing the comparing is itself a component with a failure mode, not incidental plumbing: give it the same inventory and gap treatment as any other unit, and never let it silently drop the events it's supposed to be comparing. If it correlates two independent streams for the same logical event, key the match on a stable identity, not timestamp proximity, and log the correlation window and reconciliation rule as a `decision` entry.

### Step 4 — Sequencing

Two dependency graphs exist and must not be conflated: the **build graph** (which generated artifact or piece of tooling must exist before another can be built — e.g. a shared library before the integration that wires it in) and the **cutover graph** (which production component must migrate before another because they share data or a contract). A wave groups cutover-graph dependencies; the build graph informs what must be *ready* before a wave can start, not the wave's own ordering.

Group decisions into waves by real cutover-graph dependency only — log each real dependency as its own `dependency` entry (`unit A blocks unit B because …`, tagged `build` or `cutover`) so the roadmap's ordering is traceable, not asserted. Flag waves that can run in parallel.

For every wave using a progressive-ramp rollout mechanism, define the advance criteria (numeric, checked before moving to the next step — e.g. error rate no worse than baseline plus a stated margin, latency no worse than baseline) and the rollback triggers (numeric, monitored continuously during the step, distinct from the advance criteria because they fire mid-step rather than being checked once between steps). For every unit marked Retire, define decommission criteria (traffic drained, data migrated and verified, rollback window elapsed, downstream consumers migrated) and log as `decommission-criteria` entries — a retirement with no criteria is not yet a decision.

### Step 5 — Finalize

Render `MODERNIZATION-ROADMAP.md` from the memlog via `{workflow.roadmap_template}`. Run the **Reviewer Gate** and resolve its findings, then apply `{workflow.doc_standards}` to the rendered prose. Set the roadmap's own frontmatter `status: final`, `updated: {date}`. Run `{workflow.on_complete}`. Log `uv run {project-root}/_bmad/scripts/memlog.py append --workspace {doc_workspace} --type event --text "roadmap finalized"`.

Tell the user the roadmap's path, then offer to hand wave 1 to `bmad-create-epics-and-stories` — pass the roadmap path and the wave's scope; don't re-explain its contents. For a change discovered mid-execution of an already-approved wave, route to `bmad-correct-course` rather than re-running this skill from scratch.

## Update

Amend an existing roadmap in place: resume from its `.memlog.md` (the authority on inventory, gaps, and decisions already made), not the rendered file. Capture the change as new memlog entries — a re-tiered risk, a strategy reversal, a wave re-sequenced by a newly-discovered dependency — then re-render and close as in Finalize, gate included: an amendment that moves a component between waves is exactly when the mechanical floor earns its keep. Keep prior `decision` entries intact; a reversal is a new entry that supersedes the old one, never an edit to it.
