#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "== Smart Shadow lightweight verification =="
echo "repo: $repo_root"
echo "commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [[ -n "$(git status --short)" ]]; then
  echo "worktree: dirty"
  git status --short
else
  echo "worktree: clean"
fi
if [[ -x "$repo_root/.venv/bin/python" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-$repo_root/.venv/bin/python}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi
echo "python_bin: $PYTHON_BIN"
"$PYTHON_BIN" --version

"$PYTHON_BIN" -m unittest discover -s tests -v
"$PYTHON_BIN" -m py_compile ai_server.py super_algo.py aigc/*.py eval/*.py tests/*.py
"$PYTHON_BIN" -m aigc.manifest eval/manifest.example.jsonl
"$PYTHON_BIN" -m eval.source_residual_eval
"$PYTHON_BIN" -m eval.near_duplicate_eval
"$PYTHON_BIN" -m eval.propagation_stability_eval
"$PYTHON_BIN" -m eval.propagation_envelope_eval
"$PYTHON_BIN" -m eval.image_adapter_matrix
"$PYTHON_BIN" -m eval.regional_counterfactual_eval
"$PYTHON_BIN" -m eval.regional_alignment_eval
"$PYTHON_BIN" -m eval.paired_delta_calibration_eval
"$PYTHON_BIN" -m eval.regional_fdr_eval
"$PYTHON_BIN" -m eval.scte_eval
"$PYTHON_BIN" -m eval.patch_coverage_eval
"$PYTHON_BIN" -m eval.pc_scft_eval
"$PYTHON_BIN" -m eval.evidence_budget_eval
"$PYTHON_BIN" -m eval.propagation_transform_eval
"$PYTHON_BIN" -m eval.pc_scft_real_image_eval
"$PYTHON_BIN" -m eval.spectral_evidence_eval
"$PYTHON_BIN" -m eval.multistream_eval
"$PYTHON_BIN" -m eval.multistream_calibration_eval
"$PYTHON_BIN" -m eval.patch_contribution_eval
"$PYTHON_BIN" -m eval.joint_null_calibration_eval
"$PYTHON_BIN" -m eval.sequential_evidence_eval
"$PYTHON_BIN" -m eval.real_manifold_eval
"$PYTHON_BIN" -m eval.mpcf_eval
"$PYTHON_BIN" -m eval.crop_consensus_eval
"$PYTHON_BIN" -m eval.edit_lineage_eval
"$PYTHON_BIN" -m eval.lineage_view_control_eval
"$PYTHON_BIN" -m eval.evidence_grounded_explanation_eval
"$PYTHON_BIN" -m eval.operator_stability_eval
"$PYTHON_BIN" -m eval.counterfactual_mask_persistence_eval
"$PYTHON_BIN" -m eval.reference_specificity_eval
"$PYTHON_BIN" -m eval.evidence_graph_eval
"$PYTHON_BIN" -m eval.open_set_routing_eval
"$PYTHON_BIN" -m eval.invariant_effect_eval
"$PYTHON_BIN" -m eval.selection_aware_calibration_eval
"$PYTHON_BIN" -m eval.selection_aware_acquisition_eval
"$PYTHON_BIN" -m eval.selection_aware_propagation_gate_eval
"$PYTHON_BIN" -m eval.propagation_tree_null_eval
"$PYTHON_BIN" -m eval.retrieval_aware_tree_null_eval
"$PYTHON_BIN" -m eval.real_retrieval_event_eval
"$PYTHON_BIN" -m eval.temporal_lifecycle_gate_eval
"$PYTHON_BIN" -m unittest tests.test_counterfactual_validity -v
"$PYTHON_BIN" -m eval.counterfactual_validity_eval

# This check covers tracked diffs only; the Python hygiene check below also
# validates untracked text files and repository-local Markdown links.
git diff --check
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import re
import subprocess

root = Path.cwd()
untracked = subprocess.check_output(
    ["git", "ls-files", "--others", "--exclude-standard"], text=True
).splitlines()
text_suffixes = {
    ".css", ".go", ".html", ".js", ".json", ".md", ".py", ".sh",
    ".txt", ".yaml", ".yml",
}
trailing = []
for name in untracked:
    path = root / name
    if not path.is_file() or path.suffix not in text_suffixes:
        continue
    try:
        lines = path.read_text().splitlines()
    except UnicodeDecodeError:
        continue
    trailing.extend(
        f"{name}:{line_no}"
        for line_no, line in enumerate(lines, 1)
        if line.rstrip(" \t") != line
    )
if trailing:
    raise SystemExit("untracked trailing whitespace: " + ", ".join(trailing))

markdown_files = [root / "README.md", root / "AGENTS.md"]
markdown_files.extend(sorted((root / "docs").rglob("*.md")))
markdown_files.append(root / "eval" / "README.md")
missing = []
for path in markdown_files:
    text = path.read_text()
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        target = target.split("#", 1)[0]
        if target and not (path.parent / target).resolve().exists():
            missing.append(f"{path.relative_to(root)}:{target}")
if missing:
    raise SystemExit("missing Markdown links: " + ", ".join(missing))
print("repository text/link hygiene: OK")
PY
echo "lightweight verification: OK"
