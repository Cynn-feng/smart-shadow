# SS-024：MetadataMutationGuardV1 与 provenance conflict replay

- 阶段：阶段 6（当前被阶段 1–5 阻塞）
- owner：待认领
- 状态：`blocked`
- 独占文件：获批前仅限 `configs/`、`artifacts/`、sidecar validator、离线 fixture 和本任务单；不得修改线上接口
- 目标：在一个经授权的私有 DAM/MAM 或内容发布链 shadow 中，回放导入/编辑/导出前后的原始字节、manifest/claim、C2PA/GB/IPTC 标识、provider/platform/content ID、工具版本、签名失效、删除/恢复和跨供应商冲突
- 固定 raw route：`pass`、`gap`、`conflict`、`insufficient`
- 前置：阶段 1–5 通过；原始字节可取得；法域/内容类型、删除/留存责任人、指定 reviewer、人工基线和重复任务明确
- 指标：字段完整率、签名/标识失效回放成功率、冲突复核分钟、删除/恢复回放、跨租户越权、P50/P95 和净价值
- 禁止：把有效签名写成内容真实/作者/版权，把缺标识写成人类创作，宣称 C2PA/GB 合规认证、客户、价格、收入或生产 SLA
- 验收命令：前置满足后再登记 validator/fixture 测试；当前只验收文档链接和阻塞条件
- 回滚：删除 sidecar validator、fixture、任务单和对应研究文档，不影响比赛版运行链
