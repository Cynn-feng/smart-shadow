# SS-015：D-062 source-conditioned propagation-tree null（SCPTN-v1）

## 任务状态

- 阶段：阶段 7，离线算法研究
- 状态：done（无重量 schema/树校验/null profile/synthetic runner；真实传播树待授权）
- 决策：D-062
- 独占文件：`aigc/propagation_tree_null.py`、`tests/test_propagation_tree_null.py`、`eval/propagation_tree_null_eval.py`、公共导出和轻量验证接入

## 目标

将同一登记资产的普通传播版本组织为一棵可回放树，以树为统计单位，在相同传播族、质量桶、时间桶和选择策略下校准树内最大 paired local delta，避免相关传播版本被重复计数或通过多次选择放大偶然差异。

## 已完成

- 树节点和父子拓扑校验：单根、父节点存在、拓扑顺序、唯一版本和同一资产绑定。
- 普通传播 null profile：独立 calibration asset、固定 selector、树级 max statistic、ties-inclusive p-value 和 split/manifest/digest 绑定。
- 固定 raw route：`tree_specific_candidate`、`tree_selection_ambiguous`、`tree_null_consistent`、`insufficient`。
- 结果不包含 probability、作者、版权或法律字段；普通传播 scope 不会升级为 candidate。
- 10 项专测和 5 个 scalar runner case 已通过；runner dataset digest=`70b1eab693ccb3bc670033b76ce8410366d5d6cfe0728daf4e0d94172dae8460`，profile digest=`759ccd5d6b9673d62eaeed270fe4dc6c023d9b878ed7a5e22affb0b85236dd2b`。

## 真实数据门

冻结 G0–G6 授权 manifest 后，比较 query-only、D-054、SAEC、SAEA、SCPTN、逐版本独立 null、去树相关性和完整组合。覆盖局部编辑、普通传播、错误 reference、未见生成器、下一时间窗、截图/再编码/再拍摄和低质量版本，报告 ordinary-propagation FPR、reference false-match、risk@coverage、ROI/边界 F、unknown/review、tree route flip、P50/P95、成本和人工复核分钟。当前切片不接线上服务。

## 回滚

删除 SCPTN 模块、测试、runner、公共导出、验证脚本接入、本任务单和对应文档记录；不修改 D-054、D-058、SAEC、SAEA、`aigc_result_v1` 或比赛版服务。
