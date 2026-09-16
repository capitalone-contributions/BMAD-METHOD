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
        # `fraudcheck` is in the graph but nobody declared it
        text = CLEAN.replace("  ledger --> notifier", "  ledger --> fraudcheck")
        result = check(text)
        self.assertIn("undeclared_node", self.cats(result))
        self.assertTrue(any("fraudcheck" in f["detail"] for f in result["findings"]))

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
        text = CLEAN.replace("  ledger --> notifier", "  ledger --> notifier\n  notifier --> fraudcheck")
        result = check(text)
        self.assertIn("undeclared_node", self.cats(result))
        self.assertTrue(any("fraudcheck" in f["detail"] for f in result["findings"]))

    def test_missing_file_reports_error_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "out.json"
            self.assertEqual(main(["/nonexistent-doc.md", "-o", str(report)]), 0)
            payload = json.loads(report.read_text())
        self.assertFalse(payload["ok"])
        self.assertIn("not found", payload["error"])


if __name__ == "__main__":
    unittest.main()
