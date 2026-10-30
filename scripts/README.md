# `scripts/`：验证与研究辅助脚本

`verify_lightweight.sh` 是当前唯一的统一轻量验收入口。它运行 Python 单测、语法检查、manifest 校验、合成/契约 runner、文本/链接卫生检查和 `git diff --check`，不启动 Go、MySQL、IPFS、ChainMaker 或比赛版完整服务。

```bash
bash scripts/verify_lightweight.sh
```

脚本通过只能写成“源码、单测、合成 fixture 或契约层通过”，不能写成线上部署、真实 AIGC 准确率、真实 FPR、法律结论或商业 SLA。新增脚本应在这里说明依赖、输入、输出、可重复性和证据层级。

当前入口包含 ALG-001 `real_retrieval_event_eval`；最近一次统一回归为 342 个测试（含 30 个跳过项）和 37 个合成/契约 runner。真实 retrieval archive、授权图片和独立 null 仍未接入。
