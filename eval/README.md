# AIGC 评测入口

这里存放评测 manifest、切分规则和指标脚本，不直接提交第三方图片或受限模型权重。

当前提供 manifest 校验、契约测试和不依赖重量模型的合成/契约 runner；其中 `real_retrieval_event_eval` 只验证冻结检索快照、membership、传播树、selection trace、权限/删除/隐私门和拒判路由，明确输出 `real_data_status=not_evaluated`。`pc_scft_real_image_eval` 只验证私有授权图片的 manifest、哈希、解码、配对和无独立 null 时的拒判，`spectral_evidence_eval` 只验证频谱/相位 raw evidence 的合成回归和失败闭合，`multistream_eval` 只验证 pixel residual 与 spectral sidecar 的独立记录、冲突路由和缺流拒判，`multistream_calibration_eval` 只验证两条独立流的 ordinary-propagation null profile、有限样本 p-value 和保守交集路由，`patch_contribution_eval` 只验证 leave-one-out/top-k mask-out 的证据质量审计，`joint_null_calibration_eval` 只验证 group-matched 联合 null 的组合统计量、经验校准和冲突拒判，`sequential_evidence_eval` 只验证固定策略顺序回放、失败闭合、策略 digest 和 synthetic policy-FPR/Wilson CI，`regional_fdr_eval` 只验证逐区域 null p-value 和 BH 候选选择，`real_manifold_eval` 只验证 ONMA real-only natural-manifold profile 的授权门、开放集路由、版本化适配和拒判，`scte_eval` 只验证 observed/counterfactual 三元绑定和 regional FDR 适配，`mpcf_eval` 只验证 matched placebo 控制集绑定、ties-inclusive p-value 和 fail-closed 路由，`crop_consensus_eval` 只验证同一 source-conditioned pair 的多 crop canonical-frame 共识、质量桶和 ordinary-propagation crop-null 路由，`edit_lineage_eval` 只验证有序操作链、内容编辑 mask-overlap 门、普通传播 scope 分离和绑定拒判，`lineage_view_control_eval` 只验证有序 trace 的多视角 control-backed persistence、step onset order 和普通传播隔离，`operator_stability_eval` 只验证预注册多算子逐一 matched-null 对照、spread 门和缺失拒判，`counterfactual_mask_persistence_eval` 只验证 factual/null/decoy/wrong-reference mask persistence 和 null hallucination 的四格 raw contract，`evidence_graph_eval` 只验证跨版本 DAG 的拓扑、绑定和 fail-closed 路由。仓库仍没有真实图片效果评测结果，也没有可用于论文或产品宣传的准确率或 FDR 保证结论。`A0–A8` 是冻结的研究对照协议，不代表这些模型已经在本仓库接入。

ALG-001 `real_retrieval_event_eval` 当前固定输出 9 个 synthetic replay case，route counts 为 `candidate=1`、`insufficient=2`、`not_evaluated=1`、`null_consistent=1`、`open_set_unknown=1`、`review=3`，并打印 `real_data_status=not_evaluated`。该 runner 只验证 archive/index snapshot、membership、tree、selection、隐私/删除门和 fail-closed 路由；不证明真实召回、FPR、coverage-risk、ROI、P95、人工收益或部署能力。

## Manifest 最小字段

每行一个 JSON 对象，必须包含：

- `sample_id`：样本唯一 ID；
- `group_id`：原作品/作者/prompt/来源组，用于防止同源样本跨 split 泄漏；
- `split`：`train`、`validation`、`test` 或 `external`；
- `origin`：`camera_photo`、`human_digital`、`ai_full`、`ai_edit`、`unknown` 等；
- `generator_family`：生成器家族，真实图使用 `none`；
- `license`：授权或数据集许可说明。

建议同时保存 `sample_path`、`prompt_hash`、`edit_mask`、`postprocess_chain`、`resolution`、`c2pa_status` 和 `source_model`。原始图片和个人信息放在授权的私有存储中，仓库只保存 manifest、哈希和指标。

## 校验

```bash
python3 -m aigc.manifest eval/manifest.example.jsonl
python3 -m eval.source_residual_eval
python3 -m unittest discover -s tests -v
```

