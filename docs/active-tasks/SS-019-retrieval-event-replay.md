# SS-019：ALG-001 RSCPTN 实际检索事件回放

## 任务登记

- 阶段：阶段 7（离线研究）
- owner：`alg001_replay_impl`
- 状态：done（offline contract implemented；真实数据和 G0–G6 pending）
- 独占文件：`aigc/retrieval_event_replay.py`、`tests/test_retrieval_event_replay.py`、`eval/real_retrieval_event_eval.py`
- 只读参考：`docs/01-项目决策记录.md` D-063/D-065、`docs/02-项目记忆.md`、`docs/03-技术方案.md`、`docs/research/2026-09-21-算法实现缺口与下一代码切片.md`

## 目标

把冻结的 retrieval archive/index snapshot、membership 判定、传播树解析、reference/version selection 和局部 raw evidence 连接成可回放 `RetrievalEvent`，验证 RSCPTN 是否真正处理检索污染和选择偏差。

## 允许范围

- 只新增 `aigc/`、`eval/`、`tests/` 的离线契约和研究 runner。
- 复用现有 RSCPTN、PC-SCFT、MPCF、SAEC raw sidecar，不训练新 detector。
- 没有真实授权数据时可以运行结构校验和 `insufficient`/`not_evaluated` fixture，但不得伪造效果指标。

## 必须拒判

- parent 跨 `asset_id/tree_id`、成环、depth/branch 不一致或多个 root；
- candidate snapshot、membership、selection trace、输入文件或上游 evidence digest 无法重算；
- 局部编辑缺 `edit_mask_digest`、`edit_type` 或步骤链；
- 授权、archive、独立 ordinary-null、split 隔离或删除责任人缺失。

## 验收

```bash
python3 -m unittest tests.test_retrieval_event_replay -v
python3 -m eval.real_retrieval_event_eval
bash scripts/verify_lightweight.sh
git diff --check
```

同一 manifest/archive 重放必须得到相同 digest；替换候选快照、rank、membership、parent 或 action 顺序必须改变 binding 或触发拒判。当前 12 项专测和 9 个 synthetic case 已通过，包含 clean、missing、false-positive、planted near-duplicate、wrong-reference、ordinary propagation、unknown generator、next-time-window 和 poisoning 对照；runner 明确输出 `real_data_status=not_evaluated`。

## 未完成边界

当前没有真实 retrieval archive、授权图片、独立 null profile、真实 edit mask、跨时间窗或客户数据；本任务完成也不代表 RSCPTN 已成为有效 AIGC detector、概率校准或线上能力。snapshot replay 使用冻结 archive entries 做确定性排序回放，不等同于真实索引召回；近重复 fixture 因 membership/profile 分层不一致固定 `insufficient`，属于校准支持不足拒判。

## 回滚方式

删除 replay adapter、测试、runner 和本任务单；保留现有 RSCPTN raw contract，不修改 `aigc_result_v1`、比赛版服务或客户数据。
