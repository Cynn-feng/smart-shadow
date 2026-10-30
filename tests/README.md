# `tests/`：轻量契约测试

测试覆盖 `aigc/` 的 schema、输入边界、来源绑定、拒判、确定性 digest、传播 null、校准和离线审计。默认不加载 CLIP、PyTorch、Faiss、ChainMaker、MySQL 或真实图片数据。

统一入口：

```bash
python3 -m unittest discover -s tests -v
bash scripts/verify_lightweight.sh
```

测试通过只代表当前源码和 fixture 契约通过。真实图片效果、Go/链上服务、部署和商业试点必须在 `docs/07-验证与运行记录.md` 中有独立命令和证据后才能对外描述。

当前统一回归为 342 个测试（含 30 个跳过项）；其中 `tests/test_retrieval_event_replay.py` 的 ALG-001 专测为 12 项。测试数量不是模型效果或部署状态的证明。