校验器会拒绝重复 `sample_id`、缺失必填字段、非法 split 和同一 `group_id` 跨训练/验证/测试集。真正的研究评测还必须按生成器、来源、时间和传播扰动报告 AUROC、FPR、ECE、unknown coverage-risk、局部 IoU、Recall@K 和 P95 延迟。

## source-residual-v1 合成回归 runner

`eval/source_residual_eval.py` 生成固定种子的归一化灰度网格，并对每个登记原件构造以下两类样本：

- hard negatives：原图、全局亮度/对比度/gamma/tone 变换和 codec-like 量化；
- positives：局部增亮、局部变暗、局部 patch 替换和局部噪声编辑。

runner 调用 `aigc.forensic_features.compare_aligned_regions`、`extract_residual_roi` 和 `aigc.calibration.fit_conservative_ai_threshold`，输出原始 `edit_score_raw` 的 AUROC、average precision、固定阈值诊断、验证集保守 operating point、按类别分布、合成 ROI IoU、hard-negative ROI 激活率和 `dataset_digest`。它只验证原语的确定性和回归趋势，不读取真实图片，不加载 CLIP/DCT/SRM，不产生生产校准 profile，也不判断 AIGC：

```bash
python3 -m eval.source_residual_eval \
  --seed 20260920 --repeats 3 --size 32 --threshold 0.20 \
  --output eval/results/source-residual-synthetic-v1.json
```

输出中的 `interpretation` 会明确写出“synthetic regression only”。固定阈值、验证集 operating point 和合成 ROI IoU 只是本地回归诊断，不能作为生产阈值、AIGC 概率、法律结论或真实数据效果；下一步必须用授权图片、真实传播链、时间/生成器切分和独立校准集替换该合成协议。

## 负例 conformal 拒判

`aigc.calibration.fit_negative_conformal_profile` 在冻结的验证集负例分数上建立单侧 profile，并复用现有 `CalibrationProfile` 的 `detector_version`、`score_schema`、`calibration_id` 和 `dataset_digest`。对“分数越高越像 AI”的取证分数，查询值 `s` 的负例 p-value 为：

```text
p_neg(s) = (1 + count(negative_score >= s)) / (n_negative + 1)
```

`evaluate_negative_conformal` 在 `p_neg <= alpha` 时返回 `unknown=true` 和 `unknown_reason=negative_conformal_reject`；否则只表示“没有被负例分布拒绝”。两种结果都不是 `human_supported` 或 `ai_generated_supported`，也不会绕过现有四态融合。运行时提供的 detector/schema/calibration ID 若与 profile 不一致会直接拒绝。profile 同时保存负例 score stream digest，便于发现预处理或模型漂移。

该接口是离线证据原语，尚未接入 `ai_server.py`。conformal 有效性依赖真正独立的校准流、无 group/作者/时间泄漏和与线上分数同分布；小样本只会产生粗粒度 p-value，不能外推真实覆盖率或法律结论。

## quality-aware near-duplicate fusion

`aigc.near_duplicate.fuse_near_duplicate_scores` 聚合同一 `asset_id` 的多个传播版本。每个版本必须携带唯一 `version_id`、raw detector score、`quality_score`、`detector_version` 和 `score_schema`。质量高于 `minimum_quality` 的版本按 `quality_score ** quality_power` 加权；低质量版本保留在 `version_audit`，但不进入分数。空输入、资产身份冲突、重复版本 ID、detector/schema 混用和全部低质量输入都会返回无分数及明确 `reason`，不会静默平均。

```bash
python3 -m eval.near_duplicate_eval
```

该 runner 构造同一资产的原图、JPEG、截图、再编码和低质量异常版本，比较单图、简单均值和质量加权 raw score，并输出完整审计与 digest。它只验证传播融合原语的确定性；`weighted_score_raw` 仍不是校准概率、AIGC 结论或法律结论，也没有接入线上服务。

## paired propagation stability 合成回归

