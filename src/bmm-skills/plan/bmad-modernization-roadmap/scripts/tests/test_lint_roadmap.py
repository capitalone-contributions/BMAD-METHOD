#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for lint_roadmap.py.

Run: uv run --python 3.11 src/bmm-skills/plan/bmad-modernization-roadmap/scripts/tests/test_lint_roadmap.py

The roadmap under test: a clean roadmap lints empty; the linter catches exactly the
mechanical defects a prompt is unreliable at — a cutover cycle, a Retire with no
decommission criteria, a ramp with no thresholds, components that fall between
sections, and literal placeholders that survived into the final document.

Stdlib only, like the other skill-local script tests, so it runs wherever `uv` can
reach a Python and never needs a package index.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lint_roadmap import lint, main

CLEAN = """---
name: 'Demo Modernization'
status: final
---

## Component Inventory

| Component | Current stack/version | Driver | Coupling |
| --- | --- | --- | --- |
| claims-intake | WebLogic 12c | EOL 2027-03 | claims-db |
| claims-db | Oracle 11g | EOL | — |
| notify-svc | Java 8 / Quartz | velocity | claims-intake |

## Gap Analysis

| Component | Gap | Violates | Load-bearing because |
| --- | --- | --- | --- |
| claims-intake | No horizontal scale | AD-3 | Blocks peak-load capability |
| claims-db | No logical replication | AD-7 | Blocks zero-downtime cutover |
| notify-svc | Unsupported scheduler | AD-9 | Target has native eventing |

## Strategy per Component

### claims-intake — Refactor

- **Rollout mechanism:** Progressive ramp with rollback steps
- **Risk tier:** High

### claims-db — Replatform

- **Rollout mechanism:** Direct cutover
- **Risk tier:** Medium

### notify-svc — Retire

- **Rollout mechanism:** Direct cutover
- **Risk tier:** Low

## Build Graph

```mermaid
graph LR
  shared-lib --> claims-intake-v2
```

## Cutover Graph

```mermaid
graph LR
  claims-db --> claims-intake
  claims-intake --> notify-svc
```

## Wave Sequencing

| Wave | Components | Blocked by | Can run in parallel with |
| --- | --- | --- | --- |
| wave-1 | claims-db | none | none |
| wave-2 | claims-intake | wave-1 | none |

## Wave Advance & Rollback Criteria

| Wave / Step | Advance criteria (checked before next step) | Rollback triggers (monitored during the step) |
| --- | --- | --- |
| wave-2 / 10% | Error rate <= baseline + 0.1% | Error rate > baseline + 0.5% |

## Decommission Criteria

| Component | Traffic drained | Data migrated & verified | Rollback window elapsed | Downstream consumers migrated |
| --- | --- | --- | --- | --- |
| notify-svc | 0 jobs for 7d | Schedules ported, parity verified | 14d elapsed | claims-intake on native eventing |
"""

DECOMMISSION_ROW = (
    "| notify-svc | 0 jobs for 7d | Schedules ported, parity verified"
    " | 14d elapsed | claims-intake on native eventing |\n"
)
RAMP_ROW = (
    "| wave-2 / 10% | Error rate <= baseline + 0.1%"
    " | Error rate > baseline + 0.5% |"
)


def cats(result):
    return sorted(f["category"] for f in result["findings"])


