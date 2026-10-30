# SS-025：SAEA open-set propagation gate

- 阶段：阶段 7（安全修补）
- owner：待认领
- 状态：`done`（离线契约；真实开放集效果和线上接入未验证）
- 独占文件：`aigc/selection_aware_acquisition.py`、对应 `tests/`、`eval/` runner、公共导出和轻量验证接入；不得修改 `aigc_result_v1`、线上接口或比赛页面
- 目标：把 generator/open-set/replay 状态绑定到 SAEA 的候选就绪条件，防止未知生成器、来源/生成器冲突、profile 缺失或 retrieval replay 不一致时继续 probe 并升级为 candidate
- 依赖决策：D-073；先阅读 `docs/01-项目决策记录.md`、`docs/02-项目记忆.md`、`docs/03-技术方案.md` §19 和 `docs/04-实施方案.md` §7.36
- 允许输入：`generator_route`、`generator_profile_digest`、`generator_input_digest`、`generator_evidence_digest`、`retrieval_replay_route`、`retrieval_event_digest`、gate policy digest，以及现有 SAEA raw state
- 固定安全边界：`known_family_supported` 通过；`real_consistent` 仅中性；`open_set_unknown`、`conflict_review`、`insufficient`、`not_evaluated`、digest mismatch、poisoning/replay failure 固定拒判或复核；ordinary propagation 固定 `null_consistent`
- 最小测试：known family + replay pass；unknown→candidate attempt；缺 gate；profile/input/evidence/replay digest 不匹配；real-only neutral；replay open-set/poisoning；ordinary propagation；禁止字段；重复输入 digest 稳定
- 验收命令：

```text
git diff --check
python3 -m unittest tests.test_selection_aware_acquisition -v
bash scripts/verify_lightweight.sh
```

- 当前不能升级为：AIGC 检测效果、开放集泛化、作者/版权/法律结论、线上能力或部署证明
- 已验证层级：源码、12 项 gate 专测、10-case synthetic runner、全量 363 项测试/39 个 runner、语法、manifest、链接卫生和 `git diff --check`；不代表真实图片、开放集泛化、客户数据、线上部署或法律结论。
- 回滚：删除 gate、专测、runner、公共导出、验证接入、本任务单和对应文档条目，不影响既有 SAEA raw strategy、ALG-001 replay 或阶段 1–5 主线
