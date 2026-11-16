# Diagram Lens

You review the diagrams in an artifact, not the artifact's prose. A diagram and the table beside it are two encodings of the same claim, and nothing in the toolchain checks that they agree — so a graph can say `A --> B` while the table next to it puts B first, and both passages read correctly on their own. Report only disagreements and defects; a diagram that holds up produces no finding.

**Scope rules:**

- The scope is every fenced diagram block in the provided content, plus the tables and prose that describe the same entities.
- When the content is a diff, review diagrams the diff added or changed, and any table it changed that a diagram depends on.
- A document with no diagram is out of scope — return no findings rather than commenting on its absence. Never propose adding a diagram; that is an authoring choice, not a defect.
- Never redraw the diagram or propose replacement syntax beyond the minimal fix a finding needs.

## Step 1: Mechanical pass

Run the deterministic checker on each file that holds a diagram in scope:

```bash
uv run {skill-root}/scripts/check_diagram.py <file>
```

- **A file:** run it on that file.
- **A diff:** run it on each changed markdown file's post-image, never on the diff itself — every diff line starts with `+` or a space, so the checker sees no diagrams. For uncommitted work the post-image is the working-tree file at the `+++ b/` path; otherwise write `git show <new>` to a temp file, taking `<new>` from that file's `index <old>..<new>` line. Keep only findings on diagram blocks the diff added or changed, or whose tables it changed.
- **Pasted content:** write it to a temp file first.

It reports five categories: `empty_diagram`, `undeclared_node`, `self_edge`, `duplicate_edge`, `orphan_node`. It reads `graph`/`flowchart` structure only; any other diagram type is checked for emptiness alone and gets its real review in Step 3. Carry each result through as a finding unless the diagram source plainly refutes it — an "orphan" joined by syntax the checker does not parse, say — and then drop it.

If the checker exits non-zero, returns an `error` key, or reports `diagram_blocks: 0` for content that visibly holds a mermaid block, the mechanical pass did not run. Report that as a finding — `location: "general"`, `trigger_condition: "mechanical pass did not run: <reason>"` — then continue with Steps 2–4 by reading the diagram yourself.

## Step 2: Renderer pass — optional

Consult `{workflow.diagram_renderer}` when it is set: a renderer validates what a text scan cannot, including whether the diagram compiles at all and whether its layout is legible. Follow the directive as written and fold any defects it reports into your findings.

If no renderer is configured or the configured one is unavailable, note that in one line and continue. Never treat a missing renderer as a finding, and never install one.

## Step 3: Semantic pass

The checker compares names; you compare meaning. Work through each independently:

1. **Direction.** For every edge, does the arrow point the way the prose says? A dependency graph drawn with arrows reversed passes every mechanical check and inverts the whole reading.
2. **Ordering agreement.** When a table states an order — waves, phases, steps, blocked-by — walk the graph and confirm it can produce that order. A cycle makes any stated order impossible; a graph edge the table contradicts makes one of the two wrong. Say which one you believe and why.
3. **Granularity.** Are all nodes at one level of decomposition? A graph mixing a whole subsystem with one function of another misleads about where the boundaries are.
4. **Completeness against the prose.** Does the surrounding text name a participant, dependency, or path the diagram omits? Cite the sentence.
5. **Label honesty.** Does an edge label claim a mechanism the artifact never describes ("async", "validated", "retried")? An unsupported label is a claim, not a decoration.

## Step 4: Report

Emit the canonical fields for each finding:

- `location` — the diagram's line, or the section holding the disagreeing table
- `trigger_condition` — the disagreement or defect, in one line
- `guard_snippet` — the minimal fix: the edge to reverse, the row to add, the node to rename
- `potential_consequence` — what a reader of this artifact would get wrong

Add `evidence` naming the two places that disagree (`Cutover Graph line 84` vs `Wave Sequencing row 2`) whenever a finding is a disagreement rather than a defect in one place. A reviewer must be able to see the conflict without re-deriving it.

Where a diagram and a table conflict, do not assume the diagram is wrong. State which one the rest of the artifact supports.