`aigc.propagation_stability.fuse_propagation_stability` 与近重复质量加权
不同：它要求同一登记资产的多个传播版本在分数上保持稳定，并把同一传播族
的无编辑 `counterfactual` 版本作为 hard-negative 基线。加权观察分数减去
counterfactual 的加权 p95，再乘以传播分数的一致性因子；缺少配对族、分数漂移
过大或 hard-negative 分数过高时返回 `abstained=true`。所有值仍是 raw
evidence，不是 AIGC 概率或人类/AI 结论。

```bash
python3 -m eval.propagation_stability_eval
```

该 runner 只使用确定性的标量 fixture，覆盖稳定编辑、稳定低分、传播漂移、
counterfactual 误报和配对覆盖缺口。它只验证审计字段、拒判理由和确定性，不能
替代真实图片 adapter、授权传播链、时间/生成器切分或校准 coverage-risk 评测。

## image adapter 合成矩阵

`eval.image_adapter_matrix` 使用 Pillow 生成 9 个合成输入，覆盖 JPEG、PNG、WebP、
非动画 TIFF、BMP，以及非法 magic、截断、alpha policy 和像素上限失败边界。它调用
`aigc.image_adapter.decode_image_bytes`，输出检测格式、失败 reason、质量分项、原始/审计
摘要和 `dataset_digest`：

```bash
python3 -m eval.image_adapter_matrix
```

当前固定回归为接受 5/9，digest=`1a180411885260fb89ebe7656296e8e5e6406ae48eed49334bed22c972a09e99`。
依赖版本锁定在 `requirements-research.txt`（Pillow 12.3.0、NumPy 2.5.3）。该 runner
只证明解码器、配置和失败边界的可重复性，不代表真实图片质量、C2PA 签名验证、生产上传
安全或 AIGC 效果；真实 manifest 参数目前会被明确拒绝。

## 区域 PC-SCFT 合成回归

`eval.regional_alignment_eval` 是更前置的图像网格适配回归：它验证固定 resize、有限平移搜索、重叠/匹配质量门、确定性网格分区和坐标帧不一致拒判。该 runner 使用 NumPy 合成灰度网格，不读取真实图片，不代表真实配准精度或 AIGC 效果：

```bash
python3 -m eval.regional_alignment_eval
```

当前 digest=`8f0c3b7b555e14f3b8ff0d30b979663d8da24862bf2d29011bd08c3e3039c14f`；其输出只属于 raw evidence 工程回归。

`eval.regional_counterfactual_eval` 使用 5 组标量 fixture 验证区域级
observed/counterfactual 配对、质量权重、覆盖率、按区域传播稳定性和拒判。每个区域的
raw delta 定义为 `observed_score_raw - counterfactual_score_raw`；不同区域之间不互相当作
传播不稳定，稳定性只在同一 `region_id` 的传播视图内计算：

```bash
python3 -m eval.regional_counterfactual_eval
```

当前 digest=`a187e73c1678692e330e02c7dbe6113db31ad2e643addabc72d114f32eea39e7`，
stable positive acceptance=0.5、negative abstention=0.6667。该 runner 只输出 raw
evidence 和审计原因，不读取真实图片，不输出 AIGC 概率或法律结论；真实区域对齐、授权
传播族、质量条件校准和 coverage-risk 仍未验证。

## paired delta 分层 conformal 合成回归

`eval.paired_delta_calibration_eval` 使用 ordinary-propagation 标量 fixture，按
`transform_family × quality_bucket` 生成冻结的 null profile。每个校准组的统计量是
区域正 delta 的最大值，查询使用 ties-inclusive 的有限样本 p-value；runner 覆盖精确
分层、family fallback、global fallback 和没有兼容 null 的 `evaluated=false` 路径：

```bash
python3 -m eval.paired_delta_calibration_eval
```

该 runner 只证明分层、fallback、profile/dataset digest 和拒判字段可重复。`unknown=true`
仅表示拒绝普通传播 null，`unknown=false` 也不能推出人类创作；缺少 null 支持不会被当作
unknown。真实传播族、独立时间/作者切分、coverage-risk 和线上接入仍未验证。

## 区域级 conformal / BH 候选选择

