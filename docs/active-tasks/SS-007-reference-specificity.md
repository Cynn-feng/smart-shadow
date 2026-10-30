# SS-007：Blind reference specificity gate

- 阶段：阶段 7（离线算法研究）
- owner：`/root`
- 状态：done（离线契约完成；真实参考库和效果未验证）
- 目标：控制错误登记原件选择造成的 source-conditioned 局部编辑误报。
- 独占文件：`aigc/reference_specificity.py`、`tests/test_reference_specificity.py`、`eval/reference_specificity_eval.py`、本任务单。
- 共享文件（需先确认）：`aigc/__init__.py`、`scripts/verify_lightweight.sh`、`docs/07-验证与运行记录.md`。
- 不解决：真实 AIGC 准确率、真实 reference false-match rate、作者/来源/法律结论、线上服务接入。
- 验收命令：`.venv/bin/python -m unittest tests.test_reference_specificity -v`、`.venv/bin/python -m eval.reference_specificity_eval`、`python3 -m py_compile ...`、`git diff --check`。
- 实际结果：13 项单测通过；5 个 synthetic case 路由为 `reference_specific_candidate=1`、`reference_ambiguous=1`、`reference_null_consistent=1`、`insufficient=2`；dataset digest=`e5364f50b62519fe5ab6f0bf74563ee3f826e700597c356a10272d525ab74dec`，config digest=`930bd181c3d7b61869c4a88605ac9cb0ef53324bdbc52ea22e0e66a7bf2160ca`。
- 统计边界：使用 ties-inclusive 有限样本 p-value `(1 + exceedances) / (n + 1)`；3 个 decoy 的最小 p 值为 0.25，因此特异候选合成样例使用 24 个 decoy。`specificity_gap_raw` 的合法范围为 `[-4, 4]`。
- 回滚：删除本任务独占文件，移除公共导出和验证脚本接入；不修改现有 PC-SCFT/SCTE/MPCF/Explanation/Lineage 或比赛版服务。
