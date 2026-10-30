# SS-006：持续开发目录与 Agent 协作入口

## 任务登记

- 阶段：阶段 0（文档和基线整理）
- owner：`/root/paper_algorithm_synthesis`
- 状态：done（目录治理由主任务统一完成）
- 独占文件：`docs/active-tasks/SS-006-docs-organization.md`
- 只读参考：`AGENTS.md`、`docs/00-当前任务说明.md`、`docs/01-项目决策记录.md`、`docs/02-项目记忆.md`、`docs/03-技术方案.md`、`docs/04-实施方案.md`

## 目标

把比赛结束后的持续开发入口整理成稳定的目录契约，让新 Agent 能够快速判断：当前事实在哪里、决策由谁维护、技术方案是否已批准、代码任务如何认领，以及哪些目录只能保存离线研究证据。

## 变更范围

- 记录目录治理任务的目标和验收边界；`docs/README.md` 的实际更新由主任务统一维护。
- 不改变业务接口、合约字段、状态机、特征 schema 或评测结果。
- 不移动比赛版源码和历史资料，避免破坏现有引用与未提交改动。

## 验收命令

```bash
git diff --check
rg -n "00-当前任务说明|01-项目决策记录|02-项目记忆|03-技术方案|04-实施方案" docs/README.md
```

## 未完成边界

本任务不代表任何 Go、MySQL、IPFS、Faiss、ChainMaker、真实图片或线上部署能力已经验证，也不替代 `docs/07-验证与运行记录.md`。

## 回滚方式

删除本任务单，并回滚 `docs/README.md` 中本任务新增的目录治理段落即可；不应使用 `git reset` 或覆盖其他 Agent 的未提交文件。
