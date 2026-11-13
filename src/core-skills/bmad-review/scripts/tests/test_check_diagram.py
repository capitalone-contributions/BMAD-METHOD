#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for check_diagram.py.

Run: uv run --python 3.11 src/core-skills/bmad-review/scripts/tests/test_check_diagram.py

The artifact under test: a document whose diagram and tables agree lints empty; the
checker catches exactly the mechanical disagreements a prompt is unreliable at — a node
that appears in the graph but no table, self-edges, duplicate edges, orphans, and an empty
diagram block.

Stdlib only, like the other skill-local script tests, so it runs wherever `uv` can reach
a Python and never needs a package index.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_diagram import check, main

CLEAN = """# Payments Architecture

## Components

| Component | Owner |
| --- | --- |
| gateway | platform |
| ledger | payments |
| notifier | comms |

## Flow

```mermaid
graph LR
  gateway --> ledger
  ledger --> notifier
```
"""


class CheckDiagramTest(unittest.TestCase):
    def cats(self, result):
        return sorted(f["category"] for f in result["findings"])

    def test_agreeing_document_passes(self):
        result = check(CLEAN)
        self.assertTrue(result["ok"], result["findings"])
        self.assertEqual(result["total_findings"], 0)
        self.assertEqual(result["diagram_blocks"], 1)

    def test_node_missing_from_tables_caught(self):
        # `metrics` is in the graph but nobody declared it
        text = CLEAN.replace("  ledger --> notifier", "  ledger --> metrics")
        result = check(text)
        self.assertIn("undeclared_node", self.cats(result))
        self.assertTrue(any("metrics" in f["detail"] for f in result["findings"]))

    def test_table_row_missing_from_graph_is_not_flagged(self):
        # a table row no diagram draws is normal on real documents; whether the omission
        # matters is the lens's judgment call, not a set difference
        text = CLEAN.replace("| notifier | comms |\n", "| notifier | comms |\n| archiver | data |\n")
        result = check(text)
        self.assertNotIn("untraced_row", self.cats(result))

    def test_self_edge_caught(self):
        text = CLEAN.replace("  ledger --> notifier", "  ledger --> ledger")
        self.assertIn("self_edge", self.cats(check(text)))

    def test_duplicate_edge_caught(self):
        text = CLEAN.replace(
            "  gateway --> ledger", "  gateway --> ledger\n  gateway --> ledger"
        )
        self.assertIn("duplicate_edge", self.cats(check(text)))

    def test_orphan_node_caught(self):
        text = CLEAN.replace("```mermaid\ngraph LR\n", "```mermaid\ngraph LR\n  notifier[Notifier]\n")
        text = text.replace("  ledger --> notifier\n", "")
        self.assertIn("orphan_node", self.cats(check(text)))

    def test_empty_diagram_block_caught(self):
        text = CLEAN.replace("  gateway --> ledger\n  ledger --> notifier\n", "")
        self.assertIn("unparsed_diagram", self.cats(check(text)))

    def test_naming_style_differences_are_not_findings(self):
        # a table saying "Gateway" and a graph saying "gateway" is the same entity
        text = CLEAN.replace("| gateway | platform |", "| Gateway | platform |")
        result = check(text)
        self.assertEqual(result["total_findings"], 0, result["findings"])

    def test_mermaid_keywords_never_read_as_entities(self):
        text = CLEAN.replace(
            "```mermaid\ngraph LR\n",
            "```mermaid\nflowchart LR\n  subgraph core\n  end\n",
        )
        result = check(text)
        self.assertEqual(
            [f for f in result["findings"] if "subgraph" in f["detail"].lower()], []
        )

    def test_pipes_inside_code_blocks_are_not_tables(self):
        text = CLEAN + "\n```bash\ncat x | grep y\n```\n"
        result = check(text)
        self.assertEqual(result["total_findings"], 0, result["findings"])

    def test_document_with_no_diagram_is_silent(self):
        text = "# Doc\n\n| Component | Owner |\n| --- | --- |\n| gateway | platform |\n"
        result = check(text)
        self.assertTrue(result["ok"])
        self.assertEqual(result["diagram_blocks"], 0)

    def test_diagram_with_no_tables_still_checks_internals(self):
        # no tables to cross-check, but a self-edge is still a defect
        text = "# Doc\n\n```mermaid\ngraph LR\n  a --> a\n```\n"
        result = check(text)
        self.assertIn("self_edge", self.cats(result))
        self.assertNotIn("undeclared_node", self.cats(result))

    def test_sequence_participants_recognized(self):
        text = """# Seq

| Component | Owner |
| --- | --- |
| web | frontend |
| api | platform |

```mermaid
sequenceDiagram
  participant web
  participant api
  web ->> api: request
```
"""
        result = check(text)
        self.assertEqual(result["total_findings"], 0, result["findings"])

    def test_prose_tables_are_not_entity_lists(self):
        # an Assumptions table's first column is prose; treating each row as an entity
        # would invent a phantom "missing from the diagram" finding per assumption
        text = CLEAN + """
## Assumptions

| Assumption | If false |
| --- | --- |
| Reporting team owns the batch job | Scope grows by one component |

## Open Questions

| Question | Blocks |
| --- | --- |
| Does notifier have external subscribers? | notifier retirement |
"""
        result = check(text)
        self.assertEqual(result["total_findings"], 0, result["findings"])

    def test_graph_on_a_different_layer_is_not_cross_checked(self):
        # a build graph naming generated artifacts overlaps no table on purpose;
        # flagging every node would be noise
        text = CLEAN + """
## Build Graph

```mermaid
graph LR
  shared-lib --> gateway-v2
```
"""
        result = check(text)
        self.assertEqual(
            [f for f in result["findings"] if f["category"] == "undeclared_node"], []
        )

    def test_partial_overlap_still_flags_the_omission(self):
        # a graph that names two known components and one unknown is the real case
        text = CLEAN.replace("  ledger --> notifier", "  ledger --> notifier\n  notifier --> metrics")
        result = check(text)
        self.assertIn("undeclared_node", self.cats(result))
        self.assertTrue(any("metrics" in f["detail"] for f in result["findings"]))

    def test_decision_diamond_is_not_a_missing_component(self):
        # `gate{ok?}` is a mermaid rhombus — flow control, not a system component — so it
        # has no table row on purpose and must not be flagged as an undeclared node
        text = CLEAN.replace(
            "  ledger --> notifier",
            "  ledger --> gate{ok?}\n  gate -->|yes| notifier",
        )
        result = check(text)
        self.assertEqual([f for f in result["findings"] if "gate" in f["detail"]], [])

    def test_sequence_self_call_is_not_a_self_edge(self):
        # an object calling itself is idiomatic in a sequence diagram, not a defect
        text = """# Doc

```mermaid
sequenceDiagram
  participant api
  api->>api: validate locally
```
"""
        self.assertNotIn("self_edge", self.cats(check(text)))

    def test_state_self_transition_is_not_a_self_edge(self):
        # a retry loop transitioning back to the same state is idiomatic, not a defect
        text = """# Doc

```mermaid
stateDiagram-v2
  Retrying --> Retrying : retry attempt
```
"""
        self.assertNotIn("self_edge", self.cats(check(text)))

    def test_flowchart_self_edge_is_still_caught(self):
        # the exclusion is diagram-type-specific: a flowchart component depending on
        # itself is still a real defect
        text = "# Doc\n\n```mermaid\ngraph LR\n  a --> a\n```\n"
        self.assertIn("self_edge", self.cats(check(text)))

    def test_er_diagram_relationship_syntax_not_flagged_unparsed(self):
        # erDiagram relations (`||--o{`, etc.) aren't recognized by EDGE; an empty parse
        # there means "we don't understand this syntax", not "the author left it empty"
        text = """# Doc

```mermaid
erDiagram
    CUSTOMER ||--o{ ORDER : places
```
"""
        result = check(text)
        self.assertNotIn("unparsed_diagram", self.cats(result))

    def test_class_diagram_relationship_syntax_not_flagged_unparsed(self):
        text = """# Doc

```mermaid
classDiagram
    Animal *-- Dog : owns
```
"""
        result = check(text)
        self.assertNotIn("unparsed_diagram", self.cats(result))

    def test_empty_class_diagram_still_flagged_unparsed(self):
        # scoping down the relationship-syntax check must not swallow a truly empty block
        text = "# Doc\n\n```mermaid\nclassDiagram\n```\n"
        self.assertIn("unparsed_diagram", self.cats(check(text)))

    def test_empty_er_diagram_still_flagged_unparsed(self):
        # same exclusion, other diagram type, whitespace rather than nothing at all
        text = "# Doc\n\n```mermaid\nerDiagram\n   \n```\n"
        self.assertIn("unparsed_diagram", self.cats(check(text)))

    def test_plain_state_diagram_self_transition_is_not_a_self_edge(self):
        # the exclusion covers `stateDiagram` as well as `stateDiagram-v2`
        text = "# Doc\n\n```mermaid\nstateDiagram\n  Retrying --> Retrying : retry\n```\n"
        self.assertNotIn("self_edge", self.cats(check(text)))

    def test_self_edge_produced_by_a_chain_is_still_caught(self):
        # `a --> b --> b` only exposes its self-edge once chaining threads through both
        # hops — this is the chain logic and the self_edge check working together
        text = "# Doc\n\n```mermaid\ngraph LR\n  a --> b --> b\n```\n"
        self.assertIn("self_edge", self.cats(check(text)))

    def test_duplicate_edge_caught_across_different_arrow_spellings(self):
        # the same edge declared once plainly and once with an inline label must still
        # normalize to one duplicate, not two distinct edges
        text = "# Doc\n\n```mermaid\ngraph LR\n  a --> b\n  a-- again -->b\n```\n"
        self.assertIn("duplicate_edge", self.cats(check(text)))

    def test_hyphenated_label_text_does_not_break_parsing(self):
        # a label containing its own hyphen (`not-found`) must not be mistaken for a
        # second arrow token while scanning for the closing `-->`
        text = "# Doc\n\n```mermaid\ngraph LR\n  a-- not-found -->b\n```\n"
        result = check(text)
        self.assertEqual(result["total_findings"], 0, result["findings"])

    def test_gateway_diamond_mid_chain_still_excluded_and_still_connects(self):
        # a decision diamond as the middle hop of a chain must still thread the chain
        # through to the real target, and still not be cross-checked as a component
        text = """# Doc

| Component | Owner |
| --- | --- |
| ledger | payments |
| notifier | comms |

```mermaid
graph LR
  ledger --> gate{ok?} --> notifier
```
"""
        result = check(text)
        self.assertEqual(result["total_findings"], 0, result["findings"])

    def test_inline_label_without_pipe_is_a_real_edge(self):
        # `a-- text -->b` is valid mermaid edge-label syntax without the `|pipe|` form
        text = CLEAN.replace("  ledger --> notifier", "  ledger-- forwards to -->notifier")
        result = check(text)
        self.assertEqual(result["total_findings"], 0, result["findings"])

    def test_chained_edges_on_one_line_are_all_captured(self):
        # `a --> b --> c` declares two edges, not one — `metrics` must be seen even though
        # it only appears as the second hop
        text = CLEAN.replace("  ledger --> notifier", "  ledger --> notifier --> metrics")
        result = check(text)
        self.assertIn("undeclared_node", self.cats(result))
        self.assertTrue(any("metrics" in f["detail"] for f in result["findings"]))

    def test_missing_file_reports_error_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "out.json"
            self.assertEqual(main(["/nonexistent-doc.md", "-o", str(report)]), 0)
            payload = json.loads(report.read_text())
        self.assertFalse(payload["ok"])
        self.assertIn("not found", payload["error"])


if __name__ == "__main__":
    unittest.main()
