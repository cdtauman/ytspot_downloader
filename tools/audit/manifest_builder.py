"""Build AUDIT_COVERAGE_MANIFEST skeleton from git ls-files output.

Usage:
    python tools/audit/manifest_builder.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def classify(path: str) -> tuple[str, bool, str]:
    """Return (file_type, should_audit, area_hint)."""
    p = path.replace("\\", "/")
    parts = p.split("/")
    head = parts[0]
    ext = Path(p).suffix.lower()

    if ext == ".py":
        if head == "tests":
            return ("python-test", True, "tests")
        if head == "ui":
            sub = parts[1] if len(parts) > 1 else ""
            return ("python-ui", True, f"ui/{sub}" if sub else "ui")
        if head == "core":
            return ("python-core", True, "core")
        if head == "utils":
            return ("python-utils", True, "utils")
        if head == "tools":
            return ("python-tool", True, "tools")
        return ("python-app", True, head or "root")

    if ext in {".md"}:
        return ("docs", True, "docs")
    if ext in {".toml"}:
        return ("packaging", True, "packaging")
    if ext in {".ini", ".cfg"}:
        return ("config", True, "config")
    if ext in {".txt"}:
        if "requirements" in p.lower():
            return ("packaging", True, "packaging")
        if head == ".github":
            return ("workflow", True, "ci")
        return ("text", True, "other")
    if ext in {".yml", ".yaml"}:
        if head == ".github":
            return ("workflow", True, "ci")
        return ("config", True, "config")
    if ext in {".bat", ".sh", ".ps1"}:
        return ("script", True, "scripts")
    if path == ".gitignore":
        return ("config", True, "config")
    if "egg-info" in p.lower():
        return ("packaging-meta", False, "generated")
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bin", ".so", ".dll", ".pyd"}:
        return ("binary", False, "media")

    return ("other", True, head or "root")


def line_count(path: Path) -> int:
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return -1


def main() -> int:
    files = subprocess.check_output(
        ["git", "ls-files"], cwd=REPO_ROOT, text=True
    ).splitlines()
    files = [f for f in files if f.strip()]

    rows = []
    for rel in sorted(files):
        full = REPO_ROOT / rel
        ftype, audit, area = classify(rel)
        lines = line_count(full) if full.exists() else -1
        rows.append((rel, ftype, lines, audit, area))

    out = REPO_ROOT / "tools" / "audit" / "_manifest_seed.tsv"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        f.write("path\ttype\tlines\taudit\tarea\n")
        for r in rows:
            f.write(
                f"{r[0]}\t{r[1]}\t{r[2]}\t{'yes' if r[3] else 'skip'}\t{r[4]}\n"
            )

    totals: dict[str, tuple[int, int]] = {}
    for path, ftype, lines, audit, area in rows:
        cnt, ln = totals.get(ftype, (0, 0))
        totals[ftype] = (cnt + 1, ln + max(0, lines))
    print(f"Total tracked files: {len(rows)}")
    for k in sorted(totals):
        c, ln = totals[k]
        print(f"  {k:18s}  files={c:4d}  lines={ln:7d}")
    print(f"Seed written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
