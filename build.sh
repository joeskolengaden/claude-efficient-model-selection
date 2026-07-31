#!/usr/bin/env bash
# Rebuilds efficient-model-selection.skill from the source SKILL.md.
# Run this after any edit to plugins/efficient-model-selection/skills/efficient-model-selection/SKILL.md,
# before committing — nothing auto-runs this (see .github/workflows/verify-skill-package.yml,
# which checks the result instead of regenerating it: see README for why this is deliberate).
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'EOF'
import zipfile, os
from pathlib import Path

src = Path("plugins/efficient-model-selection/skills/efficient-model-selection")
out = Path("efficient-model-selection.skill")

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules")]
        for f in files:
            if f == ".DS_Store" or f.endswith(".pyc"):
                continue
            full = Path(root) / f
            zf.write(full, Path(src.name) / full.relative_to(src))

print(f"wrote {out} ({out.stat().st_size} bytes)")
EOF
