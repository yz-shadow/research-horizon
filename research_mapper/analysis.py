from __future__ import annotations

from collections import defaultdict
import json


def canonical(label: str, mappings: dict[str, str]) -> str:
    return mappings.get(label, label).strip() or label


def grouped_claims(claims: list[dict], mappings: dict[str, str]) -> dict[tuple[str, str], list[dict]]:
    groups = defaultdict(list)
    for claim in claims:
        key = (canonical(claim["problem"], mappings), canonical(claim["method"], mappings))
        groups[key].append(claim)
    return dict(groups)


def concepts(claims: list[dict]) -> list[str]:
    return sorted({c[field] for c in claims for field in ("problem", "method", "dataset") if c.get(field)}, key=str.casefold)


def candidates(groups: dict[tuple[str, str], list[dict]]) -> list[dict]:
    problems = sorted({key[0] for key in groups}, key=str.casefold)
    methods = sorted({key[1] for key in groups}, key=str.casefold)
    found = []
    for problem in problems:
        for method in methods:
            if (problem, method) in groups:
                continue
            same_problem = [claim for (p, m), items in groups.items() if p == problem and m != method for claim in items]
            same_method = [claim for (p, m), items in groups.items() if m == method and p != problem for claim in items]
            if not same_problem or not same_method:
                continue
            found.append({
                "problem": problem,
                "method": method,
                "score": min(len({x["paper_id"] for x in same_problem}), len({x["paper_id"] for x in same_method})),
                "problem_neighbors": same_problem,
                "method_neighbors": same_method,
            })
    return sorted(found, key=lambda x: (-x["score"], x["problem"], x["method"]))


def graph_dot(claims: list[dict], mappings: dict[str, str]) -> str:
    def q(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    nodes = set()
    edges = set()
    for claim in claims:
        p = canonical(claim["problem"], mappings)
        m = canonical(claim["method"], mappings)
        nodes.add(("p:" + p, p, "#FEE2E2"))
        nodes.add(("m:" + m, m, "#DBEAFE"))
        edges.add(("p:" + p, "m:" + m))
        if claim.get("dataset"):
            d = canonical(claim["dataset"], mappings)
            nodes.add(("d:" + d, d, "#DCFCE7"))
            edges.add(("m:" + m, "d:" + d))
    lines = ["digraph G {", "rankdir=LR;", "graph [bgcolor=transparent];", "node [shape=box style=filled fontname=Arial];"]
    lines += [f"{q(node_id)} [label={q(label)} fillcolor={q(color)}];" for node_id, label, color in sorted(nodes)]
    lines += [f"{q(a)} -> {q(b)};" for a, b in sorted(edges)]
    return "\n".join(lines + ["}"])


def export_json(papers: list[dict], claims: list[dict], mappings: dict[str, str]) -> str:
    return json.dumps({"papers": papers, "claims": claims, "mappings": mappings}, ensure_ascii=False, indent=2)