class LintRoadmapTest(unittest.TestCase):
    def test_clean_roadmap_passes(self):
        result = lint(CLEAN)
        self.assertTrue(result["ok"], result["findings"])
        self.assertEqual(result["total_findings"], 0)

    def test_cutover_cycle_caught(self):
        text = CLEAN.replace(
            "  claims-intake --> notify-svc",
            "  claims-intake --> notify-svc\n  notify-svc --> claims-db",
        )
        self.assertIn("wave_cycle", cats(lint(text)))

    def test_retire_without_decommission_criteria_caught(self):
        text = CLEAN.replace(DECOMMISSION_ROW, "")
        self.assertIn("retire_no_criteria", cats(lint(text)))

    def test_progressive_ramp_without_criteria_caught(self):
        text = CLEAN.replace(RAMP_ROW + "\n", "")
        self.assertIn("ramp_no_criteria", cats(lint(text)))

    def test_identical_advance_and_rollback_thresholds_caught(self):
        # advance and rollback fire at different times; identical values mean one is wrong
        text = CLEAN.replace(
            RAMP_ROW,
            "| wave-2 / 10% | Error rate <= baseline + 0.1%"
            " | Error rate <= baseline + 0.1% |",
        )
        self.assertIn("ramp_no_criteria", cats(lint(text)))

    def test_gap_without_strategy_caught(self):
        text = CLEAN.replace(
            "### claims-db — Replatform\n\n"
            "- **Rollout mechanism:** Direct cutover\n"
            "- **Risk tier:** Medium\n\n",
            "",
        )
        self.assertIn("orphan_component", cats(lint(text)))

    def test_unknown_component_reported_once(self):
        # a component in Gap Analysis but in neither Inventory nor Strategy is one defect,
        # not two — a linter that double-reports trains reviewers to skim it
        text = CLEAN.replace(
            "| notify-svc | Unsupported scheduler | AD-9 | Target has native eventing |",
            "| notify-svc | Unsupported scheduler | AD-9 | Target has native eventing |\n"
            "| ghost-svc | Unsupported runtime | AD-9 | Blocks the wave |",
        )
        ghost = [f for f in lint(text)["findings"] if "ghost-svc" in f["detail"]]
        self.assertEqual(len(ghost), 1, ghost)

    def test_strategy_without_gap_not_flagged(self):
        # the skill requires a strategy for every unit WITH a gap, not the converse —
        # flagging the reverse would enforce a rule the roadmap never states
        text = CLEAN.replace(
            "| notify-svc | Unsupported scheduler | AD-9 | Target has native eventing |\n",
            "",
        )
        self.assertNotIn("orphan_component", cats(lint(text)))

    def test_empty_cutover_graph_caught(self):
        text = CLEAN.replace(
            "  claims-db --> claims-intake\n  claims-intake --> notify-svc\n", ""
        )
        self.assertIn("empty_graph", cats(lint(text)))

    def test_placeholder_marker_caught(self):
        text = CLEAN.replace("Blocks peak-load capability", "TBD")
        self.assertIn("placeholder", cats(lint(text)))

    def test_mermaid_node_names_not_read_as_components(self):
        # graph node ids live in a fenced block; they must not surface as orphan components
        findings = lint(CLEAN)["findings"]
        self.assertEqual([f for f in findings if "shared-lib" in f["detail"]], [])

    def test_cycle_detected_through_labeled_edges(self):
        # a labeled edge (`a -->|why| b`) must still parse — otherwise the cycle is missed
        # and the block is falsely reported empty
        text = CLEAN.replace(
            "  claims-db --> claims-intake\n  claims-intake --> notify-svc",
            "  claims-db -->|shares data| claims-intake\n"
            "  claims-intake -->|calls| claims-db",
        )
        result = lint(text)
        self.assertIn("wave_cycle", cats(result))
        self.assertNotIn("empty_graph", cats(result))

    def test_cycle_detected_through_node_shapes(self):
        # a node shape on the source (`a[Label] --> b`) must not defeat edge parsing
        text = CLEAN.replace(
            "  claims-db --> claims-intake\n  claims-intake --> notify-svc",
            "  claims-db[Claims DB] --> claims-intake\n"
            "  claims-intake --> claims-db",
        )
        self.assertIn("wave_cycle", cats(lint(text)))

    def test_backticked_names_match_plain_table_rows(self):
        # `notify-svc` in a heading is the same component as notify-svc in a table;
        # normalization must prevent false retire_no_criteria / orphan findings
        text = CLEAN.replace("### notify-svc — Retire", "### `notify-svc` — Retire")
        result = lint(text)
        self.assertNotIn("retire_no_criteria", cats(result))
        self.assertNotIn("orphan_component", cats(result))

    def test_ramp_component_in_uncovered_wave_is_flagged(self):
        # claims-intake (progressive ramp) sits in wave-2, which has a criteria row.
        # Move it to a wave with none: the ramp must be flagged even though wave-2 is covered.
        text = CLEAN.replace(
            "| wave-2 | claims-intake | wave-1 | none |",
            "| wave-3 | claims-intake | wave-1 | none |",
        )
        self.assertIn("ramp_no_criteria", cats(lint(text)))

    def test_missing_roadmap_reports_error_not_crash(self):
        # exit code is always 0 — findings and errors travel in the JSON
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "out.json"
            self.assertEqual(
                main(["--workspace", "/nonexistent-roadmap-dir", "-o", str(report)]), 0
            )
            payload = json.loads(report.read_text())
        self.assertFalse(payload["ok"])
        self.assertIn("not found", payload["error"])


if __name__ == "__main__":
    unittest.main()
