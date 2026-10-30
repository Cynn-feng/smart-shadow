# SS-009：D-057 real-family-router-v1 分层增强

- 阶段：阶段 7（离线算法研究）
- 状态：ready，尚未编码
- 决策依据：D-041、D-053、D-055、D-056、D-057
- 任务入口：`docs/00-当前任务说明.md` → `docs/01-项目决策记录.md` → `docs/02-项目记忆.md` → `docs/03-技术方案.md` → `docs/04-实施方案.md`

## 目标

在已完成的 D-056 open-set routing 之上，复用 ONMA real-only profile 的输入和拒判边界，增加按
`generator_family × quality_bucket × transform_family × time_bucket` 分层的独立 family
profile set，验证生成器族假设是否能在开放集、时间切分和传播扰动下提供可复核的候选路由。

## 独占文件

首轮允许修改：

- `aigc/real_family_router.py`
- `tests/test_real_family_router.py`
- `eval/real_family_router_eval.py`
- `aigc/__init__.py`
- `scripts/verify_lightweight.sh`
- 本任务文件及对应的 `docs/02`、`docs/04`、`docs/07` 验证记录

不得修改：`aigc_result_v1`、`ai_server.py`、Go 网关、比赛页面、ONMA 既有 profile 数据和 D-050–D-055 sidecar。

## 最小输入和结果

输入必须绑定 asset/sample/version/manifest、feature schema、detector/schema、质量/传播/时间桶、ONMA profile/version/config，以及 family profile set、support manifest、calibration split 和 router config digest。

结果只允许包含 winner family、候选距离/energy、阈值、margin、support、profile/calibration digest、ONMA route 和 failure reason；固定路由为：

```text
family_candidate
family_ambiguous
real_consistent_unknown_family
out_of_manifold_unknown_generator
family_conflict_review
insufficient
```

禁止 probability、`human_supported`、`ai_generated_supported`、作者身份或法律结论字段。

## 首轮验收

至少覆盖唯一候选、family tie、低 margin、unknown family、real-consistent unknown family、profile/schema/detector mismatch、support/quality 不足、calibration/time split 泄漏、重复 profile digest、输入顺序确定性和禁止 probability/人类映射。runner 只能使用标量 fixture，不能伪造真实生成器准确率。

```text
git diff --check
python3 -m unittest tests.test_real_family_router -v
python3 -m eval.real_family_router_eval
bash scripts/verify_lightweight.sh
```

## 真实数据门和撤回

冻结同一 manifest 后必须比较 ONMA-only、GAPL-like prototype、LIDA-like retrieval 和完整 router，覆盖 leave-one-generator-out、same-family unseen、architecture/neural-rendering unseen、next-time-window、传播后 risk@coverage、unknown recall、family flip、P95、成本和人工复核分钟。只提升 closed-set Recall@1 或使开放集/时间/传播风险、成本、延迟或复核时间变差时，撤回为诊断 sidecar。

## 交付边界

首轮完成只能报告源码/单测/合成 fixture 层级；没有授权 manifest、独立 family calibration、真实传播和时间切分时，不得报告 AIGC 效果、生成器识别准确率、概率、部署或学术创新已成立。回滚为删除本任务新增模块、测试/runner、公共导出、验证脚本接入和文档条目。
