# SS-013：SAEC-v1 选择后分层证据校准

- 阶段：阶段 7（离线算法研究）
- 决策依据：D-054、D-058、D-060
- 状态：done；无模型契约已实现，真实数据未授权
- owner：root
- 独占文件：`aigc/selection_aware_calibration.py`、`tests/test_selection_aware_calibration.py`、`eval/selection_aware_calibration_eval.py`

## 目标

把“从多个参考中选择 winner 后再评价”这一统计选择过程显式纳入 ordinary-propagation calibration，控制错误原件和最大差异 winner's curse。SAEC 只消费 D-054/D-058 已绑定的 scalar raw evidence，不重新运行 detector、图像操作或检索。

## 契约边界

- 三类 split digest 必须两两不同；query group 不得出现在 calibration group。
- calibration group 使用同一 selection policy、固定 decoy 数、profile level、null profile、schema、operator set 和质量/传播桶。
- 选择后 p-value 使用 `(1 + count(max_statistic >= candidate_contrast)) / (1 + group_count)`，只表示 raw calibration evidence。
- 路由固定为 `selection_specific_candidate`、`selection_ambiguous`、`null_consistent`、`insufficient`。
- 结果不得包含 `probability`、`confidence`、作者、版权或法律字段。

## 验收和回滚

至少 10 类专测、6 个 scalar runner case、公共导出和轻量验证通过；真实授权 manifest、独立 calibration groups、blind decoy、D-058 stability、FPR/coverage-risk 和人工收益仍未验证。回滚删除本模块、测试、runner、公共导出和验证脚本接入，不修改 D-054/D-058 或线上服务。
