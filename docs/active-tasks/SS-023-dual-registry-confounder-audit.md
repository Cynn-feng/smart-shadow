# SS-023：DRCS-v1 双注册表混淆分离

- 阶段：阶段 7（离线研究）
- owner：待认领
- 状态：`deferred`
- 独占文件：未来若批准，仅限 `aigc/`、`eval/`、`tests/`、本任务单和对应研究记录
- 前置：SS-019/ALG-001 真实 retrieval archive/index 回放；G0–G6；独立 ordinary-propagation null；授权局部编辑 mask；生成器/时间外部切分
- 目标：把登记原件/版本/传播 null 的 `asset_registry` 与生成器/real-only/open-set/水印/C2PA 的 `generator_registry` 分离，审计来源证据和生成器伪影的混淆
- 固定 raw route：`source_specific_edit_candidate`、`generator_only_unknown`、`ordinary_propagation_consistent`、`source_generator_conflict_review`、`insufficient`
- 强制对照：query-only、asset-only、generator-only、双 registry、去 ordinary-null、去 decoy、wrong-reference 和 provenance×watermark conflict
- 强制指标：ordinary-propagation FPR、reference false-match、risk@coverage、unknown/review、ROI/边界 F、route flip、P50/P95、每千件成本、人工复核分钟
- 禁止：新 detector 宣称、生成器 top-1 当作来源证明、AIGC probability、作者/版权/侵权字段、接入 `aigc_result_v1`、线上服务或客户数据
- 验收命令：获批后另行登记专测、runner、冻结 manifest digest 和回放日志；当前仅验收文档链接和任务边界
- 回滚：删除 DRCS 代码、测试、runner、导出、任务单和对应研究记录，不影响 ALG-001/RSCPTN
