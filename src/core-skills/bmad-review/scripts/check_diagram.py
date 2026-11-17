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

It reads a markdown artifact and reports, as JSON on stdout:

  - empty_diagram      a mermaid block with nothing in it beyond its directive line
  - undeclared_node    a flowchart node (by id or label) with no row in any table
  - self_edge          a flowchart node that depends on itself
  - duplicate_edge     the same directed flowchart edge declared twice
  - orphan_node        a flowchart node declared with no edges at all

Only mermaid `graph`/`flowchart` blocks get the structural checks; every other mermaid
type (sequence, state, ER, class, C4, mindmap, ...) is only checked for being empty.
Reported lines are absolute file lines. Exit code is always 0 — findings travel in the
JSON; the caller decides what to do with them.

lint_roadmap.py (bmad-modernization-roadmap) has its own mermaid edge regex, the ancestor
of this parser. Skill scripts ship standalone, so they can't share an import; a parity test
in tests/ catches drift instead.

Renderer-level validity (does this compile, does it lay out) is not this script's job:
the lens delegates that to a renderer when one is available.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True

FENCE = re.compile(r"^```(\w+)[^\n]*\n(.*?)^```", re.DOTALL | re.MULTILINE)
# Flowchart lines that never declare nodes or edges.
LAYOUT = re.compile(r"(?:subgraph|end|direction|style|classDef|class|click|linkStyle)(?!\S)")
# Ids never end with `-`, so `a-->b` can't yield a node `a--`.
ID = r"\w+(?:[-.]\w+)*"
# One node: id, optional shape (`[..]`, `((..))`, `[(..)]`, `>..]`, `{{..}}`, `["a [x]"]`, ...),
# optional `@{ .. }`, optional `:::class`, optional `&` + next. A shape closes only on its own
# bracket kind, so `svc[Order (legacy) Service]` and `a{Is it [ok]?}` keep their labels.
SHAPE = r'\[(?:"[^"]*"|[^\]"])*\]+|\((?:"[^"]*"|[^)"])*\)+|\{(?:"[^"]*"|[^}"])*\}+|>(?:"[^"]*"|[^\]"])*\]'
NODE = re.compile(
    r"\s*(?P<id>" + ID + r")(?P<shape>" + SHAPE + r")?(?:@\{[^}]*\})?(?::::\w+(?:-\w+)*)?\s*(?P<amp>&)?"
)
# One link: optional edge id `e1@`, optional start head (`<-->`, `o--o`), optional text
# opener (`-- text -->`, `A--Yes-->B`, `-. text .->`), the line itself, optional `|label|`
# (a quoted part of it may hold `|`, so `-->|"a | b"| c` still ends at `c`).
# Text never starts with an arrow character or an `o`/`x` head, which would let
# `A --o B --> C` swallow B; a closing `--`/`==` needs its head, so `-- a == b -->` is one link.
LINK = re.compile(
    r"\s*(?:\w+@)?[<ox]?(?:(?:--|==|-\.)(?P<dashlabel>(?:\s|(?![ox]\b)[^\s|>.=-])[^|]*?))?"
    r"(?:-{2,}(?:>|[ox]\b)|-{3,}|={2,}(?:>|[ox]\b)|={3,}|-?\.+-(?:>|[ox]\b)?|~{3,})"
    r"(?:\s*\|(?P<pipelabel>(?:\"[^\"]*\"|[^|\"])*)\|)?"
)


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def parse_line(line: str) -> tuple[list[re.Match], list[tuple[str, str]], list[str]]:
    """Node matches, (source, target) edges, and each edge's label, on one flowchart line.

    Scans left to right — node group, link, node group, ... — and stops at the first thing
    that doesn't fit. `a & b --> c` is two edges; `a --> b --> c` is a chain of two. A line
    that is neither a lone node group nor an edge yields nothing. A link's label (`|label|`,
    or the dash-style text before its closing arrow) belongs to the edge(s) it closes, so
    it's carried from the link matched in the previous step into the edges built here —
    `edges` stays plain `(a, b)` pairs so existing callers (and the `lint_roadmap.py` parity
    check) are untouched; `labels` is a same-length, same-order parallel list."""
    nodes, edges, labels, group, pos, label = [], [], [], [], 0, ""
    while True:
        nxt = []
        while m := NODE.match(line, pos):
            nxt.append(m)
            pos = m.end()
            if not m["amp"]:
                break
        for a in group:
            for b in nxt:
                edges.append((a["id"], b["id"]))
                labels.append(label)
        nodes += nxt
        link = nxt and LINK.match(line, pos)
        if not link:
            break
        label = (link["pipelabel"] or link["dashlabel"] or "").strip()
        group, pos = nxt, link.end()
    return (nodes, edges, labels) if edges or pos == len(line) else ([], [], [])


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
    """Compare entity names ignoring case, separators, and punctuation other than `#`/`+`."""
    return re.sub(r"[^\w#+]+|_", "", name).lower()


