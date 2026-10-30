# SS-012：核心文档职责与持续开发入口刷新

## 任务登记

- 阶段：阶段 0（文档和基线整理）
- owner：`/root/algorithm_research_refresh`
- 状态：done（仅文档治理）
- 独占文件：`docs/00-当前任务说明.md`、`docs/01-项目决策记录.md`、`docs/02-项目记忆.md`、`docs/03-技术方案.md`、`docs/04-实施方案.md`、`docs/README.md`、`README.md`
- 不改范围：业务接口、合约字段、模型、评测 schema 和线上服务

## 目标

固定比赛结束后的持续开发目录、四份核心文档职责、研究编号口径和 Agent 交付记录，减少新 Agent 在历史 README、研究候选和当前事实之间误判。

## 验收命令

```bash
git diff --check
rg -n "D-059|状态快照|方案变更门|Agent 交付最小记录" docs/00-当前任务说明.md docs/01-项目决策记录.md docs/03-技术方案.md docs/04-实施方案.md
bash scripts/verify_lightweight.sh
```

## 边界与回滚

这些改动只建立导航和记录规则，不证明 Go、数据库、IPFS、Faiss、ChainMaker、真实图片、部署或商业能力。回滚时删除本任务单并撤回本任务新增的文档段落，不覆盖其他 Agent 的未提交修改。
