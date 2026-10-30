# SS-010：D-058 invariant-effect-v1 跨视角 × 多算子不变性效应检验

- 阶段：阶段 7（离线算法研究）
- 决策依据：D-050、D-051、D-052、D-058
- 状态：done；离线契约已实现，真实数据未授权
- owner：root
- 独占文件：`aigc/invariant_effect.py`、`tests/test_invariant_effect.py`、`eval/invariant_effect_eval.py`

## 目标

把已经执行并绑定的 source-conditioned observed/null raw evidence，按多个 canonical view 和多个预注册 intervention operator 统一成一个保守的选择性检验。检验要求正向 effect 在两个 nuisance 轴上都保持，使用独立 ordinary-propagation null 计算有限样本 p-value；输出只属于 raw evidence/review route。

## 不做

- 不加载重量模型、不执行图像操作、不训练 detector。
- 不修改 `aigc_result_v1`、`ai_server.py`、Go 网关或线上接口。
- 不把 invariant effect、p-value 或 `invariant_candidate` 写成 AIGC 概率、作者/来源证明或法律结论。

## 最小契约

- 所有 observations 绑定 `asset_id/pair_id/manifest_digest/canonical_frame_digest/detector_version/score_schema/null_profile_digest`。
- 至少 3 个 views、2 个 operators、2 个 region 和 20 个独立 ordinary-propagation null statistics。
- 每个 view/operator 记录 observed effect、matched null effect、quality、source match、operator/view digest 和 execution digest。
- 对跨 view/operator 的 contrast 计算低分位 invariant effect、离散度、正向支持比例和 ties-inclusive finite-sample p-value。
- 固定路由：`invariant_candidate`、`null_consistent`、`view_operator_inconsistent`、`insufficient`。

## 验收

1. 完整绑定、顺序变化和重复运行产生相同 config/profile/result digest。
2. 只保留一个 view、一个 operator、少量 null、质量/source-match 不足、binding/schema/operator digest 冲突时均 `insufficient`。
3. 普通传播 null 不能成为 candidate；跨 view/operator spread 超限时进入 `view_operator_inconsistent`。
4. 结果序列化不包含 `probability`、`confidence`、`human_supported` 或 `ai_generated_supported` 字段。
5. runner 只使用 scalar fixture，输出 route counts、digest 和 raw statistics，不报告效果指标。

当前实现已接入 `aigc/__init__.py` 和 `scripts/verify_lightweight.sh`。专测与 runner 的实际结果写入
`docs/07-验证与运行记录.md`；这些结果只证明无重量模型的 raw contract、确定性和 fail-closed 行为。

## 真实数据门

冻结 `real_pc_scft_manifest_v1`、至少三类生成器的局部编辑 mask、同传播族 ordinary-propagation null、时间下一窗、截图/再编码/再拍摄和预注册 operator set；同一 manifest 比较单视角、单算子、view-only、operator-only、完整方案和去 null 消融，报告 ordinary-propagation FPR、ROI/边界 F、risk@coverage、unknown/review、route flip、P95、成本和人工复核分钟。

## 回滚

删除本任务的模块、测试、runner、公共导出和验证脚本接入；不修改既有 PC-SCFT、MPCF、Crop-Consensus、Lineage 或线上服务。
