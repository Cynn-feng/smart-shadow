# SS-032：ALG-001 真实 archive/index preparation 与 G0–G6 数据门

- 阶段：阶段 7（真实数据准备；不等于算法效果）
- owner：待认领
- 状态：ready（无授权数据时只能做 schema/validator/fixture）
- 独占文件：`configs/`、`artifacts/`、`eval/`、`docs/07-验证与运行记录.md`；不得改线上接口或客户数据
- 前置关系：主线 `SS-001` 可并行；本任务完成前不得编码完整 CFAEA 或 AR-SCMI

## 目标

冻结可独立回放的 `real_retrieval_archive_v1` 和 `real_pc_scft_manifest_v1` 准备包，供
ALG-001、SIPA-LG 和后续 CFAEA 使用。该任务只建立数据、权限、生命周期、切分和 digest
证据，不报告 FPR、coverage-risk、ROI、P95 或 AIGC 效果。

## 必须冻结的内容

- 授权原件、普通传播版本、局部编辑版本、wrong-reference/decoy 和删除/恢复记录；
- A archive/index snapshot、候选 rank、membership、传播树、selection trace；
- 时间、生成器、传播、transport、asset/group 的互斥 split；
- `snapshot_created_at`、ledger/index head、删除墓碑、留存规则、访问审计和回显策略；
- 文件/父子版本/manifest/archive/index/event/evidence digest，以及两次独立回放命令。

## 验收门

1. G0 权限与删除责任齐全，缺授权或过期固定 `unauthorized_input`；
2. G1 普通传播 null 独立于 query、selection 和评价 split；
3. G2 局部编辑包含真实 `edit_mask_digest`、步骤链和授权范围；
4. G3 覆盖错误 reference、decoy、unknown/open-set、poisoning；
5. G4 覆盖生成器/时间/传播/transport 外部切分、漂移与成本；
6. G5 固定 query-only、ALG-001/RSCPTN 和后续 SIPA-LG 的同预算对照；
7. G6 证据包可回放、删除/恢复可演练、人工复核责任人明确。

## 未完成边界与回滚

没有真实授权数据时只能提交字段 schema、validator 和 synthetic fixture；不得用合成
digest 代替真实数据门。若授权、删除、独立 null 或回放任一门失败，状态保持 `blocked`，
删除本任务新增的准备包和文档记录即可，不触碰 ALG-001、RSCPTN 或线上代码。
