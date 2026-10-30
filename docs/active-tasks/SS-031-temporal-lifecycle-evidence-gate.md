# SS-031：TLEG-v1 时序/生命周期证据门

## 任务信息

- 阶段：阶段 7（离线研究契约），同时服务阶段 1–5 的可靠性前置门
- 决策：D-077
- owner：algorithm_innovation_design
- 状态：done（无重量离线契约；真实生命周期数据待授权，未接线上）
- 独占文件：`aigc/temporal_lifecycle_gate.py`、`tests/test_temporal_lifecycle_gate.py`、`eval/temporal_lifecycle_gate_eval.py`；允许追加 `aigc/__init__.py`、`scripts/verify_lightweight.sh`
- 协作边界：核心文档由主 agent 更新；不得修改 `aigc_result_v1`、比赛版服务、Go 网关或客户数据

## 目标

在任何候选路由前验证 query-as-of、snapshot freshness、事件序列、删除墓碑、恢复新版本、授权/留存/访问 digest 和租户边界。TLEG 只允许或阻止下游证据继续，不检测 AIGC、不输出概率、不认定作者或法律责任。

## 固定契约

raw route 固定为：

`lifecycle_consistent`、`future_event_leak`、`stale_snapshot_review`、`tombstoned_insufficient`、`deletion_replay_mismatch`、`profile_stale`、`insufficient`、`not_evaluated`。

输入必须绑定 `event_id`、资产/版本/父版本、`query_as_of`、`snapshot_created_at`、index epoch、有效时间区间、单调序号和前一事件 digest，以及删除、留存、授权、访问、split、time window 和上游 replay/evidence digest。输入顺序改变或任一绑定不一致时不得静默继续。

## 最小验收

- 同一输入重复回放的结果和 digest 稳定；输入顺序变化不改变规范化结果。
- future snapshot/profile、序列重排/重复/断链、删除后仍可见、恢复但没有新版本、授权过期、retention/access digest 不一致、跨租户和同资产跨 split 均 fail closed。
- ordinary propagation、unknown/open-set、source conflict 不能被 TLEG 修复成 candidate；TLEG 的 `lifecycle_consistent` 只表示时序门通过。
- 至少 12 个 synthetic cases；runner 只报告 route、digest 和 raw 支持量。

## 验收结果

- `python3 -m unittest tests.test_temporal_lifecycle_gate -v`：20 项通过。
- `python3 -m eval.temporal_lifecycle_gate_eval`：18 个 synthetic case；route counts 和 dataset/config digest 已写入 `docs/07-验证与运行记录.md`。
- `bash scripts/verify_lightweight.sh`：通过，383 个测试、40 个合成/契约 runner、语法、manifest、Markdown/link hygiene 和 `git diff --check` 通过。
- `import aigc`：TLEG version/schema 公共导出可用。

## 验收命令

```text
python3 -m unittest tests.test_temporal_lifecycle_gate -v
python3 -m eval.temporal_lifecycle_gate_eval
bash scripts/verify_lightweight.sh
git diff --check
```

## 真实数据门与回滚

真实 manifest 必须包含合法事件时间、过去和未来窗口、删除责任/墓碑、恢复演练和授权访问记录；在此之前只能称为 fixture contract，不能宣称 temporal generalization、AIGC 效果或部署能力。回滚为删除本模块、专测、runner、公共导出、脚本接入、本任务单和 D-077 的实施记录，不触碰既有研究切片。
