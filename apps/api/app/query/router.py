"""Deterministic route -> optional module selection (no agent loop)."""

from __future__ import annotations

from app.query.ir import QueryIR


def select_modules(
    query_ir: QueryIR | None,
    *,
    graph: bool,
    decomposition: bool,
    requirements: bool,
    targeted: bool,
) -> dict[str, bool]:
    modules = {
        "graph": graph,
        "decomposition": decomposition,
        "requirements": requirements,
        "targeted": targeted,
    }
    if query_ir is None:
        return modules
    if query_ir.strategy == "semantic_expansion":
        modules["graph"] = True
    elif query_ir.strategy == "multi_hop":
        modules["graph"] = True
        modules["decomposition"] = True
    elif query_ir.strategy == "regulation":
        modules["requirements"] = True
        modules["targeted"] = True
    return modules
