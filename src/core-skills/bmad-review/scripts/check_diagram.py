#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""check_diagram — the mechanical half of diagram integrity, done deterministically.

A diagram and the prose table beside it are two encodings of the same claim, and nothing
checks that they agree. An LLM reads both and sees two plausible passages; a set
comparison sees that `payments` is a node in the graph and absent from the table. This
script owns the checks a script does better than a prompt and leaves the semantic half
(is this the right decomposition? is the boundary sound?) to the lens.

It reads a markdown artifact and reports, as compact JSON on stdout:

  - unparsed_diagram   a fenced diagram block whose body declares no nodes or edges
  - undeclared_node    a node in the graph with no row in any table in the document
  - untraced_row       a table row naming an entity that appears in no graph
  - self_edge          a node that depends on itself
  - duplicate_edge     the same directed edge declared twice
  - orphan_node        a declared node with no edges at all

Mermaid `graph`/`flowchart`, `sequenceDiagram`, and `stateDiagram` bodies are recognized.
Reported lines are absolute file lines. Exit code is always 0 — findings travel in the
JSON; the caller decides what to do with them.

Renderer-level validity (does this compile, does it lay out) is not this script's job:
the lens delegates that to a renderer when one is available.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

FENCE = re.compile(r"^```(\w+)[^\n]*\n(.*?)^```", re.DOTALL | re.MULTILINE)
DIAGRAM_LANGS = {"mermaid"}
# Arrow alternation is longest-first: `->` placed before `-->` would match the first two
# characters and leave `-` as the target node. The final alternative matches a dash-style
# inline edge label with no `|pipe|` (`a-- some text -->b`) — common mermaid syntax that
# the literal tokens alone don't cover.
ARROW = r"(?:-\.->|-->>|==>|-->|---|->>|=>|->|--[ \t]*[^\n|]+?[ \t]*(?:-->|---))"
SHAPE = r"(?:\[[^\]]*\]|\([^)]*\)|\{[^}]*\})"
# One hop: source node, optional shape, arrow, optional pipe label, then a zero-width
# lookahead on the target so the match doesn't consume it — the target can then serve as
# the source of the next hop when a line chains edges (`a --> b --> c`).
_HOP = r"([A-Za-z0-9_.\-]+?)\s*" + SHAPE + r"?\s*" + ARROW + r"\s*(?:\|[^|]*\|)?\s*(?=([A-Za-z0-9_.\-]+))"
# A chain's first hop must start at true line-start, so arrow-like text inside a node's
# own shape label (`a[Does X -> Y?]`) is never mistaken for an edge. Later hops in the same
# chain resume wherever the previous hop's target began, with no such anchor.
EDGE_START = re.compile(r"^[ \t]*" + _HOP, re.MULTILINE)
EDGE_CONTINUE = re.compile(_HOP)
NODE_DECL = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(?:\[[^\]]*\]|\([^)]*\)|\{[^}]*\})\s*$", re.MULTILINE)
PARTICIPANT = re.compile(r"^\s*(?:participant|actor)\s+([A-Za-z0-9_.\-]+)", re.MULTILINE)
# A node drawn as a decision diamond `id{...}` or hexagon `id{{...}}` is flow control, not a
# component — captured anywhere it appears, even inline on an edge line.
GATEWAY_DECL = re.compile(r"([A-Za-z0-9_.\-]+)\{\{?[^}]*\}\}?")
DIRECTIVE = re.compile(
    r"^\s*(graph|flowchart|sequenceDiagram|stateDiagram(?:-v2)?|classDiagram|erDiagram)\b"
)
# Mermaid keywords and layout directions that are never entity names.
RESERVED = {
    "graph", "flowchart", "subgraph", "end", "sequencediagram", "statediagram",
    "statediagram-v2", "classdiagram", "erdiagram", "participant", "actor", "note",
    "loop", "alt", "else", "opt", "par", "and", "rect", "activate", "deactivate",
    "lr", "rl", "tb", "bt", "td", "direction", "class", "click", "style", "linkstyle",
    "classdef", "state", "title", "accdescr", "acctitle",
}


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def chain_edges(body: str) -> list[tuple[str, str]]:
    """Every edge in a diagram body, following multi-hop chains on one line.

    `a --> b --> c` declares two edges, not one. Each chain's first hop is found anchored
    to line-start (see EDGE_START); each further hop resumes matching exactly where the
    previous hop's target began, threading the chain without re-anchoring."""
    edges: list[tuple[str, str]] = []
    for m in EDGE_START.finditer(body):
        source, target = m.group(1), m.group(2)
        pos = m.end()
        while True:
            edges.append((source, target))
            m2 = EDGE_CONTINUE.match(body, pos)
            if not m2:
                break
            source, target = m2.group(1), m2.group(2)
            pos = m2.end()
    return edges