def check(text: str) -> dict:
    findings: list[dict] = []
    table_norm = {_norm(t) for t in table_entities(text)}
    blocks = [m for m in FENCE.finditer(text) if m[1].lower() == "mermaid"]

    for block in blocks:
        loc = f"line {line_of(text, block.start())}"

        def add(category: str, detail: str) -> None:
            findings.append({"category": category, "location": loc, "detail": detail})

        body = re.sub(r"%%\{.*?\}%%", "", block[2], flags=re.DOTALL)  # init, even multi-line
        body = re.sub(r'"`.*?`"', lambda m: m[0].replace("\n", " "), body, flags=re.DOTALL)
        lines = [raw.strip().rstrip(";").rstrip() for raw in body.splitlines()]
        lines = [line for line in lines if line and not line.startswith("%%")]
        if lines[:1] == ["---"] and "---" in lines[1:]:
            lines = lines[lines.index("---", 1) + 1:]  # YAML frontmatter
        if len(lines) < 2:
            add("empty_diagram", "diagram block declares nothing beyond its directive")
            continue
        if not re.match(r"(?:graph|flowchart)\b", lines[0]):
            continue

        # names: every id with its labels. A gateway is a node drawn as a decision diamond
        # `id{..}` or hexagon `id{{..}}` — flow control, not a component — so it is never
        # cross-checked: a `decision{approve?}` legitimately has no table row, and flagging
        # it would train reviewers to ignore the category.
        names: dict[str, set[str]] = {}
        gateways: set[str] = set()
        edges: list[tuple[str, str]] = []
        labels: list[str] = []
        mentions: Counter[str] = Counter()
        for line in lines[1:]:
            if LAYOUT.match(line):
                continue
            nodes, line_edges, line_labels = parse_line(line)
            edges += line_edges
            labels += line_labels
            for n in nodes:
                label = re.split(r"<br\s*/?>", n["shape"] or "", flags=re.I)[0]
                names.setdefault(n["id"], {n["id"]}).add(label or n["id"])
                if (n["shape"] or "").startswith("{"):
                    gateways.add(n["id"])
            mentions.update(set(re.findall(ID, line)))
        # `e1@{ animate: true }` styles the edge declared as `a e1@--> b`; it isn't a node.
        for edge_id in re.findall(r"\b(\w+)@(?=[<ox]?[-=.~])", body):
            names.pop(edge_id, None)

        seen: set[tuple[str, str, str]] = set()
        for (a, b), edge_label in zip(edges, labels):
            # Self-edge identity is case-insensitive only: unlike the table cross-check
            # below, it must not also strip separators, or two distinct mermaid ids that
            # differ only by `_` vs `-` (`api_gw`, `api-gw`) collide into a false positive.
            if a.lower() == b.lower():
                add("self_edge", f"{a!r} depends on itself")
            # The label is part of the duplicate key: `a -->|yes| b` and `a -->|retry| b`
            # are two genuinely different edges, not a duplicate.
            key = (_norm(a), _norm(b), edge_label.lower())
            if key in seen:
                add("duplicate_edge", f"edge {a} -> {b} declared more than once")
            seen.add(key)

        connected = {n for edge in edges for n in edge}
        for n in sorted(names.keys() - connected):
            # An id that also appears on another line sits on an edge this parser didn't
            # understand — skip it rather than report a false orphan.
            if mentions[n] < 2:
                add("orphan_node", f"{n!r} is declared but has no edges")

        # Cross-check names against tables only when one of this graph's ids is in a table.
        # A graph with none is describing a different layer on purpose — a build graph
        # naming generated artifacts — and flagging every node would be noise. A label match
        # alone (`pg[(PostgreSQL)]` beside a stack table) is too incidental to open the gate,
        # but once it is open a node passes on its id or its label.
        def listed(n: str) -> bool:
            return any(_norm(x) in table_norm for x in names[n])

        if any(_norm(n) in table_norm for n in names):
            for n in sorted(names.keys() - gateways):
                if not listed(n):
                    add("undeclared_node", f"{n!r} appears in the diagram but in no table row")

    # Deliberately not checked: a table row naming something no diagram draws. On real
    # documents that fires constantly and almost always wrongly — a page with one
    # illustrative diagram and several unrelated reference tables is normal. Whether the
    # diagram omits something that matters is a judgment call the lens's semantic pass owns.

    return {
        "ok": not findings,
        "diagram_blocks": len(blocks),
        "total_findings": len(findings),
        "by_category": dict(Counter(f["category"] for f in findings)),
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
