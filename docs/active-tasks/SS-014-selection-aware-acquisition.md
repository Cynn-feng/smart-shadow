# SS-014：selection-aware-acquisition-v1（SAEA）

## 任务状态

- 阶段：阶段 7，离线研究契约
- 决策：D-061
- 状态：done（无重量模型离线契约；真实数据和同预算效果待验证）
- 目标 owner：后续 Agent 继续负责真实 manifest 和对照评测

## 目标

在 D-054 blind reference specificity、D-058 invariant-effect 和 D-060 SAEC 的 raw evidence 之上，使用固定动作集合和成本预算选择下一项 probe，并让每一步都可以通过 digest 回放。该切片只验证策略合同和失败闭合，不把主动采集本身称作独立算法创新。

## 独占文件

```text
aigc/selection_aware_acquisition.py
tests/test_selection_aware_acquisition.py
eval/selection_aware_acquisition_eval.py
aigc/__init__.py
scripts/verify_lightweight.sh
```

## 已完成内容

- 预注册 `append_matched_decoy`、`build_matched_null`、`alternate_view`、`alternate_operator`、`realign_quality` 五项动作及 cost units。
- 绑定 state input digest、output digest、action order、raw updates、失败原因和耗时。
- 重复动作、顺序/输入 digest 不一致、无效更新、预算耗尽和 executor failure 均 fail closed。
- 结果不包含 probability、confidence、作者、版权或法律字段；不接线上 detector、`aigc_result_v1` 或比赛服务。

## 验收

```bash
python3 -m unittest tests.test_selection_aware_acquisition -v
python3 -m eval.selection_aware_acquisition_eval
bash scripts/verify_lightweight.sh
git diff --check
```

当前专测 11 项通过；5 个 scalar runner case 的 route counts 为 `selection_specific_candidate=4`、`review=1`，dataset digest=`b8f6b1d60f84805e3f1e0824429d9a338e09f7563d66180912cd12ac69fa7697`。

## 未完成边界和下一步

真实验收需要同一冻结授权 manifest、独立 ordinary-propagation null、错误 reference、局部编辑、未见生成器、下一时间窗和低质量传播，并对照固定顺序 A9、去 decoy、去 null 和 no-extra-probe，报告 ordinary-propagation FPR、reference false-match、risk@coverage、ROI、route flip、P50/P95、动作成本和人工复核分钟。未通过 G0–G6 前保持阶段 7 离线 sidecar。

## 回滚

删除本任务涉及的模块、测试、runner、公共导出、验证脚本接入和文档；不修改 D-054、D-058、SAEC、旧顺序状态机或比赛版线上接口。
