# SS-029：CFAEA-v1 来源—生成器交叉拟合证据审计

## 任务登记

- 阶段：阶段 7（离线研究）
- owner：`/root/algorithm_innovation_design`（设计）；编码 owner 待主 Agent 批准
- 状态：`P0 design-ready / deferred encoding`
- 设计文档：[CFAEA-v1 研究设计](../research/2026-09-21-CFAEA-v1研究设计.md)
- 依赖：[SS-019 / ALG-001](SS-019-retrieval-event-replay.md)、[SS-020 / SIPA](SS-020-split-index-provenance-audit.md)、[SS-023 / DRCS](SS-023-dual-registry-confounder-audit.md)、G0–G6
- 独占文件（获批编码后）：`aigc/cfaea.py`、`tests/test_cfaea.py`、`eval/cfaea_eval.py`；认领前不得创建或修改
- 当前明确不修改：`aigc_result_v1`、`ai_server.py`、Go 网关、合约、比赛版 `/check`、客户数据和线上接口

## 目标与最窄主张

把四个独立性门绑定到同一个可回放研究事件：

1. A 负责 retrieval → membership → propagation tree → fixed winner/region；
2. B 只 direct lookup 冻结 winner，禁止重新排序或替换 reference；
3. `asset_registry` 负责登记原件/版本/ordinary-propagation null，`generator_registry` 负责 real-only/family/open-set controls；
4. source contrast 与 generator evidence 使用独立 group/time/family fold，冲突或未知时拒判。

待证伪主张是：在相同 candidate coverage、action budget 和人工预算下，该组合是否降低 ordinary-propagation FPR、reference/decoy false-match、poisoning route flip 或 accepted-sample selective risk，同时不牺牲 coverage、局部 ROI、unknown recall、P95、成本和人工复核分钟。它不是新 detector、新检索器、新树算法、新 conformal/e-value 理论或作者/版权证明。

## 前置条件

- ALG-001 能从冻结 archive/index snapshot 重放 candidate、membership、tree 和 selection trace；真实数据状态不得以 synthetic runner 代替。
- 有授权 `real_pc_scft_manifest_v1`、独立 ordinary-propagation null、blind decoy/wrong-reference、真实局部 edit mask 和时间/生成器/传播 external split。
- A/B archive、AR/GR profile、calibration 和 evaluation 按 asset/group、generator family、时间分流；B 不反向影响 A，GR 不参与 winner 或 source-null 拟合。
- 有删除墓碑、访问审计、保留期限和证据包复核责任人；缺失时固定 `not_evaluated` 或 `insufficient`。

## 计划切片

1. **Contract**：定义 `CFAEAInputV1` / `CFAEAResultV1`，校验 A/B/AR/GR digest、fold、direct lookup、matched null、confounder gate 和禁用字段；只使用标量 evidence。
2. **Replay adapter**：从 `RetrievalEventReplayV1` 生成 A trace，冻结 winner/region，再把 B direct lookup 交给独立 null profile；B 不重选。
3. **Registry adapter**：接入 real-only/family/open-set generator profile 和 generator-matched controls；支持 `generator_only_unknown` 与 `source_generator_conflict_review`，不把 GR 命中写成 AIGC 结论。
4. **Evaluation runner**：覆盖 clean、ordinary propagation、blind decoy、wrong-reference、missing B、A/B leakage、B reselect、retrieval miss/poisoning、unknown generator、next-time-window、截图/再编码和局部 mask；没有真实数据只输出 `not_evaluated`。

## 固定路由

```text
holdout_consistent
source_generator_conflict_review
generator_only_unknown
ordinary_propagation_consistent
selection_contaminated
missing_holdout
open_set_unknown
insufficient
not_evaluated
```

普通传播不能进入 candidate；B 缺失不能回退 A；`p_B_raw` 只能是 ties-inclusive raw rank；任何 `aigc_probability`、`confidence`、作者、版权或法律字段均禁止。

## 评测与成功门

完整协议必须与 query-only、asset-only/RSCPTN/ALG-001、SIPA、generator-only 以及去 null、去 decoy、去 replay、共享 A/B、B reselect、去 cross-fit、去 GR confounder 的版本做同 manifest、同 coverage/action budget 对照，报告 ordinary-propagation FPR、reference false-match、poisoning route flip、risk@coverage、unknown/review recall、ROI/boundary-F、P50/P95、成本、存储和人工分钟。

只有当以下条件全部预注册并通过才可讨论研究增量：

- A/B/AR/GR/calibration/evaluation 可独立回放且无 group/time/generator/query/operator 泄漏；
- 主要 FPR 与至少一个 source false-match/poisoning 指标达到预注册改善 `delta_primary`；
- coverage、accepted risk、unknown recall、ROI、P95、成本和人工分钟处于预注册非劣化边界；
- generator-family leave-one-out、next-time-window 和真实传播 external split 重复方向；
- B missing、open-set、conflict、ordinary propagation 都 fail closed。

## 撤回门

只增加 `unknown/review`、只在 IID/已知生成器或 synthetic fixture 有收益、A/B 或 AR/GR 泄漏、B 重选、GR 污染 source-null、ordinary propagation 被升级、外部 split 失效、P95/成本/人工负担恶化或 null 无法独立回放，均降级为 provenance/confounder audit sidecar，不称 AIGC 算法创新。

## 验收与交付边界

获批编码后：

```text
python3 -m unittest tests.test_cfaea
python3 -m eval.cfaea_eval
git diff --check
bash scripts/verify_lightweight.sh
```

在此任务当前设计阶段，以上命令不应被虚报为已执行；真正实现时把命令、digest、结果和未验证项写入 `docs/07-验证与运行记录.md`。设计文档和任务单本身的校验只使用链接检查与 `git diff --check`。代码完成也不等于真实图片、部署或商业验证。

## 回滚

删除本任务单、研究设计及获批后新增的 `cfaea` adapter/test/runner/export；保留 ALG-001、RSCPTN、SIPA/DRCS 原有 deferred 设计，不修改线上接口、`aigc_result_v1` 或比赛版服务。
