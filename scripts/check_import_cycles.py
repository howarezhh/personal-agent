"""Detect Python import cycles in the backend package."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path("backend")


def module_name(file_path: Path) -> str:
    rel = file_path.relative_to(Path("."))
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def discover_modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for file_path in ROOT.rglob("*.py"):
        if "__pycache__" in file_path.parts or "tests" in file_path.parts:
            continue
        modules[module_name(file_path)] = file_path
    return modules


def resolve_relative(module: str, imported: str | None, level: int) -> str:
    parts = module.split(".")
    base = parts[:-1]
    if level > 0:
        base = base[: len(base) - level + 1]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def build_graph(modules: dict[str, Path]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {name: set() for name in modules}
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = alias.name
                    if target.startswith("backend") and target in modules:
                        graph[name].add(target)
            elif isinstance(node, ast.ImportFrom):
                target = resolve_relative(name, node.module, node.level) if node.level else node.module
                if target and target.startswith("backend") and target in modules:
                    graph[name].add(target)
    return graph


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    visited: set[str] = set()
    stack: list[str] = []
    in_stack: set[str] = set()
    cycles: list[list[str]] = []

    def dfs(node: str):
        visited.add(node)
        stack.append(node)
        in_stack.add(node)

        for neighbor in graph[node]:
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in in_stack:
                start = stack.index(neighbor)
                cycle = stack[start:] + [neighbor]
                if cycle not in cycles:
                    cycles.append(cycle)

        stack.pop()
        in_stack.remove(node)

    for node in graph:
        if node not in visited:
            dfs(node)
    return cycles


def main() -> int:
    modules = discover_modules()
    graph = build_graph(modules)
    cycles = find_cycles(graph)
    if cycles:
        print("Import cycles detected:")
        for cycle in cycles:
            print(" -> ".join(cycle))
        return 1
    print("No backend import cycles detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