`eval.regional_fdr_eval` 在同一登记原件和传播族内，把每个区域的 observed/counterfactual
正 delta 与按 `transform_family × quality_bucket × region_id × region_type` 匹配的
ordinary-propagation null 比较。runner 保存 ties-inclusive p-value、BH q-value、null
计数、分层键、profile/query digest，并在区域缺失、质量或来源匹配不足时固定拒判：

```bash
python3 -m eval.regional_fdr_eval
```

当前使用 24 组标量 null；局部候选选择 `r0`，普通传播和负 delta 路由为
`null_consistent`，缺失区域或质量/来源门进入 `insufficient`。profile digest 为
`d38a5a980bfa8aef6dce43f4bacccfb3298767fde8c42b7e6543fbb1859aa169`，dataset digest 为
`b0dda63eabe1b3a0f26dadaea928586691aa9be7d66efa7260092c9b11da5f21`。`candidate_regions`
只表示人工 ROI 复核候选，不是正式 FDR 保证、AIGC 概率、四态结论或法律证据；区域 p-value
交换性、空间相关性、选择后 FDR、真实 edit mask、跨生成器/时间切分和真实图片效果仍未验证。

## ONMA natural-manifold raw fallback 合成回归

`aigc.real_manifold_profile` 是无登记原件场景的 real-only raw fallback。它只接受
`real_authorized` 且 `authorized_for_research=true` 的固定维度特征，按 median/MAD 生成
不可变 profile，并以有界 `energy_raw` 和 profile threshold 输出开放集路由：
`in_distribution`、`out_of_manifold`、`insufficient`、`profile_mismatch`。低 energy 只表示
没有被当前真实校准流拒绝，高 energy 只表示偏离当前 profile；两者都不能证明人类创作或
AI 生成，也不会改写 `aigc_result_v1` 四态。

```bash
python3 -m eval.real_manifold_eval
```

runner 只使用固定的二维合成特征，覆盖授权/质量/支持数门、schema/detector/维度错配、
父 profile digest 绑定和 child profile 版本化适配。当前合成摘要为：`in_distribution=1`、
`out_of_manifold=1`、`insufficient=2`、`profile_mismatch=3`；dataset digest=`4c05084eb570a2afbaae1da6d12dda59d97babbf9dc0b5ae4b6366d34fd62c55`。
该 runner 不加载模型、不读取图片、不实现 latent hard negative 或生成器 prototype；真实授权
特征、跨生成器/时间切分、普通传播 hard negative、独立校准、coverage-risk、线上接入和
商业效果仍未验证。

## SCTE 三元区域证据适配合成回归

`aigc.scte.build_scte_query_deltas` 是从区域 observed/counterfactual 原语到
`RegionalQueryDelta` 的严格绑定层。它要求同一 asset/pair/manifest/reference、同一传播族和
`transform_spec_digest`、完整 alignment 坐标帧、完整 region set、detector/schema 及质量/来源门；
任何缺失或不一致都返回 `insufficient` 且不输出 delta。通过后 `e_edit=e_obs-e_null` 原样进入
`eval.regional_fdr_eval` 的区域候选选择器。

```bash
python3 -m eval.scte_eval
```

当前 5 个 synthetic case 覆盖局部编辑候选 `r0`、普通传播 `null_consistent`、缺失
counterfactual、区域集合不完整和坐标帧不一致。profile digest=`de6e4299e5d608d7503b8143721d0c42a26e5c23f0d9d43aef58a9be6684b1d4`，dataset digest=`fb69ff6d44639f7ce90b442573310fcdb754d2b3ddcf0160bf649c4fae44430c`。
结果只属于 raw 三元证据和 fail-closed 契约，不代表真实图片效果、正式 FDR 保证、AIGC 概率或法律结论。

## patch coverage 形状路由合成回归

`eval.patch_coverage_eval` 将已配对区域的 raw delta 转成质量和来源匹配门之后的形状
证据，计算正 delta 覆盖率、有效 patch 比例、集中度和正证据质量，并输出：

- `global_like`：分布式证据，路由到全图取证复核；
- `localized_like`：集中证据，路由到 ROI 复核；
- `ambiguous`：形状混合，主动拒判；
- `abstained`：质量/匹配/正证据不足。

