# SS-022：PE-CEA-v1 传播严重度包络审计

状态：done（owner：`/root/pe_cea_impl`；无重量离线契约；真实数据待 G0–G6）
阶段：阶段 7，离线研究
决策：D-070
目标：验证同一 source/query/counterfactual 配对的局部效应，是否在多个传播严重度等级上持续超出同层 ordinary-propagation null。

## 独占文件

- `aigc/propagation_envelope.py`
- `tests/test_propagation_envelope.py`
- `eval/propagation_envelope_eval.py`
- `aigc/__init__.py`
- `scripts/verify_lightweight.sh`
- `docs/07-验证与运行记录.md`（只有真实执行后才能更新）

## 契约边界

- 只实现无重量模型的 schema、profile、severity-level envelope、curve-level raw statistics 和 fail-closed route。
- ordinary-propagation profile 只能使用独立 asset groups；内容编辑查询必须有 `edit_mask_digest`，普通传播不得携带编辑标签。
- 固定路由：`envelope_candidate`、`null_consistent`、`curve_inconsistent`、`insufficient`。
- 结果不包含 probability、作者、版权、侵权、`human_supported` 或 `ai_generated_supported`。
- 不修改 `aigc_result_v1`，不接 `ai_server.py`、Go 网关、比赛页面或客户数据。

## 最小验收

覆盖 profile 层级支持、候选曲线、普通传播隔离、孤立尖峰/不连续曲线、缺 severity、mask 缺失、split 泄漏、binding/schema 冲突、输入顺序确定性和字段卫生。执行：

```bash
python3 -m unittest tests.test_propagation_envelope -v
python3 -m eval.propagation_envelope_eval
bash scripts/verify_lightweight.sh
git diff --check
```

## 真实评测门

冻结授权 manifest、同传播族 severity path、编辑 mask、独立 ordinary null、wrong-reference/decoy、已知/未见生成器、下一时间窗和传播红队。与 query-only、paired delta、propagation-stability、SCPTN/RSCPTN、去 envelope 做相同 coverage/action budget 对照，报告 ordinary-propagation FPR、reference false-match、risk@coverage、ROI/边界 F、曲线保持率、route flip、P50/P95、成本和人工复核分钟。

## 回滚

删除模块、测试、runner、公共导出、脚本接入、本任务单和 D-070/03/04 对应段落；保留现有 paired-delta、propagation-stability、SCPTN/RSCPTN 契约。

## 完成记录（2026-09-21）

- 已完成 `aigc/propagation_envelope.py`、9 项专测、`eval/propagation_envelope_eval.py`、公共导出和 `scripts/verify_lightweight.sh` 接入。
- `python3 -m unittest tests.test_propagation_envelope -v`：9 项通过。
- `python3 -m eval.propagation_envelope_eval`：6 个 synthetic case；`route_counts={curve_inconsistent:1,envelope_candidate:1,insufficient:2,null_consistent:2}`；`dataset_digest=a383cde8aed660d8a9287320c461231dc6a61a19026ae93692be82d1f1bb4d36`；`profile_digest=254fc908ff8f8063b8879646c52d6a0d7210ff5304b7b4d8cc97176a252a3ec9`。
- `bash scripts/verify_lightweight.sh`：351 项测试、38 个 runner、语法、manifest、Markdown/link hygiene 和 `git diff --check` 通过。
- 真实 retrieval archive、授权图片、独立 ordinary null、外部切分、G0–G6、线上服务和客户数据仍未验证；本任务结果只能称为 raw-evidence contract。
