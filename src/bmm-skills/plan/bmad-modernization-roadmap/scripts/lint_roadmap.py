#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""lint-roadmap — the mechanical half of roadmap integrity, done deterministically.

LLMs write a cutover graph in one place and a wave table in another, then miss that the
two disagree; a graph walk does not. This linter owns the checks a script does better
than a prompt, and leaves the semantic half (is this wave order justified? is the
rollback real?) to the Reviewer Gate's lenses.

It reads MODERNIZATION-ROADMAP.md from a workspace and reports, as compact JSON on stdout:

  - placeholder            literal TBD / TODO / unfilled {template-token}
  - retire_no_criteria     a component marked Retire with no Decommission Criteria row
  - ramp_no_criteria       a progressive ramp with no advance/rollback thresholds, or
                           thresholds identical to each other
  - wave_cycle             a dependency cycle in the cutover graph — no wave can go first
  - empty_graph            a mermaid block that declares no edges
  - orphan_component       a component that falls between Inventory, Gap Analysis, and Strategy

Fenced code blocks are blanked (replaced with equal-count blank lines) before scanning, so
mermaid graphs don't trip false positives AND reported line numbers still line up with the
real file. Reported lines are absolute file lines (frontmatter offset added). Exit code is
always 0 — findings travel in the JSON; the caller (the Reviewer Gate) decides what to do
with them.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROADMAP = "MODERNIZATION-ROADMAP.md"

HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)
FENCE = re.compile(r"```.*?```", re.DOTALL)
PLACEHOLDER_WORD = re.compile(r"\b(TBD|TODO|FIXME|XXX)\b")
TEMPLATE_TOKEN = re.compile(r"\{[a-z_][a-z0-9_ /.-]*\}")
STRATEGY_HEADING = re.compile(r"^###\s+(.+?)\s+—\s+(Rehost|Replatform|Refactor|Rebuild|Replace|Retire)\s*$", re.M)
MERMAID_EDGE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*-->\s*([A-Za-z0-9_.-]+)\s*$", re.M)


def split_frontmatter(text: str) -> tuple[str, str, int]:
    lines = text.split("\n")
    if lines and lines[0] == "---":
        for i in range(1, len(lines)):
            if lines[i] == "---":
                return "\n".join(lines[1:i]), "\n".join(lines[i + 1:]), i + 1
    return "", text, 0


def blank_fences(text: str) -> str:
    return FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def _cells(row: str) -> list[str]:
    s = row.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def section_rows(body: str, name: str) -> list[list[str]]:
    """Data rows of the first markdown table under `## name` (fences blanked)."""
    scan = blank_fences(body)
    rows, in_sec, header_seen = [], False, False
    for raw in scan.splitlines():
        if HEADING.match(raw):
            if in_sec and rows:
                break
            in_sec = re.match(rf"^##\s+{re.escape(name)}\b", raw) is not None
            header_seen = False
            continue
        if not in_sec or not raw.lstrip().startswith("|"):
            continue
        if set(raw.strip()) <= set("|-: "):
            continue
        c = _cells(raw)
        if not header_seen:
            header_seen = True
            continue
        rows.append(c)
    return rows


def fenced_blocks(body: str, lang: str) -> list[tuple[str, int]]:
    out = []
    for m in re.finditer(rf"```{lang}\s*(.*?)```", body, re.DOTALL):
        out.append((m.group(1), line_of(body, m.start())))
    return out


def find_placeholders(body: str, offset: int) -> list[dict]:
    findings = []
    scan = blank_fences(body)
    for rx, label, sev in ((PLACEHOLDER_WORD, "placeholder marker", "high"),
                           (TEMPLATE_TOKEN, "possible unfilled template token (verify)", "low")):
        for m in rx.finditer(scan):
            findings.append({"category": "placeholder", "severity": sev,
                             "detail": f"{label}: {m.group(0)!r}",
                             "location": f"{ROADMAP} (line {offset + line_of(scan, m.start())})"})
    return findings


def find_retire_without_criteria(body: str, offset: int) -> list[dict]:
    """Every component marked Retire needs a Decommission Criteria row.
    The skill's rule: 'a retirement with no criteria is not yet a decision.'"""
    findings = []
    decommissioned = {r[0].lower() for r in section_rows(body, "Decommission Criteria") if r and r[0]}
    for m in STRATEGY_HEADING.finditer(blank_fences(body)):
        comp, strat = m.group(1).strip(), m.group(2)
        if strat == "Retire" and comp.lower() not in decommissioned:
            findings.append({"category": "retire_no_criteria", "severity": "high",
                             "detail": f"{comp!r} is strategy Retire but has no Decommission Criteria row",
                             "location": f"{ROADMAP} (line {offset + line_of(blank_fences(body), m.start())})"})
    return findings