```bash
python3 -m eval.patch_coverage_eval
```

该 runner 只使用 5 个标量 fixture。路由状态不等于 AIGC 四态，覆盖率和集中度也不是
概率；真实授权 mask、object/stuff/background 分层、传播扰动和独立阈值校准仍未验证。

## patch contribution / forensic distraction 审计

`eval.patch_contribution_eval` 接收已经通过质量和来源匹配门的 `PatchDelta`，对每个
accepted patch 执行 leave-one-out，并对 top-k 高贡献 patch 执行 mask-out。结果保留
`contribution_share_raw`、去除后的正证据质量、route flip、detector/schema/config/evidence
digest；单 patch 主导、top-k 后证据崩塌或路由翻转时进入 `distraction_sensitive`，不能静默
保留全图候选：

```bash
python3 -m eval.patch_contribution_eval
```

当前 runner 只有 5 个标量 fixture，覆盖分布式稳定、全局单 patch 干扰、局部集中、形状
歧义和无正证据，dataset digest=`3941c63d151ecf96d9254cb18895dc73b3739f34b8353a1f4a500c33247c969f`。
该切片是 raw evidence 质量审计，不是因果归因、AIGC 概率或法律证据；真实 edit mask、
semantic-boundary overlap、普通传播 hard negative、跨生成器/时间切分、独立校准和人工复核
收益仍未验证。

## PC-SCFT 统一决策协议合成回归

`aigc.pc_scft.decide_pc_scft` 将区域反事实结果、传播族/质量分层的 paired-delta null
校准和 patch coverage 形状证据在同一个审计边界内组合。它只允许四种取证路由状态：
`candidate_edit`、`null_consistent`、`review` 和 `insufficient`；这些状态不等于
`ai_generated_supported`、`human_supported` 或法律判断。默认配置拒绝 calibration fallback，
要求区域质量、来源匹配、配对覆盖和 null 支持均达到门槛。

```bash
python3 -m eval.pc_scft_eval
```

当前 runner 覆盖“null 被拒绝且形状可用”“普通传播 null 一致”和“null 被拒绝但形状混合
而转人工复核”三种组合。它仍是标量 fixture 的协议回归；真实授权图片、生成器切分、ROI
指标、FPR/coverage-risk、P95 和人工复核收益必须按 G0–G6 独立验证。

## A9 限预算主动证据获取合成回归

`aigc.evidence_budget.plan_evidence_acquisition` 根据现有 raw evidence 的缺口生成有界
行动计划。质量或来源匹配不达标时提前停止；其余动作按稳定优先级和成本单位选择，避免在
同一证据链重复执行已完成的动作。计划状态 `acquire`、`review`、`insufficient`、
`no_action` 都是调度状态，不是 AIGC 判断：

```bash
python3 -m eval.evidence_budget_eval
```

静态 planner 之外，`aigc.sequential_evidence` 已提供固定 action order、`policy_digest`、
输入/输出 digest、预算和失败/重复/乱序拒判的不可变 replay state；
`aigc.policy_calibration` 在完整 ordinary-propagation replay 上统计策略级 empirical FPR
和 Wilson CI。真实执行时仍必须把参数、耗时、失败原因和模型/profile 身份追加到 EvidenceV1；
预算耗尽后才进入拒判或人工复核。当前 4 个 planner fixture 与 6 条顺序 trace 只验证调度、
回放、校准 digest 和 fail-closed 契约，不能证明 risk-coverage-cost、ROI、真实 FPR 或真实
AIGC 效果。

```bash
python3 -m eval.sequential_evidence_eval
```

该 runner 的 policy FPR 仅是合成 ordinary-propagation trace 的经验统计，不是单张图片的
概率，也不代表真实授权数据、跨生成器/时间切分、传播扰动、人工复核收益或部署能力。

## G1 字节级普通传播变换回归

