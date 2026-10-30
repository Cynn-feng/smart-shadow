# SS-030：2025–2026 论文前沿深度审计与可证伪白区

- 阶段：阶段 7（研究输入）
- owner：paper_frontier_audit
- 目标：在既有论文刷新基础上，核验 UniAIDet、AI-GenBench、OpenSDI、RRDataset、X-Edit、2026 开放 detector benchmark、RADAR、Detective SAM、IAR provenance、反取证与 C2PA/AI Act 边界；把已覆盖能力、最窄白区、必要对照、撤回门写成可审阅研究文件。
- 独占文件：`docs/research/2026-09-21-论文前沿深度审计与白区.md`、本任务单。
- 不修改：代码、`aigc_result_v1`、线上接口、主线阶段 1–5、既有算法任务单和商业文档。
- 状态：done（论文/标准/监管一手来源审计；AR-SCMI-v1 仅为待批准离线研究候选；真实图片、攻击样本、客户、部署和效果未验证）。
- 验收命令：`git diff --check`；Markdown/link hygiene；如纳入轻量验证，结果必须说明仅为文档检查。
- 回滚：删除本任务单和对应研究文件，不触碰既有代码、决策记录和验证记录。
