#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TARGET_DIR="${1:-cosmicsnip}"

if [ ! -d "$TARGET_DIR" ]; then
    echo "ERROR: Target directory '$TARGET_DIR' does not exist."
    exit 1
fi

have() {
    command -v "$1" >/dev/null 2>&1
}

print_section() {
    echo
    echo "== $1 =="
}

print_section "Maintainability Audit"
echo "Repo: $ROOT_DIR"
echo "Target: $TARGET_DIR"
echo "Timestamp (UTC): $(date -u +"%Y-%m-%dT%H:%M:%SZ")"

print_section "Policy Drift Checks"
echo "[1/7] Risky API patterns"
if rg -n "\\beval\\(|\\bexec\\(|os\\.system\\(|shell\\s*=\\s*True|shell=True" "$TARGET_DIR"; then
    echo "Result: MATCHES FOUND (review required)"
else
    echo "Result: no risky API matches found"
fi

echo
echo "[2/7] DBusActivatable usage"
if rg -n "DBusActivatable" data install.sh build-deb.sh; then
    echo "Result: MATCHES FOUND (verify against COSMIC safety constraints)"
else
    echo "Result: no DBusActivatable usage found in packaging/install surface"
fi

echo
echo "[3/7] Broad exception handlers"
if rg -n "^\\s*except\\s+Exception" "$TARGET_DIR"; then
    echo "Result: broad exception handlers present (review granularity)"
else
    echo "Result: no broad exception handlers found"
fi

echo
echo "[4/7] Informal markers (TODO/FIXME/HACK/XXX)"
if rg -n "TODO|FIXME|HACK|XXX" "$TARGET_DIR"; then
    echo "Result: markers found"
else
    echo "Result: no informal markers found"
fi

print_section "Complexity Scan"
echo "[5/7] Function complexity hotspots"
if have radon; then
    echo "Using radon."
    RADON_OUT="/tmp/cosmicsnip-radon-cc.txt"
    if ! radon cc -s "$TARGET_DIR" >"$RADON_OUT" 2>&1; then
        echo "radon returned non-zero status (continuing with captured output)."
    fi
    sed -n '1,60p' "$RADON_OUT"
else
    echo "radon not found; running heuristic complexity fallback."
    TARGET_DIR="$TARGET_DIR" python3 - <<'PY'
import ast
import os
from pathlib import Path

ROOT = Path(os.environ["TARGET_DIR"])

def complexity(node):
    score = 1
    for n in ast.walk(node):
        if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Assert, ast.Match)):
            score += 1
        elif isinstance(n, ast.BoolOp):
            score += max(0, len(n.values) - 1)
        elif isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            score += 1
    return score

rows = []
for p in ROOT.rglob("*.py"):
    src = p.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rows.append((complexity(node), str(p), node.lineno, node.name))

rows.sort(reverse=True)
print("Top complexity hotspots (heuristic):")
for c, f, l, n in rows[:20]:
    print(f"{c:>3}  {f}:{l}  {n}")
PY
fi

print_section "Duplication Scan"
echo "[6/7] Potential duplicate blocks"
if have jscpd; then
    echo "Using jscpd."
    if ! jscpd --min-lines 8 --min-tokens 50 "$TARGET_DIR"; then
        echo "jscpd returned non-zero status (typically indicates duplicates found)."
    fi
else
    echo "jscpd not found; running normalized-window fallback."
    TARGET_DIR="$TARGET_DIR" python3 - <<'PY'
import os
from pathlib import Path
from collections import defaultdict

ROOT = Path(os.environ["TARGET_DIR"])
WINDOW = 8

buckets = defaultdict(list)
for p in ROOT.rglob("*.py"):
    lines = p.read_text(encoding="utf-8").splitlines()
    for i in range(len(lines) - WINDOW + 1):
        chunk = lines[i:i + WINDOW]
        norm = []
        for ln in chunk:
            s = ln.strip()
            if not s or s.startswith("#"):
                s = ""
            norm.append(" ".join(s.split()))
        key = "\n".join(norm)
        if key.strip():
            buckets[key].append((str(p), i + 1))

hits = [(k, v) for k, v in buckets.items() if len(v) > 1]
hits.sort(key=lambda kv: len(kv[1]), reverse=True)
print("Potential duplicated blocks (8-line windows, normalized):")
shown = 0
for _, occ in hits[:30]:
    dedup = []
    for file_path, line_no in occ:
        if not dedup or dedup[-1][0] != file_path or abs(dedup[-1][1] - line_no) > 2:
            dedup.append((file_path, line_no))
    if len(dedup) < 2:
        continue
    shown += 1
    locs = ", ".join(f"{f}:{l}" for f, l in dedup[:6])
    print(f"- {len(dedup)}x -> {locs}")
    if shown >= 12:
        break
if shown == 0:
    print("- none")
PY
fi

print_section "Dead Code and Syntax"
echo "[7/7] Dead code + compile sanity"
if have vulture; then
    echo "Using vulture (confidence >= 80)."
    if ! vulture "$TARGET_DIR" --min-confidence 80; then
        echo "vulture returned non-zero status (typically indicates unused-code candidates)."
    fi
else
    echo "vulture not found; skipping dead-code scan."
fi

python3 -m py_compile "$TARGET_DIR"/*.py
python3 -m compileall -q "$TARGET_DIR"
echo "Compile checks: PASS"

print_section "Completed"
echo "Maintainability audit finished."