`eval.propagation_transform_eval` 调用 `aigc.propagation_transforms`，对同一 source/query 使用完全相同的 `TransformSpec`，覆盖 identity、JPEG 重编码、resize、center crop、blur、screenshot simulation 和 bounded composite。每个输出都带父/子哈希、格式、尺寸、操作链、Pillow toolchain、配置摘要和 pair digest；边界 fixture 覆盖非法质量参数和 identity 输出字节上限：

```bash
python3 -m eval.propagation_transform_eval
```

当前合成 runner digest=`db260592c577c94363f2950cdc4e4ab9006bea4137ca56b986fe510843bfdc74`，7/7 配对变换通过且 pair digest 稳定。该结果只证明字节级普通传播审计和 fail-closed 契约，不生成 AI 编辑、不判断来源、不输出 AIGC 概率；真实授权图片、真实传播链、打印/扫描/再拍摄和跨生成器效果仍未验证。

## 真实图片 PC-SCFT 私有契约 runner

`eval.pc_scft_real_image_eval` 在运行时生成三张合成图片，使用 `real_pc_scft_manifest_v1` 所需的授权编号、用途范围、期限、相对路径、SHA-256、角色和配对字段，调用 `aigc.real_image_runner` 完成：

```text
manifest/授权校验 → 文件哈希 → Pillow/NumPy 解码 → 统一坐标帧 → source-residual sidecar → observed/counterfactual 配对 → PC-SCFT 路由
```

```bash
.venv/bin/python -m eval.pc_scft_real_image_eval
```

当前合成结果的 manifest digest 为 `7ca073cc6714e32e4ec78b494df50239727f8ca3fccfc143c15efa53adcd772b`，重复执行结果 digest 为 `a13a8800a1404cb6d2963f008dabc52d47a438c3f0e714b5b09806ddaeab24df`；没有独立 ordinary-propagation null profile 时固定返回 `insufficient/calibration_unavailable`。结果只证明输入和证据契约可回放，不证明真实图片 AIGC 效果、ROI、概率或法律结论。

## 频谱/相位 raw evidence 合成回归

`aigc.spectral_evidence` 是与 source-residual 分开记录的研究对照支路，基于同一 source/query 坐标帧计算 phase circular incoherence、amplitude/high-frequency 变化，并用同一传播族 counterfactual 做 paired correction。它只输出版本化 raw evidence、质量字段、输入/配置/evidence digest 和固定失败原因，不改变 PC-SCFT 路由，也不输出 AIGC 四态、概率、作者身份或法律结论。

```bash
.venv/bin/python -m eval.spectral_evidence_eval
```

当前合成回归结果：`local_edit` 的 paired `score_raw=0.708162438302026`，`global_change` 与 ordinary-propagation hard negative 的 paired delta 均为 `0`；区域 raw scores 为 `0.6901744873143504` 和 `0.014269505813222326`；非有限输入固定返回 `nonfinite_input`，形状不匹配固定返回 `shape_mismatch`；`deterministic=true`，dataset digest=`daa2b0bc731a0ab4de96b5ff005fa6a4f04935ce21bb6aec76591f2055188033`。这些数值只属于当前 NumPy 合成 fixture 的 raw evidence 回归，不能外推为真实 AIGC 效果、校准概率、传播鲁棒性或法律证据；真实授权图片、频域校准、模型接入和线上服务仍未验证。

## 多流冲突感知路由回归

`aigc.multistream` 将 pixel residual 和 spectral sidecar 并列保存，在路由边界检查 paired/quality/metadata 完整性。它不平均分数，也不要求两路使用相同 detector/schema；跨流高低分进入 `conflict_review`，缺流、未配对或低质量进入 `insufficient`，两路一致时才分别进入 `candidate_edit` 或 `null_consistent`。所有状态都是 raw-evidence 复核路由，不是 AIGC 四态。

```bash
.venv/bin/python -m eval.multistream_eval
```

## 独立多流 null 校准回归

`aigc.multistream_calibration` 为 pixel residual 与 spectral/phase sidecar 分别保存 ordinary-propagation null profile，并使用 ties-inclusive conformal p-value。默认以 `alpha / stream_count` 做保守交集：所有流都拒绝各自 null 才进入 `candidate_edit`；所有流都与 null 一致才进入 `null_consistent`；一高一低或边界不一致进入 `conflict_review`；缺流、配对失败、低质量、schema 不匹配或 null 样本不足进入 `insufficient`。分数不跨流平均，也不输出 AIGC 概率、人类身份或法律结论。

