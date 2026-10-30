# `aigc/`：离线证据契约与研究原语

这里存放不依赖重量模型的 evidence schema、来源绑定、区域反事实、传播 null、校准、拒判和审计原语。它们用于可回放的离线研究和契约测试，不等于比赛版服务已经接入，也不产生 AIGC 概率、作者身份或法律结论。

常用入口：

- `schema.py`、`provenance.py`：结果和来源证据契约；
- `image_adapter.py`、`real_image_runner.py`：有限格式图片解码和私有文件回放；
- `source_conditioned.py`、`pc_scft.py`：原件条件的区域反事实协议；
- `propagation_transforms.py`、`propagation_stability.py`：普通传播 hard negative/null；
- `evidence_grounded_explanation.py`、`operator_stability.py`：解释干预审计和质量门；
- `counterfactual_mask_persistence.py`：factual/ordinary-null/decoy/wrong-reference 的区域 mask 持续性和 null hallucination 审计；
- `counterfactual_validity.py`：在 PC-SCFT/SCTE 之前检查 counterfactual 的目标生效、非目标保持、mask 外泄漏、语义/因果一致和最小干预；`valid_intervention` 只表示输入可进入下游 raw evidence；
- `retrieval_event_replay.py`：从冻结 retrieval archive/index snapshot 重放候选、membership、传播树和 selection trace；只输出 route/raw sidecar，并对权限、删除、隐私和原始资产回显 fail-closed；
- `manifest.py`：数据授权、分组和 split 泄漏校验。

从仓库根目录运行：

```bash
python3 -m aigc.manifest eval/manifest.example.jsonl
python3 -m unittest discover -s tests -v
python3 -m eval.real_retrieval_event_eval
bash scripts/verify_lightweight.sh
```

没有真实授权图片、冻结 manifest、独立 ordinary-propagation null 和时间/生成器切分时，新增模块只能作为 raw contract；不要把 synthetic digest、p-value、ROI 或路由名称写成真实准确率或部署能力。

ALG-001 当前为 `offline contract implemented`：专测 12 项通过，合成 runner 覆盖 9 个回放案例；`real_data_status=not_evaluated`。真实 archive/index、授权图片、独立 null、FPR、coverage、客户数据和线上接入仍待 G0–G6，不得把 `candidate` 或 `null_consistent` 路由写成 AIGC 概率、来源证明或法律结论。