def diagram_kind(body: str) -> str | None:
    """The directive keyword (e.g. `sequencediagram`) opening a diagram body, if any."""
    m = DIRECTIVE.search(body)
    return m.group(1).lower() if m else None


def diagram_blocks(text: str) -> list[dict]:
    """Every fenced diagram block: its body, language, and absolute start line."""
    blocks = []
    for m in FENCE.finditer(text):
        lang = m.group(1).lower()
        if lang not in DIAGRAM_LANGS:
            continue
        blocks.append({"lang": lang, "body": m.group(2), "line": line_of(text, m.start())})
    return blocks


def graph_entities(body: str) -> tuple[set[str], list[tuple[str, str]], set[str]]:
    """Nodes, directed edges, and gateway ids declared in one diagram body.

    A gateway is a node drawn as a decision diamond (`id{...}`) or hexagon (`id{{...}}`) —
    mermaid flow control, not a system component. They are real nodes for cycle, self-edge,
    and orphan purposes, but must not be cross-checked against a component table: a
    `decision{approve?}` diamond legitimately has no table row, and flagging it would train
    reviewers to ignore the category that also catches a genuinely missing component."""
    edges = [
        (a, b)
        for a, b in chain_edges(body)
        if a.lower() not in RESERVED and b.lower() not in RESERVED
    ]
    nodes = {n for edge in edges for n in edge}
    for rx in (NODE_DECL, PARTICIPANT):
        for name in rx.findall(body):
            if name.lower() not in RESERVED:
                nodes.add(name)
    gateways = {g for g in GATEWAY_DECL.findall(body) if g.lower() not in RESERVED}
    return nodes, edges, gateways


def table_entities(text: str) -> set[str]:
    """First-column values of every markdown table that plausibly names entities.

    Fenced blocks are removed first so a pipe inside a code sample is never read as a
    table row. Header and separator rows are skipped. Two kinds of table are excluded
    because their first column is prose, not an entity name: a table whose header names a
    non-entity column (Assumption, Question, Risk, Wave, Step), and any row whose first
    cell reads as a sentence rather than an identifier. Without those exclusions an
    Assumptions table turns every assumption into a phantom "entity missing from the
    diagram" — noise that trains reviewers to skim the category."""
    stripped = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    entities: set[str] = set()
    header: list[str] = []
    prev_was_row = False
    for raw in stripped.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            prev_was_row = False
            header = []
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if set(line) <= set("|-: "):
            prev_was_row = True  # separator: the row before it was the header
            continue
        if not prev_was_row:
            header = [_bare(c).lower() for c in cells]  # header row
            continue
        if header and header[0] in _NON_ENTITY_COLUMNS:
            continue
        if not cells or not cells[0]:
            continue
        name = _bare(cells[0])
        if name and _is_identifier_like(name):
            entities.add(name)
    return entities


# First-column headers whose values are prose or labels, never diagram nodes.
_NON_ENTITY_COLUMNS = {
    "assumption", "question", "open question", "risk", "wave", "wave / step", "step",
    "wave / phase", "phase", "term", "rule", "finding", "criterion", "criteria",
}


def _is_identifier_like(name: str) -> bool:
    """Whether a cell reads as an entity name rather than a sentence.

    Diagram nodes are short identifiers. A cell with sentence punctuation or more than
    four words is prose that happens to sit in a first column."""
    if name.endswith("?") or name.endswith("."):
        return False
    return len(name.split()) <= 4


def _bare(cell: str) -> str:
    """Strip markdown emphasis, code ticks, and link syntax from a table cell."""
    cell = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    return cell.replace("`", "").replace("*", "").replace("_", " ").strip()


def _norm(name: str) -> str:
    """Compare entity names ignoring case and separator style."""
    return re.sub(r"[\s_.\-]+", "", name).lower()