```bash
.venv/bin/python -m eval.multistream_calibration_eval
```

## 联合 ordinary-propagation null 校准回归

`aigc.joint_null_calibration` 是现有逐流 Bonferroni 交集的研究对照分支。它只接收同一 ordinary-propagation group 中已校准的各流 p-value，先计算 Cauchy 组合统计量，再在独立且 group-matched 的联合 null profile 上做 ties-inclusive 经验校准。它不平均 raw score，也不把组合结果转成 AIGC 概率、人类创作结论或法律证据。缺流、stream set/schema 不一致、null 支持不足、p-value 分歧过大或 profile 与 query group 不满足隔离时必须拒判。

```bash
.venv/bin/python -m eval.joint_null_calibration_eval
```

当前 runner 只有 4 个标量 fixture，覆盖一致的中等证据、普通传播、流冲突和 profile 缺失；dataset digest=`a6beec1b4374989ef9527b8676df51b9e9aca1b016bb5ae0f589ea2bcf6f9185`。Cauchy 组合和联合 profile 都不是本项目独立学术创新，真实验证必须在同一授权 manifest 上与单流、Bonferroni、raw score 平均和去掉 counterfactual/质量分层的对照比较，并报告普通传播 FPR 及 95% CI、risk@coverage、unknown/review、ROI、P95、成本和人工复核分钟数；当前这些结果均未验证。

当前 synthetic runner 覆盖局部编辑、普通传播 hard negative、跨流冲突和缺失频谱流四类路由，dataset digest=`63683ed8e11ba44e1597fe9e6f1f6f3cf583004a1a71eb7ead0cb29396771576`。该 digest 只证明 profile、p-value 和路由的确定性；真实独立 null、流间相关性、跨生成器/时间切分和 coverage-risk 仍未验证。

当前 synthetic fixture 固定覆盖局部编辑 `candidate_edit`、普通传播 hard negative `null_consistent`、跨流冲突 `conflict_review` 和频谱流缺失 `insufficient`；dataset digest=`54c2508329a43aa9dcaac5ba5454c57d0fe64c002e24dd1370621c33be79efba`。这只证明独立 sidecar、冲突拒判和 digest 可回放，不证明真实图片效果、流间相关性、校准概率或线上 P95。

## Source-Conditioned Crop-Consensus 合成回归

`eval.crop_consensus_eval` 在共享 canonical coordinate frame 下构造同一
`reference/observed/counterfactual` pair 的多个 crop view，并与同绑定
ordinary-propagation crop-null 比较。它记录质量×source-match 加权的正向 view fraction、
可见区域集合的 Jaccard overlap、`consensus_raw` 和 ties-inclusive p-value：

```bash
python3 -m eval.crop_consensus_eval
```

当前三个 scalar case 路由为 `consensus_candidate`、`view_inconsistent` 和
`null_consistent`，dataset digest=`0693139527b8c08901e3baef91412cb4ba09acc59dcf10e0fe959381faedab8c`。
该 runner 只验证 crop/manifest/pair/canonical-frame/detector/schema/quality bucket 的绑定、
不可见区域不被当作负证据以及 fail-closed 行为，不代表真实 crop 鲁棒性、AIGC 效果、FPR、ROI、
正式统计保证或线上接入。

## Operation-aware ordered edit trace 合成回归

`aigc.edit_lineage` 审计声明的有序编辑操作链与区域 raw evidence 是否一致。每个
`EditTraceStep` 保存操作类型、顺序、父步骤、输入/输出区域和 mask digest；trace 还必须绑定
`pair_id`、传播族、canonical frame、manifest 和 binding digest。区域证据按质量与 source-match
门筛选，并检查 operation type、区域 lineage overlap、mask overlap 和逐步覆盖率。顺序缺口、未来
父步骤、绑定摘要缺失、质量不足或 operation/region 不一致都 fail-closed；结果只属于
`lineage_consistent`、`lineage_inconsistent` 或 `insufficient` 的 raw audit route，不是 AIGC
概率、来源/作者证明或法律结论：

