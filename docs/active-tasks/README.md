# 当前 Agent 任务队列

这个目录只用于并行协作和文件认领，不是新的事实源。产品边界和取舍写入
`docs/01-项目决策记录.md`，当前事实写入 `docs/02-项目记忆.md`，阶段和验收写入
`docs/04-实施方案.md`，实际验证写入 `docs/07-验证与运行记录.md`。

视觉算法任务自 D-081 起在相邻工作区 [`../../../smart-shadow-vision-algorithm`](../../../smart-shadow-vision-algorithm) 登记；本队列只管理主项目落地和兼容边界。算法工作区有自己的任务队列和验证脚本。

开始任务前先运行 `git status --short`，复制 `docs/templates/agent任务单模板.md`，在任务描述中写清独占文件、阶段、验收命令和回滚方式。任务完成后把状态更新为 `done`、`blocked` 或 `deferred`，不要把“已写代码”写成“已部署”。

| 任务 ID | 阶段 | 目标 | 首选文件 | 状态 | 验收入口 |
| --- | --- | --- | --- | --- | --- |
| SS-001 | 阶段 1 | 结构化 AI/链回执和失败校验 | `cm_client.go`、`server.go`、`contract/` | ready | `git diff --check`、接口契约测试 |
| SS-034 | 阶段 7/0 | 视觉算法独立工作区提取与 landing 边界 | `/Users/cynn/project/smart-shadow-vision-algorithm`；主项目 pointer 文档 | done（工作区已建立；真实算法未验证） | 独立验证脚本、主项目链接卫生、`git diff --check` |
| SS-002 | 阶段 4/7 | 冻结 `real_pc_scft_manifest_v1` 和独立 ordinary-propagation null | `eval/`、`aigc/`、`docs/07-验证与运行记录.md` | blocked by authorized data | manifest 校验、真实数据审计 |
| SS-003 | 阶段 5 | 可复现依赖、readiness、迁移和恢复演练 | `start_all.sh`、部署配置、迁移文件 | deferred | 环境检查、服务 readiness、恢复演练 |
| SS-004 | 阶段 6 | MAM/DAM 只读 provenance/version/evidence sidecar 试点 | 先写 `docs/01`/`docs/04`，再定接口 | blocked by stages 1–5 | 500 原件/1000 传播样本 shadow 指标 |
| SS-005 | 阶段 7 | Counterfactual factual/null/decoy/wrong-reference mask persistence 审计 | `aigc/counterfactual_mask_persistence.py`、`tests/`、`eval/` | done | 10 tests、synthetic runner、`git diff --check` |
| SS-006 | 阶段 0 | 持续开发目录与 Agent 协作入口 | `AGENTS.md`、`docs/README.md`、`docs/research/`、目录 README | done | `git diff --check`、轻量验证、链接检查 |
| SS-007 | 阶段 7 | Blind reference specificity gate | `aigc/reference_specificity.py`、`tests/`、`eval/` | done | 13 项单测、5 个 synthetic case、`git diff --check` |
| SS-008 | 阶段 7 | Version-DAG evidence consistency audit | `aigc/evidence_graph.py`、`tests/test_evidence_graph.py`、`eval/evidence_graph_eval.py` | done（合成契约） | 10 项单测、6 个 synthetic case、轻量验证、`git diff --check` |
| [SS-009](SS-009-real-family-router.md) | 阶段 7 | D-057 分层 real-family selective routing（D-056 后续，暂缓编码） | `aigc/real_family_router.py`、`tests/test_real_family_router.py`、`eval/real_family_router_eval.py` | deferred（先例重合，暂缓编码） | 仅在重新批准后补契约测试、合成 runner、轻量验证、`git diff --check` |
| [SS-010](SS-010-invariant-effect.md) | 阶段 7 | D-058 跨视角 × 多算子不变性效应检验 | `aigc/invariant_effect.py`、`tests/test_invariant_effect.py`、`eval/invariant_effect_eval.py` | done（离线契约；真实数据待授权） | 专测、合成 runner、轻量验证、`git diff --check` |
| [SS-011](SS-011-market-business-refresh.md) | 阶段 6 研究输入 | 市场与商业化深度刷新：竞争替代、首单切口、收费实验和 30/60/90 天试点门 | `docs/research/2026-09-20-商业化深度刷新.md`（不改代码） | done（外部资料/文档审计） | 文档链接检查、外部官方 URL 抽查、`git diff --check` |
| [SS-012](SS-012-docs-governance-refresh.md) | 阶段 0 | 固定四份核心文档职责、研究编号口径和 Agent 交付记录 | `docs/00–04`、`docs/README.md`、`README.md` | done（仅文档治理） | `git diff --check`、轻量验证、入口卫生检查 |
| [SS-013](SS-013-selection-aware-calibration.md) | 阶段 7 | SAEC-v1：检索 winner 的选择后分层证据校准 | `aigc/selection_aware_calibration.py`、`tests/`、`eval/` | done（无模型离线契约；真实数据待授权） | 15 项专测、6 个 scalar runner、轻量验证、`git diff --check` |
| [SS-014](SS-014-selection-aware-acquisition.md) | 阶段 7 | SAEA-v1：固定预算下按失败原因选择下一项证据 probe | `aigc/selection_aware_acquisition.py`、`tests/`、`eval/` | done（无模型离线契约；同预算真实效果待验证） | 11 项专测、5 个 scalar runner、轻量验证、`git diff --check` |
| [SS-015](SS-015-propagation-tree-null.md) | 阶段 7 | SCPTN-v1：按传播树校准树内版本选择后的最大 paired local delta | `aigc/propagation_tree_null.py`、`tests/`、`eval/` | done（无重量契约；真实传播树和同预算效果待验证） | 10 项专测、5 个 scalar runner、轻量验证、`git diff --check` |
| [SS-016](SS-016-market-signal-refresh-20260921.md) | 阶段 6 研究输入 | 商业信号、首客切口和四周 shadow 验收门刷新 | `docs/research/2026-09-21-商业信号与首客切口刷新.md`、`docs/research/外部证据索引.md` | done（外部资料/文档审计；客户和付费未验证） | 官方 URL 抽查、链接卫生、`git diff --check` |
| [SS-017](SS-017-retrieval-aware-tree-null-research.md) | 阶段 7 | D-063 RSCPTN-v1：检索污染感知的传播树选择校准 | `aigc/retrieval_aware_tree_null.py`、`tests/test_retrieval_aware_tree_null.py`、`eval/retrieval_aware_tree_null_eval.py`、研究文件 | done（最小离线契约；真实数据待 G0–G6） | 专测、合成 runner、轻量验证、Markdown 链接、`git diff --check` |
| SS-018 | 阶段 6（阻塞） | D-064 `EvidenceSidecarV1` 私有图库/DAM 只读 shadow 试点 | 先写 `docs/01`、`docs/03`、`docs/04`，再定接口和隔离部署 | blocked by stages 1–5 and authorized customer data | D0–D28 试点门、权限/删除/回放和人工基线 |
| [SS-019](SS-019-retrieval-event-replay.md) | 阶段 7（离线研究） | ALG-001：RSCPTN 实际检索/树/选择事件回放 | `aigc/retrieval_event_replay.py`、`tests/test_retrieval_event_replay.py`、`eval/real_retrieval_event_eval.py` | done（offline contract implemented；真实数据和 G0–G6 pending） | 12 项专测、9-case runner、event replay/digest/privacy/generator-family fail-closed、全量轻量验证、`git diff --check` |
| [SS-020](SS-020-split-index-provenance-audit.md) | 阶段 7（离线研究） | SIPA-v1；先收窄为 SIPA-LG 的 A/B holdout + TLEG + B direct lookup | `aigc/`、`tests/`、`eval/`（获批后） | deferred（先完成 SS-032 真实 archive/index preparation 和 G0–G6） | fixed winner/region、B direct lookup、TLEG-A/B、matched null、泄漏/投毒/误召回拒判 |
| SS-021 | 阶段 0/7/6 研究收敛 | 市场、商业化与 AIGC 算法创新终审汇总 | `docs/research/2026-09-21-市场拓展第二轮深度调研.md`、`docs/research/2026-09-21-市场商业化与AIGC算法创新终审.md`、`docs/00–04` 导航同步 | done（文档研究；客户、真实数据和部署未验证） | `git diff --check`、轻量验证、Markdown/link hygiene |
| [SS-022](SS-022-propagation-envelope-audit.md) | 阶段 7（离线研究） | D-070 PE-CEA-v1：按传播严重度分层的 ordinary-null envelope 与局部效应曲线审计 | `aigc/propagation_envelope.py`、`tests/test_propagation_envelope.py`、`eval/propagation_envelope_eval.py`、`docs/03–04` | done（无重量离线契约；真实数据待 G0–G6） | 专测、synthetic runner、轻量验证、字段/链接卫生、`git diff --check` |
| [SS-023](SS-023-dual-registry-confounder-audit.md) | 阶段 7（离线研究） | D-071 DRCS-v1：分离 asset registry 与 generator registry 的来源/伪影混淆 | 获批前不占用代码文件；未来限 `aigc/`、`eval/`、`tests/` | deferred（先完成 ALG-001 真实数据和 G0–G6） | 任务/字段审查；获批后另行登记专测、runner、冻结 manifest 和回放 digest |
| [SS-024](SS-024-metadata-mutation-guard.md) | 阶段 6（商业验证） | D-072 `MetadataMutationGuardV1 + provenance_conflict_replay` 私有 DAM/MAM sidecar | 获批前限 `configs/`、`artifacts/`、validator/fixture；不得改线上接口 | blocked（阶段 1–5、客户授权、删除责任人和人工基线未齐） | 只读 shadow 前置审计；字段完整率、冲突回放、删除/恢复、权限和人工基线 |
| [SS-025](SS-025-open-set-propagation-gate.md) | 阶段 7（安全修补） | D-073 为 SAEA 增加 generator/open-set/replay propagation gate | `aigc/selection_aware_acquisition.py`、`tests/`、`eval/`、公共导出 | done（离线契约；真实效果待验证） | 12 项 gate 专测、10-case runner、unknown/冲突/缺失支持 fail-closed；known family、real-only neutral、ordinary null 和 digest 稳定性 |
| [SS-026](SS-026-commercial-pilot-convergence.md) | 阶段 6 研究输入 | 商业试点与拓展执行收敛：S0–S5、D0–D28 shadow、收费单位和停止门 | `docs/research/2026-09-21-商业试点与拓展收敛.md`（只读研究与文档） | done（外部资料/文档审计；客户和付费未验证） | 官方来源抽查、Markdown 链接卫生、`git diff --check` |
| [SS-027](SS-027-paper-frontier-20260921.md) | 阶段 7（研究输入） | 核验 2025–2026 AIGC 检测、局部取证、provenance、开放集、传播鲁棒和反取证一手论文 | `docs/research/2026-09-21-论文前沿补充.md`（只读研究与文档） | done（外部资料/文档审计） | 官方论文/论文页抽查、Markdown 链接卫生、`git diff --check` |
| [SS-028](SS-028-official-market-expansion-audit.md) | 阶段 6 研究输入 | 官方市场扩展与商业价值审计：标识/来源 readiness、DAM/MAM sidecar、争议取证和供应链 provenance | `docs/research/2026-09-21-官方市场扩展与商业价值审计.md`（只读研究与文档） | done（官方资料/文档审计；客户、价格、收入和部署未验证） | 官方 URL 抽查、Markdown 链接卫生、`git diff --check` |
| [SS-029](SS-029-cfaea-v1-cross-fitted-evidence-audit.md) | 阶段 7（离线研究） | CFAEA-v1：A/B split-index、asset/generator registry cross-fit 与 matched ordinary-null 证据审计 | `docs/research/2026-09-21-CFAEA-v1研究设计.md`；获批后才可占用 `aigc/cfaea.py`、`tests/test_cfaea.py`、`eval/cfaea_eval.py` | P0 design-ready / deferred encoding | 先完成 ALG-001 真实回放和 G0–G6；获批后再做 contract/replay/registry/eval 四个切片 |
| [SS-030](SS-030-paper-frontier-audit.md) | 阶段 7（研究输入） | 论文前沿深度审计与最窄白区：AR-SCMI-v1 attack-robust source-conditioned matched intervention | `docs/research/2026-09-21-论文前沿深度审计与白区.md`（只读研究与文档） | done（外部论文/标准审计；算法效果未验证） | 一手论文/官方页面抽查、Markdown 链接卫生、`git diff --check` |

