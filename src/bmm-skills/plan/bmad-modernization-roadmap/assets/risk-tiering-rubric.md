# Risk-Tiering Rubric

Used at Step 3 (strategy per component) to assign a risk tier to each modernization decision. Override this file in team/user TOML to add axes (e.g. regulatory exposure) or change weights — the shape is a starting point, not a fixed formula.

## Axes

| Axis | Low | Medium | High |
| --- | --- | --- | --- |
| **Business criticality** | Internal tool, low usage | Customer-facing, moderate volume | Revenue-critical or compliance-bound |
| **Blast radius** | Isolated component, few consumers | Several internal consumers | Widely depended-on, cross-team |
| **Rollback difficulty** | Feature-flaggable, instant revert | Requires redeploy, minutes of downtime | Data migration involved, rollback is lossy or slow |

## Tiering

Take the highest axis score, not the average — a component that's low-criticality but has a lossy-rollback data migration is High tier, not Medium. A single hard-to-reverse axis dominates the risk regardless of the others.

- **Low tier** — all three axes Low. Safe to batch into a larger wave; parallel execution is fine.
- **Medium tier** — any one axis Medium, none High. Sequence with a clear rollback plan; can run alongside other Medium/Low work in the same wave.
- **High tier** — any one axis High. Gets its own wave or a clearly isolated slot within one, an explicit rollback plan logged before the wave starts, and — where the org's `persistent_facts` name a change-freeze window — scheduling outside it.

## Using the tier

The tier feeds two things directly: how much isolation a wave needs (a High-tier component doesn't share a wave with unrelated risky work) and how much decommission rigor applies (a High-tier retirement needs every row in Decommission Criteria verified before close, not just asserted).
