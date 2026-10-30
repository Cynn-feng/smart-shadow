# SS-033：CIVG-v1 counterfactual intervention validity gate

- 阶段：阶段 7（离线研究契约；不改变阶段 1–5 主线）
- owner：root
- 状态：done（offline contract；真实效果待 G0–G6）
- 决策：D-080
- 独占文件：`aigc/counterfactual_validity.py`、`tests/test_counterfactual_validity.py`、`eval/counterfactual_validity_eval.py`、`aigc/__init__.py`、`scripts/verify_lightweight.sh`、`docs/07-验证与运行记录.md`
- 前置关系：可与 SS-032 并行；真实效果评测依赖 G0–G6、真实 edit mask、独立 ordinary-null 和同预算 PC-SCFT 对照

## 目标

把 counterfactual 自身的有效性从 PC-SCFT 的下游假设提升为独立 raw data-quality gate，避免目标未生效、mask 外泄漏、非目标改变或语义/因果连带变化污染局部 AIGC 取证。

## 固定契约

输入绑定 reference/query/counterfactual、pair/null/mask/operator/execution/canonical frame、授权和质量；保存 target effect、非目标保持、mask leakage、semantic/causal consistency 和 minimum intervention raw scores。固定路由：`valid_intervention`、`spillover_review`、`counterfactual_invalid`、`insufficient`。

`valid_intervention` 只表示输入可供下游 raw evidence 使用，不表示 AIGC、作者、版权或法律结论。ordinary propagation、decoy、wrong-reference 不能成为有效 content intervention。

## 验收和撤回

```bash
python3 -m unittest tests.test_counterfactual_validity -v
python3 -m eval.counterfactual_validity_eval
bash scripts/verify_lightweight.sh
git diff --check
```

无授权真实数据时只报告 route、reason、support 和 digest，并写出 `real_data_status=not_evaluated`。如果真实对照中收益只来自更多拒判、coverage 降低、单一 operator 或 synthetic fixture，则撤回为输入质量审计 sidecar。

本轮验收已完成：15 项专测、14 个 scalar fixture、统一轻量验证通过；Python 3.14.7，398 个测试和 41 个合成/契约 runner。真实 edit mask、独立 ordinary-null、G0–G6、同预算 PC-SCFT 对照、客户数据和线上接入仍未验证。