| [SS-031](SS-031-temporal-lifecycle-evidence-gate.md) | 阶段 7（离线研究契约；阶段 1–5 前置门） | D-077 TLEG-v1：时序/生命周期证据门，阻断 future/stale/tombstoned evidence 升级 | `aigc/temporal_lifecycle_gate.py`、`tests/test_temporal_lifecycle_gate.py`、`eval/temporal_lifecycle_gate_eval.py` | done（无重量契约；真实生命周期数据待授权，未接线上） | 20 项专测、18-case runner、383/40 统一轻量验证、`git diff --check` |
| [SS-032](SS-032-real-archive-index-preparation.md) | 阶段 7（真实数据准备） | ALG-001 真实 archive/index preparation 与 G0–G6 数据门 | `configs/`、`artifacts/`、`eval/`、`docs/07-验证与运行记录.md` | ready（无授权数据时仅 schema/validator/fixture） | manifest、A/B snapshot、rank/membership/tree/selection trace、删除/访问审计、双回放 digest |
| [SS-033](SS-033-counterfactual-validity-gate.md) | 阶段 7（离线研究契约） | D-080 CIVG-v1：counterfactual intervention validity gate，阻止无效干预进入 PC-SCFT | `aigc/counterfactual_validity.py`、`tests/test_counterfactual_validity.py`、`eval/counterfactual_validity_eval.py` | done（offline contract；真实效果待 G0–G6） | 15 项专测、14-case synthetic runner、字段卫生、轻量验证、`git diff --check` |

研究切片可以在阶段 7 离线并行，但不得绕过阶段 1–5 接入线上或客户；没有授权 manifest、独立 null 和外部切分时，只能输出 raw evidence、`review` 或 `insufficient`。
