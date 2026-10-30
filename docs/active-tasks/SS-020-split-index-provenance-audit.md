# SS-020：SIPA-LG-v1 跨索引来源与生命周期审计（SIPA 的首个子协议）

## 任务登记

- 阶段：阶段 7（离线研究）
- owner：待认领
- 状态：deferred（先完成 SS-032 真实 archive/index preparation 和 G0–G6）
- 独占文件：获批后仅限 `aigc/sipa_lifecycle_gate.py`、`tests/test_sipa_lifecycle_gate.py`、`eval/sipa_lifecycle_gate_eval.py`；认领前不得创建或改写
- 研究依据：[算法下一切片设计终审](../research/2026-09-21-算法下一切片设计终审.md)、[论文先例覆盖终审](../research/2026-09-21-论文先例覆盖终审.md)

## 目标

在 `ALG-001` 完成真实检索事件回放并由 `TLEG-A` 校验后，把 winner 选择与来源证据审计拆到两个独立索引：A 只负责候选生成和选择，冻结 winner/region；B 只对该对象做 direct lookup、`TLEG-B` 校验和 ordinary-propagation holdout gate。目标是审计跨索引泄漏、误召回、漏召回、检索投毒和生命周期错误造成的来源证据误报。

SIPA 不是新的 detector、retriever、conformal 理论、作者归因或法律证明；如果独立 B 只增加 `unknown/review` 而没有在相同 coverage、action budget 和人工成本下降低 ordinary-propagation FPR、wrong-reference false-match 或 poisoning route flip，应保留为审计 sidecar并撤回算法创新主张。

## 前置条件

- `SS-019/ALG-001` 已完成离线契约，并能在真实数据具备后从冻结 archive/index snapshot 重放候选、membership、tree 和 selection trace；当前真实数据仍为 `not_evaluated`。
- `SS-032` 已登记真实 archive/index preparation、授权、删除/访问审计、时间/生成器/传播/transport split 和双回放 digest 的冻结门；当前尚未有真实数据包。
- 已有授权 `real_pc_scft_manifest_v1`、独立 ordinary-propagation null、时间/生成器/传播切分和删除/留存责任。
- A/B 索引、calibration 和 evaluation 不共享会反向影响 winner 的 asset/group；B 不能只保留成功召回样本。

## 建议的代码切片顺序

1. 定义 `SIPASelectionV1`：绑定 A replay、TLEG-A、A/B snapshot、冻结 `winner_id`/`region_proposal_digest`、selection trace、canonical frame 和 action budget。
2. 实现 B direct lookup：至少两条独立 holdout 轴；禁止 B top-K、重排、重选 region、切换 operator 或重拟合 null。
3. 接入 TLEG-B 和 matched ordinary-null，保存 `p_B_raw`、support、contrast、质量/source-match、输入/证据/direct-lookup digest 和固定 route。
4. 补齐同 snapshot A=B（必须污染）、B reselect、B missing/stale/delete/restore、ordinary propagation、unknown/open-set、poisoning、wrong-reference、跨 split/group 和输入顺序 fixture，再与 ALG-001/RSCPTN 对照。

## 真实验收门

同一冻结 manifest、同一 action budget 和同一候选 coverage 下，至少比较 query-only、RSCPTN/ALG-001、SIPA、去 holdout、共享索引和 B 重新选择。报告 ordinary-propagation FPR、reference false-match、poisoning-induced route flip、accepted-sample selective risk、unknown/review、coverage、P50/P95、存储和人工复核分钟。真实数据不足时只输出 `not_evaluated`、`review` 或 `insufficient`，不得以 synthetic runner 填充效果。

## 回滚方式

删除 SIPA-LG adapter、测试、runner、公共导出、验证脚本接入和本任务单；保留 `ALG-001`、RSCPTN 和 TLEG raw contract，不修改 `aigc_result_v1`、比赛版服务或客户数据。完整 CFAEA 需另行批准，不能在本任务内顺带创建。
