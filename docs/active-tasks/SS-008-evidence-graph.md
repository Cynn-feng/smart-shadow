# SS-008：Version-DAG evidence consistency audit

- 阶段：阶段 7（离线算法研究）
- owner：`/root`
- 状态：done（无重量合成契约；真实版本图和客户数据未验证）
- 目标：审计同一登记资产的父子传播、内容编辑、兄弟分支和后代证据是否满足拓扑与 sidecar 绑定约束。
- 独占文件：`aigc/evidence_graph.py`、`tests/test_evidence_graph.py`、`eval/evidence_graph_eval.py`、本任务单。
- 共享文件：`aigc/__init__.py`、`scripts/verify_lightweight.sh`、`docs/01`、`docs/02`、`docs/03`、`docs/04`、`docs/06`、`docs/07`、`docs/09`。
- 输出边界：只输出 `graph_consistent`、`propagation_leak`、`branch_conflict`、`trajectory_inconsistent`、`insufficient` raw audit route；不重算 detector、p-value 或 placebo，不改变 `aigc_result_v1`。
- 验收命令：`.venv/bin/python -m unittest tests.test_evidence_graph -v`、`.venv/bin/python -m eval.evidence_graph_eval`、`bash scripts/verify_lightweight.sh`、`git diff --check`。
- 回滚：删除本任务独占文件，移除公共导出和验证脚本接入；不修改 D-050–D-054 的原始 evidence。
