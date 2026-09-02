---
name: '{name}'
type: modernization-roadmap
scope: '{what system or set of components this roadmap governs}'
status: draft               # draft · final
created: '{date}'
updated: '{date}'
current_state_source: '{path to project-context / scan this diffs from}'
target_state_source: '{path to ARCHITECTURE-SPINE.md or equivalent this diffs against}'
---

# Modernization Roadmap — {name}

<!-- TEMPLATE GUIDE — act on these comments, then delete them; never emit a comment in the finished roadmap. This is a shape, not a script: keep only the sections this roadmap needs. A single-component migration may be just Inventory + one Wave; a platform-wide modernization earns the full shape. Decisions, not rationale (rationale lives in the memlog). -->

## Scope and Drivers

<!-- One paragraph: what's in scope, and the drivers pulling it toward modernization (EOL, compliance, cost, velocity, incident history). A component with no driver here doesn't belong in the inventory below. -->

## Component Inventory

<!-- Every unit in scope. Cut rows for anything with no gap against the target — this table is not a full asset registry. -->

| Component | Current stack/version | Driver | Coupling |
| --- | --- | --- | --- |
| {component} | {stack + version} | {EOL / compliance / cost / velocity} | {what it's coupled to} |

## Gap Analysis

<!-- One row per component with a real gap. Cite the target AD it violates when one applies. -->

| Component | Gap | Violates | Load-bearing because |
| --- | --- | --- | --- |
| {component} | {current vs target mismatch} | {AD-n or capability} | {why this blocks something, not just differs} |

## Strategy per Component

<!-- One block per component in scope. Alternatives considered are shown, not silently decided — this is where the load-bearing calls live. Strategy and rollout mechanism are separate axes; decide both. -->

### {component} — {Rehost | Replatform | Refactor | Rebuild | Replace | Retire}

- **Rollout mechanism:** {Direct cutover | Parallel-run validation then cutover | Progressive ramp with rollback steps}
- **Risk tier:** {tier, from risk_rubric}
- **Alternatives considered:** {other strategies and mechanisms weighed and why they lost}
- **Rationale:** {why this strategy, this mechanism, this tier}

## Validation Channels

<!-- Present only for components whose rollout mechanism is parallel-run or progressive-ramp with a comparison step. The channel doing the comparing is itself a component with a failure mode — give it the same rigor as anything else in scope. Cut this section if no component needs it. -->

| Component | Compares | Correlation key | Correlation window | On dropped/unmatched event |
| --- | --- | --- | --- | --- |
| {component} | {old path output vs new path output} | {stable identity, never timestamp} | {bounded window} | {reconciliation rule — never silently discarded} |

## Build Graph

<!-- Tooling/artifact build order — what must exist before something else can be built. Distinct from the cutover graph below; do not use this to sequence waves. Author as valid mermaid; cut if the roadmap doesn't generate its own tooling. -->

```mermaid
graph LR
```

## Cutover Graph

<!-- Real production dependencies only — each one is traceable to a memlog `dependency` entry tagged `cutover`. This graph, not the build graph, drives Wave Sequencing below. Author as valid mermaid; never an empty or placeholder graph. -->

```mermaid
graph LR
```

## Wave Sequencing

<!-- Waves grounded in the cutover graph above. Note which waves can run in parallel. -->

| Wave | Components | Blocked by | Can run in parallel with |
| --- | --- | --- | --- |
| {wave-n} | {components} | {upstream wave or "none"} | {other wave or "none"} |

## Wave Advance & Rollback Criteria

<!-- Present only for waves using a progressive-ramp rollout mechanism. Advance criteria are checked once before moving to the next step; rollback triggers are monitored continuously during the step — keep them in separate columns, they fire at different times. Numeric and falsifiable, never "make sure it's working." -->

| Wave / Step | Advance criteria (checked before next step) | Rollback triggers (monitored during the step) |
| --- | --- | --- |
| {wave-n / step} | {numeric threshold} | {numeric threshold, distinct from advance criteria} |

## Decommission Criteria

<!-- Every component marked Retire above gets a row. A retirement with no row here is not yet a decision. -->

| Component | Traffic drained | Data migrated & verified | Rollback window elapsed | Downstream consumers migrated |
| --- | --- | --- | --- | --- |
| {component} | {condition} | {condition} | {condition} | {condition} |

## Assumptions

<!-- Every assumption paired with its concrete consequence if false — never a bare list of things believed true. -->

| Assumption | If false |
| --- | --- |
| {assumption} | {concrete consequence, not "risk increases"} |

## Open Questions

<!-- Real gaps needing a human decision — never invented answers. -->