```bash
python3 -m eval.edit_lineage_eval
```

当前 5 个 scalar fixture 覆盖有序局部操作、普通传播 trace、region lineage gap、binding 缺失和
质量缺口；dataset digest=`92c968fc140ba2de64e37acc1c1313bf9a53eb48d693537c5a490f322989c2da`，路由计数
为 `lineage_consistent=2`、`lineage_inconsistent=1`、`insufficient=2`。该 digest 只证明顺序/绑定/拒判
契约可回放；真实授权编辑 mask、跨生成器/时间切分、传播后定位和人工复核收益仍未验证。

## Ordered lineage multi-view matched-control 合成回归

该 runner 的输入是已绑定的 `EditLineageTrace`、多个 canonical view 的
observed/counterfactual delta 和上游 MPCF control summary。它按质量×来源匹配检查
view persistence、跨视角离散度和 step onset order；不重新拟合 placebo，也不加载图像模型。

```bash
python3 -m eval.lineage_view_control_eval
```

当前 5 个 scalar case 的路由计数为
`consistent_controlled_lineage=1`、`trajectory_inconsistent=1`、`insufficient=3`，
dataset digest=`28d3ecbe0fd827e766fcdb51f1d245a3c894e575fa8da91f8e171f61050c8ba3`。
普通传播和 binding/control 缺口固定拒判。所有输出仍是 raw evidence，不能解释为 AIGC
概率、来源/作者证明、正式 FDR 保证或法律结论；真实授权过程、mask、多视角图像、独立控制集、
跨生成器/时间切分和线上接入仍未验证。

## Smart Shadow 的最低评测矩阵

每次模型更新至少保留以下切分，不能只报随机 IID 测试：

- `known_generator`：训练中出现的生成器，用于检查基本能力；
- `unseen_same_family`、`unseen_architecture` 和 `commercial_black_box`：检查开放集泛化；
- `temporal_next_period`：按生成器发布时间模拟下一代模型；
- `partial_edit`：inpaint、outpaint、img2img、AI upscale 和人类图 + 局部 AI 编辑，必须有 ROI mask；
- `propagation`：JPEG、resize、裁剪、截图、打印/扫描/再拍摄和多轮平台重编码；
- `contradiction`：C2PA、用户声明、水印和视觉取证发生冲突的样本。

算法对照固定为 A0–A8：历史二分类器、全图 CLIP、CLIP+DCT+SRM、多尺度 ROI、重建复核、来源/开放集融合、质量感知传播融合、few-shot prototype 和最终 source-conditioned residual。A8 只有在外部授权数据上同时改善 coverage-risk、ECE、ROI IoU 和 P95 成本，才能写成创新结论。

## Version-DAG evidence consistency 合成回归

`eval.evidence_graph_eval` 只消费已经绑定的节点/边 raw sidecar，检查父节点存在、无环、初版禁止 merge、统一 binding context、普通传播 null profile 和内容编辑 declared mask。它计算 `new_support_raw`、`propagation_leak_raw`、`off_mask_gain_raw`、`branch_disagreement_raw` 和 `path_persistence_raw`，固定输出 `graph_consistent`、`propagation_leak`、`branch_conflict`、`trajectory_inconsistent` 或 `insufficient`：

```bash
.venv/bin/python -m eval.evidence_graph_eval
```

当前 6 个 scalar case 的路由计数为 `graph_consistent=1`、`propagation_leak=1`、`branch_conflict=1`、`trajectory_inconsistent=1`、`insufficient=2`，dataset digest=`bc14e91690b9bc194d83fa88deacf35f86ab41d77641cf975e5560e943edf621`。它不重算 detector、p-value 或 placebo，不改变 `aigc_result_v1`，也不是图神经网络、来源证明、AIGC 概率或法律结论；真实版本图、传播链、编辑 mask、时间/生成器切分、FPR/coverage-risk、ROI、P95 和人工复核收益仍未验证。