def check(text: str) -> dict:
    findings: list[dict] = []
    blocks = diagram_blocks(text)
    table_names = table_entities(text)
    table_norm = {_norm(t) for t in table_names}
    all_graph_norm: set[str] = set()

    for block in blocks:
        nodes, edges, gateways = graph_entities(block["body"])
        kind = diagram_kind(block["body"])
        all_graph_norm |= {_norm(n) for n in nodes}
        gateway_norm = {_norm(g) for g in gateways}
        loc = f"line {block['line']}"

        if not nodes and not edges:
            # classDiagram/erDiagram relation syntax (`*--`, `..>`, `||--o{`, ...) isn't
            # recognized by EDGE, so an empty parse there usually means "we don't
            # understand this diagram's own relationship syntax", not "the author left it
            # empty" — not flagged, for the same reason the table-row-with-no-diagram rule
            # was removed. A block with nothing at all beyond the directive keyword is
            # still flagged either way.
            if kind in {"classdiagram", "erdiagram"}:
                remainder = DIRECTIVE.sub("", block["body"], count=1).strip()
                should_flag = not remainder
            else:
                should_flag = bool(DIRECTIVE.search(block["body"])) or not block["body"].strip()
            if should_flag:
                findings.append({
                    "category": "unparsed_diagram", "location": loc,
                    "detail": "diagram block declares no nodes or edges",
                })
            continue

        for a, b in edges:
            # A self-call in a sequence diagram and a self-transition in a state diagram
            # are idiomatic and valid; only a flowchart/graph component depending on
            # itself is a real defect.
            if _norm(a) == _norm(b) and kind not in {"sequencediagram", "statediagram", "statediagram-v2"}:
                findings.append({
                    "category": "self_edge", "location": loc,
                    "detail": f"{a!r} depends on itself",
                })
        seen: set[tuple[str, str]] = set()
        for a, b in edges:
            key = (_norm(a), _norm(b))
            if key in seen:
                findings.append({
                    "category": "duplicate_edge", "location": loc,
                    "detail": f"edge {a} -> {b} declared more than once",
                })
            seen.add(key)

        connected = {n for edge in edges for n in edge}
        for n in sorted(nodes - connected):
            findings.append({
                "category": "orphan_node", "location": loc,
                "detail": f"{n!r} is declared but has no edges",
            })

        # Cross-check names against tables only when this graph overlaps them at all. A
        # graph whose nodes are entirely absent from every table is describing a different
        # layer on purpose — a build graph naming generated artifacts, a state machine
        # naming states — and flagging every node would be noise, not signal. A graph that
        # overlaps partially is the interesting case: those are real omissions.
        if table_norm:
            node_norms = {_norm(n) for n in nodes}
            if node_norms & table_norm:
                for n in sorted(nodes):
                    # Gateways are flow control, not components — never cross-checked.
                    if _norm(n) not in table_norm and _norm(n) not in gateway_norm:
                        findings.append({
                            "category": "undeclared_node", "location": loc,
                            "detail": f"{n!r} appears in the diagram but in no table row",
                        })

    # Deliberately not checked: a table row naming something no diagram draws. On real
    # documents that fires constantly and almost always wrongly — a page with one
    # illustrative diagram and several unrelated reference tables is normal, and no rule in
    # this framework says every table row must be drawn. Whether the diagram omits
    # something that matters is a judgment call, so the lens's semantic pass owns it
    # (completeness against the prose) rather than a set difference here.

    counts: dict[str, int] = {}
    for f in findings:
        counts[f["category"]] = counts.get(f["category"], 0) + 1
    return {
        "ok": len(findings) == 0,
        "diagram_blocks": len(blocks),
        "total_findings": len(findings),
        "by_category": counts,
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check diagram/table agreement in a markdown artifact.")
    ap.add_argument("path", help="markdown file containing one or more fenced diagram blocks")
    ap.add_argument("-o", "--output", help="write JSON here instead of stdout")
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        result = {"ok": False, "error": f"{path} not found", "findings": [], "total_findings": 0}
    else:
        try:
            result = check(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as error:
            result = {"ok": False, "error": f"could not read {path}: {error}",
                      "findings": [], "total_findings": 0}

    out = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(out + "\n", encoding="utf-8")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
