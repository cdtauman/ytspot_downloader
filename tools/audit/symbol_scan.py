"""Extract top-level symbols (classes, functions, constants) from every .py file.

Outputs tools/audit/_symbols.tsv with columns:
    path  kind  name  lineno
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def scan(path: Path) -> list[tuple[str, str, str, int]]:
    """Return list of (kind, name, lineno, parent) for top-level + class members."""
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []

    rows: list[tuple[str, str, str, int]] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            rows.append(("class", node.name, "", node.lineno))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    rows.append(("method", item.name, node.name, item.lineno))
                elif isinstance(item, ast.Assign):
                    for tgt in item.targets:
                        if isinstance(tgt, ast.Name):
                            rows.append(("classvar", tgt.id, node.name, item.lineno))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rows.append(("func", node.name, "", node.lineno))
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    rows.append(("const", tgt.id, "", node.lineno))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            rows.append(("const", node.target.id, "", node.lineno))
        elif isinstance(node, ast.Import):
            for n in node.names:
                rows.append(("import", n.name, "", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for n in node.names:
                rows.append(("from", f"{mod}.{n.name}", "", node.lineno))

    return rows


def main() -> int:
    files = subprocess.check_output(
        ["git", "ls-files", "*.py"], cwd=REPO_ROOT, text=True
    ).splitlines()
    files = [f for f in files if f.strip()]

    out = REPO_ROOT / "tools" / "audit" / "_symbols.tsv"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        f.write("path\tkind\tname\tparent\tlineno\n")
        for rel in sorted(files):
            full = REPO_ROOT / rel
            if not full.exists():
                continue
            for kind, name, parent, lineno in scan(full):
                f.write(f"{rel}\t{kind}\t{name}\t{parent}\t{lineno}\n")

    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
