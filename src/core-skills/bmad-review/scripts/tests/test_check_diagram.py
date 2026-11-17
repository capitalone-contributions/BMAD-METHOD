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

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_diagram import check, main, parse_line

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

    def test_distinct_ids_differing_only_by_separator_are_not_a_self_edge(self):
        # mermaid treats `api_gw` and `api-gw` as different ids; `_norm` strips both `_`
        # and `-` for the (deliberately loose) table cross-check, but self-edge identity
        # must not use that same loose match or these collide into a false positive
        text = """```mermaid
graph LR
  api_gw --> api-gw
```
"""
        self.assertNotIn("self_edge", self.cats(check(text)))

    def test_differently_labeled_edges_are_not_duplicates(self):
        text = "```mermaid\ngraph LR\n  a -->|yes| b\n  a -->|retry| b\n```\n"
        self.assertNotIn("duplicate_edge", self.cats(check(text)))

    def test_identically_labeled_edges_are_still_a_duplicate(self):
        text = "```mermaid\ngraph LR\n  a-- x -->b\n  a-- x -->b\n```\n"
        self.assertIn("duplicate_edge", self.cats(check(text)))

    def test_orphan_node_caught(self):
        text = CLEAN.replace("```mermaid\ngraph LR\n", "```mermaid\ngraph LR\n  notifier[Notifier]\n")
        text = text.replace("  ledger --> notifier\n", "")
        self.assertIn("orphan_node", self.cats(check(text)))

    def test_empty_diagram_block_caught(self):
        text = CLEAN.replace("  gateway --> ledger\n  ledger --> notifier\n", "")
        self.assertIn("empty_diagram", self.cats(check(text)))

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
        self.assertEqual(result["findings"], [])

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

    def test_self_edge_produced_by_a_chain_is_still_caught(self):
        # `a --> b --> b` only exposes its self-edge once chaining threads through both
        # hops — this is the chain logic and the self_edge check working together
        text = "# Doc\n\n```mermaid\ngraph LR\n  a --> b --> b\n```\n"
        self.assertIn("self_edge", self.cats(check(text)))

    def test_duplicate_edge_caught_across_different_arrow_spellings(self):
        # the same unlabeled edge written with two different arrow lengths is still one
        # duplicate; a label would make it a distinct edge, so none is used here
        text = "# Doc\n\n```mermaid\ngraph LR\n  a --> b\n  a ---> b\n```\n"
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

    def test_non_flowchart_diagrams_get_no_structural_findings(self):
        # only graph/flowchart is a dependency graph; other mermaid syntax (self-calls,
        # repeated messages, activations, relations, `[*]`, C4, mindmap) is not checked
        bodies = {
            "participants": "sequenceDiagram\n  participant web\n  participant api\n  web ->> api: request",
            "self_call": "sequenceDiagram\n  participant api\n  api->>api: validate locally",
            "repeated_messages": "sequenceDiagram\n  api->>db: q1\n  api->>db: q2",
            "activation": "sequenceDiagram\n  api->>+db: q\n  db-->>-api: r",
            "frontmatter": "---\ntitle: x\n---\nsequenceDiagram\n  A->>A: self",
            "state_self": "stateDiagram-v2\n  Retrying --> Retrying : retry attempt",
            "plain_state_self": "stateDiagram\n  Retrying --> Retrying : retry",
            "state_star": "stateDiagram-v2\n  [*] --> Idle\n  Idle --> [*]",
            "er_relation": "erDiagram\n    CUSTOMER ||--o{ ORDER : places",
            "er_attributes": "erDiagram\n  CUSTOMER {\n    string name\n  }\n  CUSTOMER ||--o{ ORDER : places",
            # entities with no relations at all are a valid ER diagram, not an empty one
            "er_entity_only": "erDiagram\n  CUSTOMER",
            "er_entities_no_relations": "erDiagram\n  CUSTOMER {\n    string id PK\n  }\n  ORDER {\n    string id PK\n  }",
            "class_declaration_only": "classDiagram\n  class Animal",
            "class_relation": "classDiagram\n    Animal *-- Dog : owns",
            "c4": 'C4Context\n  Person(customer, "Customer")\n  Rel(customer, bank, "Uses")',
            "mindmap": "mindmap\n  root((Tools))\n    Pen[Pen]\n    Pencil",
        }
        tables = "| Component | Owner |\n| --- | --- |\n| web | x |\n| api | x |\n| CUSTOMER | x |\n"
        for name, body in bodies.items():
            with self.subTest(name):
                result = check(f"# Doc\n\n{tables}\n```mermaid\n{body}\n```\n")
                self.assertEqual(result["findings"], [])

    def test_block_with_nothing_beyond_its_directive_is_empty(self):
        # frontmatter, `%%` lines and blanks don't count as content, for any diagram type
        for body in ("classDiagram", "erDiagram\n   ", "---\ntitle: x\n---\nflowchart TD",
                     '%%{init: {"theme": "dark"}}%%\nsequenceDiagram'):
            with self.subTest(body):
                self.assertEqual(self.cats(check(f"```mermaid\n{body}\n```\n")), ["empty_diagram"])

    def test_directive_found_after_frontmatter_and_init(self):
        # a frontmatter or `%%{init}%%` header must not hide the flowchart directive
        for head in ("---\ntitle: x\n---\n", '%%{init: {"theme": "dark"}}%%\n'):
            with self.subTest(head):
                text = f"```mermaid\n{head}flowchart LR\n  a --> a\n```\n"
                self.assertEqual(self.cats(check(text)), ["self_edge"])

    def test_flowchart_link_syntax_is_parsed(self):
        # each of these is ordinary mermaid that the old arrow grammar misread or dropped;
        # node ids never end in `-`, so `A-->B-->C` can't yield a node `B--`
        ab = [("A", "B")]
        cases = {"A <--> B": ab, "A:::hot --> B": ab, "A ---> B": ab, "A ====> B": ab,
                 "A --o B": ab, "A --x B": ab, "A -. maybe .-> B": ab, "A e1@--> B": ab,
                 "A ~~~ B": ab, "A-->|sync|B": ab, "A --> |sync| B": ab, "A:::hot-->B": ab,
                 'A -->|"a | b"| B': ab,
                 "A--Yes-->B": ab, "A==go==>B": ab, "A-.retry.->B": ab, "A --oauth--> B": ab,
                 "A@{ shape: rect } --> B": ab, "A -- status == ok --> B": ab, "A -. a--b .-> B": ab,
                 "A[Order (legacy) Service] --> B": ab, "A{Is it [ok]?} --> B": ab,
                 "A --o B --> C": [("A", "B"), ("B", "C")], "A --x B --> C": [("A", "B"), ("B", "C")],
                 "A-->B-->C": [("A", "B"), ("B", "C")], "A & B --> C": [("A", "C"), ("B", "C")]}
        for line, edges in cases.items():
            with self.subTest(line):
                self.assertEqual(parse_line(line)[1], edges)
        # a line that is neither an edge nor a lone node group declares nothing
        self.assertEqual(parse_line("accTitle: Payments"), ([], [], []))

    def test_amp_and_nospace_chain_expand_to_real_edges(self):
        # `a & b --> c` is two edges and `a-->b-->c` is a->b, b->c, so a repeat is a duplicate
        for body in ("a & b --> c\n  a --> c", "a-->b-->c\n  a-->b"):
            with self.subTest(body):
                result = check(f"```mermaid\ngraph LR\n  {body}\n```\n")
                self.assertEqual(self.cats(result), ["duplicate_edge"])
                self.assertNotIn("b--", result["findings"][0]["detail"])

    def test_short_id_matched_by_its_label(self):
        # `osvc[Order Service]` is the table's "Order Service"; `mx[Metrics Exporter]` isn't
        text = CLEAN.replace("  ledger --> notifier", "  ledger --> osvc[Order Service]\n  osvc --> mx[Metrics Exporter]")
        text = text.replace("| notifier | comms |", "| Order Service | orders |")
        result = check(text)
        self.assertEqual(self.cats(result), ["undeclared_node"])
        self.assertIn("mx", result["findings"][0]["detail"])

    def test_label_punctuation_does_not_block_a_table_match(self):
        # `api[API (v2)]` and `gw["Gateway<br/>Kong"]` are the table's "API (v2)" and "Gateway"
        text = CLEAN.replace("  ledger --> notifier", '  ledger --> api[API (v2)]\n  gw["Gateway<br/>Kong"] --> ledger')
        text = text.replace("| notifier | comms |", "| API (v2) | platform |\n| Gateway | edge |")
        self.assertEqual(check(text)["findings"], [])

    def test_mermaid_forms_that_must_not_hide_a_defect(self):
        # each block repeats `a --> b`; none of these forms may stop the duplicate being seen
        heads = {
            "multi-line init": '%%{\n  init: { "theme": "dark" }\n}%%\nflowchart LR\n',
            "trailing semicolons": "graph LR;\n",
        }
        for name, head in heads.items():
            with self.subTest(name):
                text = f"```mermaid\n{head}  a --> b;\n  a --> b;\n```\n"
                self.assertIn("duplicate_edge", self.cats(check(text)))
        # a multi-line "`markdown string`" label still carries its edge
        md_string = '```mermaid\ngraph LR\n  a("`The **cat**\n  in the hat`") --> b\n  a --> b\n```\n'
        self.assertEqual(self.cats(check(md_string)), ["duplicate_edge"])
        # a lone node ending in `;` is still a declared node
        self.assertEqual(self.cats(check("```mermaid\ngraph LR\n  a --> b;\n  c[C];\n```\n")), ["orphan_node"])

    def test_names_that_must_not_match_a_table_row(self):
        # `C#` in a language table is not node `C`, and `e1@{ animate: true }` styles an edge
        lang = "| Language | Use |\n| --- | --- |\n| C# | api |\n\n```mermaid\ngraph LR\n  A --> B\n  B --> C\n```\n"
        self.assertEqual(check(lang)["findings"], [])
        anim = CLEAN.replace("  ledger --> notifier", "  ledger e1@--> notifier\n  e1@{ animate: true }")
        self.assertEqual(check(anim)["findings"], [])

    def test_label_match_alone_does_not_open_the_cross_check(self):
        # a stack table naming PostgreSQL doesn't make every node of a deployment view undeclared
        text = "| Stack | Version |\n| --- | --- |\n| PostgreSQL | 16 |\n\n```mermaid\ngraph LR\n  svc --> pg[(PostgreSQL)]\n  svc --> sqs\n```\n"
        self.assertEqual(check(text)["findings"], [])

    def test_node_on_an_unparsed_line_is_not_an_orphan(self):
        # `c` is used on a line the parser doesn't understand; a `style` line doesn't count
        base = "```mermaid\nflowchart LR\n  a --> b\n  c[C]\n  {}\n```\n"
        self.assertNotIn("orphan_node", self.cats(check(base.format("c -> a"))))
        self.assertIn("orphan_node", self.cats(check(base.format("style c fill:#f00"))))

    def test_edges_match_lint_roadmap_parser(self):
        # lint_roadmap.py keeps its own copy of this edge regex (skill scripts can't share
        # imports); every edge it finds on valid flowchart lines must be found here too
        path = (Path(__file__).resolve().parents[4]
                / "bmm-skills/plan/bmad-modernization-roadmap/scripts/lint_roadmap.py")
        spec = importlib.util.spec_from_file_location("lint_roadmap", path)
        lint = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lint)
        corpus = ["a --> b", "a -.-> b", "a ==> b", "a --- b", "a[A] --> b", "a(A) --> b[B]",
                  "gate{ok?} --> b", "a -->|yes| b", "a --> |yes| b", "a --> b --> c", "api-gw --> order.svc"]
        for line in corpus:
            with self.subTest(line):
                ours = parse_line(line)[1]
                for edge in lint.MERMAID_EDGE.findall(line):
                    self.assertIn(edge, ours)

    def test_missing_file_reports_error_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "out.json"
            self.assertEqual(main(["/nonexistent-doc.md", "-o", str(report)]), 0)
            payload = json.loads(report.read_text())
        self.assertFalse(payload["ok"])
        self.assertIn("not found", payload["error"])


if __name__ == "__main__":
    unittest.main()