def find_ramp_without_criteria(body: str, offset: int) -> list[dict]:
    """Progressive-ramp components need advance criteria AND distinct rollback triggers."""
    findings = []
    scan = blank_fences(body)
    rows = section_rows(body, "Wave Advance & Rollback Criteria")
    have_criteria = bool(rows)
    identical = [r for r in rows if len(r) >= 3 and r[1] and r[1] == r[2]]
    for m in STRATEGY_HEADING.finditer(scan):
        comp = m.group(1).strip()
        nxt = HEADING.search(scan, m.end())
        block = scan[m.end():nxt.start()] if nxt else scan[m.end():]
        if "progressive ramp" in block.lower() and not have_criteria:
            findings.append({"category": "ramp_no_criteria", "severity": "high",
                             "detail": f"{comp!r} uses a progressive ramp but no Wave Advance & Rollback Criteria rows exist",
                             "location": f"{ROADMAP} (line {offset + line_of(scan, m.start())})"})
    for r in identical:
        findings.append({"category": "ramp_no_criteria", "severity": "medium",
                         "detail": f"step {r[0]!r} advance criteria and rollback trigger are identical; they fire at different times and must differ",
                         "location": f"{ROADMAP} Wave Advance & Rollback Criteria"})
    return findings


def find_graph_issues(body: str, offset: int) -> list[dict]:
    """Empty graphs, and a dependency cycle in the cutover graph."""
    findings = []
    for label, section in (("Build Graph", "Build Graph"), ("Cutover Graph", "Cutover Graph")):
        idx = body.find(f"## {section}")
        if idx < 0:
            continue
        nxt = body.find("\n## ", idx + 1)
        chunk = body[idx: nxt if nxt > 0 else len(body)]
        blocks = fenced_blocks(chunk, "mermaid")
        if not blocks:
            continue
        for content, rel in blocks:
            edges = MERMAID_EDGE.findall(content)
            line = offset + line_of(body, idx) + rel
            if not edges:
                findings.append({"category": "empty_graph", "severity": "high",
                                 "detail": f"{label} mermaid block declares no edges",
                                 "location": f"{ROADMAP} {label} (line ~{line})"})
                continue
            if section == "Cutover Graph":
                adj: dict[str, list[str]] = {}
                for a, b in edges:
                    adj.setdefault(a, []).append(b)
                cycle = _find_cycle(adj)
                if cycle:
                    findings.append({"category": "wave_cycle", "severity": "high",
                                     "detail": f"cutover graph has a dependency cycle: {' -> '.join(cycle)}",
                                     "location": f"{ROADMAP} {label} (line ~{line})"})
    return findings


def _find_cycle(adj: dict[str, list[str]]) -> list[str] | None:
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    stack: list[str] = []

    def dfs(n: str) -> list[str] | None:
        color[n] = GREY
        stack.append(n)
        for m in adj.get(n, []):
            c = color.get(m, WHITE)
            if c == GREY:
                return stack[stack.index(m):] + [m]
            if c == WHITE:
                r = dfs(m)
                if r:
                    return r
        stack.pop()
        color[n] = BLACK
        return None

    for node in list(adj):
        if color.get(node, WHITE) == WHITE:
            r = dfs(node)
            if r:
                return r
    return None


def find_orphan_components(body: str, offset: int) -> list[dict]:
    """Gap Analysis components must appear in Strategy; Strategy components must come from Inventory.

    One component yields at most one finding. A component missing from Inventory is reported
    once — not again for each later section it also falls out of — so a single defect never
    reads as several and trains reviewers to skim the category."""
    findings = []
    inventory = {r[0].lower() for r in section_rows(body, "Component Inventory") if r and r[0]}
    gaps = {r[0].lower() for r in section_rows(body, "Gap Analysis") if r and r[0]}
    strategies = {m.group(1).strip().lower() for m in STRATEGY_HEADING.finditer(blank_fences(body))}
    reported: set[str] = set()

    def report(name: str, severity: str, detail: str, section: str) -> None:
        if name in reported:
            return
        reported.add(name)
        findings.append({"category": "orphan_component", "severity": severity,
                         "detail": detail, "location": f"{ROADMAP} {section}"})

    # Not in Inventory is the root defect — report it before the downstream consequences.
    for c in sorted((gaps | strategies) - inventory):
        report(c, "high", f"{c!r} is referenced but is not in Component Inventory", "Gap Analysis")
    for g in sorted(gaps - strategies):
        report(g, "high", f"{g!r} has a gap but no strategy block", "Gap Analysis")
    # Deliberately not checked: a strategy with no Gap Analysis row. The skill requires
    # "for every unit with a gap, assign a strategy" — not the converse — so flagging it
    # would enforce a rule the roadmap never states.
    return findings


def lint(text: str) -> dict:
    frontmatter, body, offset = split_frontmatter(text)
    findings: list[dict] = []
    findings += find_placeholders(body, offset)
    findings += find_retire_without_criteria(body, offset)
    findings += find_ramp_without_criteria(body, offset)
    findings += find_graph_issues(body, offset)
    findings += find_orphan_components(body, offset)
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {"ok": len(findings) == 0, "roadmap": ROADMAP,
            "total_findings": len(findings), "by_severity": counts, "findings": findings}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lint a modernization roadmap for mechanical integrity.")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("-o", "--output")
    args = ap.parse_args(argv)
    p = Path(args.workspace) / ROADMAP
    if not p.exists():
        result = {"ok": False, "error": f"{p} not found", "findings": [], "total_findings": 0}
    else:
        result = lint(p.read_text(encoding="utf-8"))
    out = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(out + "\n", encoding="utf-8")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
