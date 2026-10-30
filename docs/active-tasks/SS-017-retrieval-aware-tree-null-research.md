# SS-017：检索污染感知的传播树选择校准研究

- 阶段：阶段 7 研究输入（仅文档，不接线上）
- owner：AIGC 前沿刷新 agent
- 独占文件：`docs/research/2026-09-21-检索污染感知传播树选择校准.md`、`aigc/retrieval_aware_tree_null.py`、`tests/test_retrieval_aware_tree_null.py`、`eval/retrieval_aware_tree_null_eval.py`、本任务单
- 目标：审计 SCPTN/SAEC/SAEA 对真实近重复检索缺失、误召回、未知生成器和端到端选择事件的遗漏，提出可证伪的下一算法切片
- 数据影响：只定义研究 manifest/sidecar 要求，不写入客户数据，不修改 `aigc_result_v1`
- 代码影响：已完成无重量离线契约；不接 `aigc_result_v1`、线上服务或客户数据
- 验收命令：`python3 -m unittest tests.test_retrieval_aware_tree_null -v`、`python3 -m eval.retrieval_aware_tree_null_eval`、`bash scripts/verify_lightweight.sh`、`git diff --check`；Markdown 链接和外部一手来源 URL 抽查
- 已验证层级：外部论文/官方论文页审计、无重量契约、合成 fixture、拒判和字段卫生；没有真实图片、模型、部署或效果验证
- 回滚方式：删除本任务单和研究文件；不触碰 D-054、D-058、D-060、D-061、D-062 或线上接口
- 状态：done（最小离线契约；真实数据、商业价值和学术增量待 G0–G6）
