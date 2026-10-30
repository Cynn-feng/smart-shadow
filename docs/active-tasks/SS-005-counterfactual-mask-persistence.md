# SS-005：Counterfactual mask persistence audit

- 阶段：阶段 7（离线算法研究）
- owner：next_algorithm_slice
- 状态：done
- 目标：把同一 source/query 候选区域在 factual view 与 ordinary-propagation/decoy/wrong-reference counterfactual 上的 mask persistence 与 null hallucination 变成可回放 raw-evidence 契约。
- 独占文件：`aigc/counterfactual_mask_persistence.py`、`tests/test_counterfactual_mask_persistence.py`、`eval/counterfactual_mask_persistence_eval.py`、本任务单。
- 共享文件（需先确认）：`aigc/__init__.py`、`scripts/verify_lightweight.sh`、`docs/07-验证与运行记录.md`。
- 不解决：真实 AIGC 准确率、真实 ROI、开放集概率、作者/来源/法律结论、线上服务接入。
- 验收命令：`.venv/bin/python -m unittest tests.test_counterfactual_mask_persistence -v`（10/10）、`.venv/bin/python -m eval.counterfactual_mask_persistence_eval`（6 cases）、`python3 -m py_compile aigc/counterfactual_mask_persistence.py eval/counterfactual_mask_persistence_eval.py tests/test_counterfactual_mask_persistence.py`、`git diff --check`。
- 回滚：删除本任务独占文件并移除公共导出/验证脚本接入；不改既有 PC-SCFT、SCTE、MPCF、Explanation、Lineage 或线上接口。
