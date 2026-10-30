# Smart Shadow AIGC 算法创新调研

版本：V0.4 研究方案
更新时间：2026-09-21
状态：研究结论和实验计划；尚未证明新方法的效果或学术新颖性

命名约定：`PARFD` 是来源感知开放集取证的研究总体系；`PC-SCFT` 是其中针对“登记原件 + 同传播族无编辑反事实”的区域配对协议。两者都是研究假设，`aigc/` 当前实现的是离线 raw-evidence 原语，不是线上 detector。`SCTE`（Source-Conditioned Triadic Evidence）是 PC-SCFT 的三元证据研究分解，`ONMA`（Open-World Natural-Manifold + On-Manifold Adaptation）是无原件 fallback，`BMEA`（Budgeted Multi-View Evidence Acquisition）是 A9 的主动取证路线；三者不是新 API 或四态结果名，正式接口和阶段门仍以 `docs/01-项目决策记录.md`、`docs/03-技术方案.md` 和 `docs/04-实施方案.md` 为准。`evidence_budget.py` 已实现为 A9 的离线 planner；`sequential_evidence.py`、`policy_calibration.py` 和 `eval/sequential_evidence_eval.py` 已实现固定策略、可回放状态机和合成策略级 FPR/CI 契约，但真实授权回放、risk-coverage-cost 和部署仍未验证；`model_adapter.py`、`real_image_runner.py`、`real_manifold_profile.py`、`scte.py` 及对应 eval runner 已实现第一版合成/契约切片，但只证明私有授权、哈希、解码、配对、版本化 profile、三元绑定和无独立 null 时的 fail-closed 行为；`generator_attribution.py`、`re_edit_probe.py` 仍是 planned。以仓库实际文件和 `docs/04-实施方案.md` 为准。

## 0. 状态矩阵：事实、计划与禁止外推

| 层级 | 当前状态 | 可写入的结论 | 不能写入的结论 |
| --- | --- | --- | --- |
| 已实现 raw 原语 | `schema`、来源/合规、`source-residual`、图片 adapter、区域配准、PC-SCFT、G1 传播变换、A9 planner | 契约、确定性、拒判原因和合成 fixture 回归可复现 | 真实 AIGC 准确率、概率、法律证据或部署能力 |
| 研究协议 | A0–A8 消融、开放集、时间切分、传播和 ROI 指标 | 可指导 manifest、对照和发布门 | 不代表对应模型已接入仓库 |
| 已实现但仅限契约 | `model_adapter.py`、`real_image_runner.py`、`pc_scft_real_image_eval.py`；SRM/DCT/CLIP/重建/归因仍 planned | 可复现私有 runner、输入/配对审计和 `calibration_unavailable → insufficient` | 不得引用为真实图片效果、AIGC 概率或线上功能 |
| 真实验证 | 授权图片、真实传播、跨生成器、外部审计 | 只有记录到 `docs/07-验证与运行记录.md` 后才能升级状态 | 合成 digest、论文数字和采购预算不能替代 |

新增代码每次都要同步这张表、`docs/02-项目记忆.md` 和 `docs/04-实施方案.md`；实现了接口草图也必须把“契约已实现”和“真实效果未验证”分开，不要制造“已接入”印象。

### 0.1 研究路线与现行项目文档的映射

| 研究路线 | 在本项目中的准确含义 | 现行技术/实施入口 | 当前状态和接口边界 |
| --- | --- | --- | --- |
| `PARFD` | 来源感知开放集取证的总体系 | `01-项目决策记录.md` D-028；`03-技术方案.md` §11 | 规范研究总名，不是线上服务名 |
| `PC-SCFT` | 有登记原件时，observed 与同传播族无编辑 counterfactual 的区域配对协议 | `03-技术方案.md` §11.7–§11.12、§11.21；`04-实施方案.md` 阶段 7 | 已有离线 raw/契约切片；不改变 `aigc_result_v1` 四态 |
| `SCTE` | 对 PC-SCFT 的三元证据分解：reference、query 和 ordinary-propagation counterfactual 的差异检验 | `03-技术方案.md` §11.7–§11.10、§11.21；`04-实施方案.md` 阶段 7 | 研究假设；不新增 `/check` 字段，不替代 PC-SCFT 正式命名 |
| `ONMA` | 无登记原件时的 natural-manifold/real-only 保守回退，以及有 latent 访问权时的 on-manifold hard negative 和版本化适配 | `03-技术方案.md` §11.1、§11.15；`04-实施方案.md` 阶段 7 后续步骤 | `real_manifold_profile.py` 已有离线合成/契约切片；真实授权特征、独立校准和适配仍待验证；不能由高置信 real-only 结果生成 `human_supported` |
| `BMEA` | A9 的限预算多视角证据获取和完整策略回放 | `03-技术方案.md` §11.4.1、§11.20；`04-实施方案.md` §7.4、阶段 7 | planner/state machine 契约已存在，真实 probe、策略 FPR 和线上接入未验证 |
| `reference-specificity-v1` | 候选登记原件与同 query 的 blind decoy references 做 matched specificity gate，控制错误原件选择造成的局部差异误报 | `01-项目决策记录.md` D-054；`03-技术方案.md` §11.33；`04-实施方案.md` §7.22 | 离线 raw contract 已实现；有限样本 p-value、参考库/decoy 独立性、真实 false-match rate 和效果仍待验证；不改变四态接口 |

### 0.2 2026-09-20 一手论文和标准刷新

本轮只记录能改变 Smart Shadow 实验设计的官方论文/标准页面，论文指标不能直接外推到本项目：

| 来源 | 新信息 | 对本项目的直接动作 | 不能外推 |
| --- | --- | --- | --- |
| [AIGIBench，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/fb693c67f61e5321746ffce8b6fdd2d0-Abstract-Datasets_and_Benchmarks_Track.html) | 以多源泛化、退化鲁棒、增广敏感性和测试时预处理评估检测器，并报告受控数据到真实数据的明显跌落。 | 将传播链、预处理和外部来源作为独立切分；所有结果同时报告 known/unseen/real-world。 | 不提供 Smart Shadow 的真实准确率或开放集保证。 |
| [ForensicHub，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/5d8a47fc1cb0a143f149ee07321621c9-Abstract-Datasets_and_Benchmarks_Track.html) | 用配置驱动、可替换 adapter 组织数据、变换、模型和评测，并统一多任务取证。 | 继续维护 manifest、adapter、detector、evaluator 的独立 digest；A0–A10 必须可重放。 | 模块化框架不等于 Smart Shadow 已有模型或效果。 |
| [Phase Spectrum Robustness，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Li_Detecting_Compressed_AI-Generated_Images_via_Phase_Spectrum_Robustness_CVPR_2026_paper.html) | 针对社交平台压缩提出 phase-spectrum 稳健支路，强调压缩会破坏脆弱伪影并制造干扰。 | 保留 spectral/phase 作为独立流，加入多轮 JPEG、resize、截图和复合传播对照；不得直接与 pixel 流平均。 | 压缩鲁棒不等于未知生成器、局部编辑或来源证明。 |
| [SAFE Image Authenticity Challenge，WACV 2026 Workshop](https://openaccess.thecvf.com/content/WACV2026W/SynRDinBAS/html/Nguyen_The_SAFE_Image_Authenticity_Challenge_Detecting_and_Localizing_Partial_and_WACVW_2026_paper.html) | 将整图生成、局部 AI 编辑和传统篡改放进检测、分类、定位的统一评测。 | A0–A8 同时保留 image-level route、edit type、ROI 和 unknown/review，不再只报二分类 AUROC。 | 挑战赛结果不能转成产品 SLA。 |
| [Locate-Then-Examine，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/papers/Ji_Locate-Then-Examine_Grounded_Region_Reasoning_Improves_Detection_of_AI-Generated_Images_CVPR_2026_paper.pdf) | 先定位可疑区域，再对 crop 与全图复核，强调区域证据对解释和泛化的作用。 | 可把它作为高成本外部 baseline；Smart Shadow 的差异仍需依赖登记原件、matched null 和拒判，而不是自由文本解释。 | LTE/TRACE 的区域定位不能证明来源、作者或版权。 |
| [AI-generated Image Detection: Passive or Watermark?，CVPR 2026 Workshop](https://openaccess.thecvf.com/content/CVPR2026W/SAFE/html/Guo_AI-generated_Image_Detection_Passive_or_Watermark_CVPRW_2026_paper.html) | 在多类扰动下比较被动 detector 与 watermark，指出可用水印时其鲁棒性可能优于被动检测。 | 产品侧把 C2PA/水印、第三方 detector 和 PC-SCFT 分成独立 evidence adapter；来源冲突进入 review。 | 水印缺失不能证明人类创作，水印覆盖也不能替代开放集评测。 |
| [C2PA 2.4 技术规范](https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html) | 新增 `c2pa.ai-disclosure`、`c2pa.repository-receipt` 和 crJSON 派生视图，并要求保留 manifest/签名/验证语义。 | Evidence sidecar 增加标准版本、AI disclosure 原始值、repository receipt 和验证错误；crJSON 只作为导出视图。 | C2PA 是可验证的来源绑定，不是对内容价值、真实性或版权的自动判断。 |

本轮收敛出的算法方向是：**不要再寻找单一万能 AIGC 分类器，而是把“来源条件局部证据、普通传播 null、独立低层流、开放集拒判和可回放复核”组织成可证伪协议。** 如果去掉登记原件或 matched null 后效果仍不下降，必须撤回 source-conditioned 创新主张。

三条路线都受 `01-项目决策记录.md` D-040 的双轨准入约束：阶段 7 可以离线推进，阶段 6 线上产品扩展必须等待阶段 1–5。它们只描述研究分解和实验顺序，不能被 agent 当作新的产品能力、状态枚举或服务接口。

**快速阅读**：只想接手下一切片时，先看本节状态矩阵、§1 的问题边界、§6 的代码计划、§10.12 的最小创新主张和 §11.11 的 G1 配对审计；完整论文表和外部对照按具体任务再查。

## 1. 研究问题和结论

当前项目不能用一个二分类器“解决 AIGC”。生成器持续变化，图片会被裁剪、压缩、截图、再拍摄和局部重绘，元数据也可能被删除或伪造。更适合 Smart Shadow 的问题定义是：

> 在版权存证场景中，能否把来源凭证、局部语义指纹、低层取证、重建误差和生成器归因组合成可审计的证据链，并在未知生成器和传播扰动下主动拒判？

因此，算法目标改为四态分流：

| 状态 | 含义 | 可否作为法律结论 |
| --- | --- | --- |
| `human_supported` | 当前证据支持未发现 AI 信号 | 不可作为“证明人类创作” |
| `ai_generated_supported` | 来源凭证或多路模型证据支持整图生成 | 不可作为单独的侵权/权属结论 |
| `ai_edited_supported` | 局部区域存在 AI 编辑证据 | 需要人工查看区域和编辑链 |
| `unknown_or_inconclusive` | 证据缺失、冲突、置信度不足或模型失败 | 必须人工复核 |

没有 C2PA、可信水印或元数据，不能推导出“人类创作”；模型异常、原始分数未校准或阴性证据不足也不能默认 `human_supported`。当前实现只有在签名的非 AI 来源声明、匹配校准 profile 和至少两路阴性模型流同时满足时才允许该状态。

## 2. 当前代码基线和缺口

源码事实如下：

- `super_algo.py` 使用全图、四象限和中心六个区域的 CLIP 向量，拼接长度为 3072；这是版权语义检索基线，不是 AIGC 取证器。
- `ai_server.py` 将六组向量分片写入 `faiss.IndexFlatIP(512)`，查询后取区域命中的高分；当前没有作品级有向分数和完整的 CID 聚合。
- YOLO 只提供主体标签，不参与相似度或 AIGC 判定。
- 当前 AIGC 字段不能证明模型有效性；没有固定数据集、生成器时间切分、阈值校准或未知生成器评测。

因此，现阶段只能把六区域 CLIP 叫作“区域语义指纹基线”，不能继续使用“精准抗裁剪”“AI/人类确定性判定”等表述。

## 3. 相关研究及对本项目的启示

| 工作 | 已解决的问题 | 对 Smart Shadow 的采用方式 | 需要保留的限制 |
| --- | --- | --- | --- |
| [GenImage, NeurIPS 2023](https://arxiv.org/abs/2306.08571) | 百万级真实/生成图、多生成器和退化基准 | 训练与跨生成器基线 | 不能当作真实平台准确率 |
| [DIRE, ICCV 2023](https://openaccess.thecvf.com/content/ICCV2023/html/Wang_DIRE_for_Diffusion-Generated_Image_Detection_ICCV2023_paper.html) | 用扩散重建误差提升未见生成器泛化 | 低置信样本的离线二阶段复核 | 反演成本高，依赖预训练模型族 |
| [AEROBLADE, CVPR 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Ricker_AEROBLADE_Training-Free_Detection_of_Latent_Diffusion_Images_Using_Autoencoder_Reconstruction_CVPR2024_paper.html) | 训练免依赖的自编码器重建检测 | 研究版轻量重建支路 | 对模型族和后处理仍有边界 |
| [LaRE², CVPR 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Luo_LaRE2_Latent_Reconstruction_Error_Based_Method_for_Diffusion-Generated_Image_Detection_CVPR2024_paper.html) | latent 重建误差和误差引导特征 | 与现有区域切片对齐的可选支路 | 不默认在线同步执行 |
| [FakeInversion, CVPR 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Cazenavette_FakeInversion_Learning_to_Detect_Images_from_Unseen_Text-to-Image_Models_by_CVPR2024_paper.html) | 通过 Stable Diffusion inversion 适配未见模型 | 作为高成本研究基线 | 推理慢，不能替代来源凭证 |
| [CLIP detector, CVPRW 2024](https://openaccess.thecvf.com/content/CVPR2024W/WMF/html/Cozzolino_Raising_the_Bar_of_AI-generated_Image_Detection_with_CLIP_CVPRW_2024_paper.html) | 轻量 CLIP 头和 OOD/压缩鲁棒性 | 作为最小 AIGC 视觉基线 | 仍是被动检测，不能验证来源 |
| [AIDE, ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/hash/b0303773962ea1b5394c3a83cc7dd066-Abstract-Conference.html) | CLIP 语义 + DCT 高频/低频 patch + SRM 噪声 | 第一版最适合复现的三路模型 | 论文同时说明高质量 AIGC 仍会欺骗检测器 |
| [RRBench/RRDataset, ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Li_Bridging_the_Gap_Between_Ideal_and_Real-world_Evaluation_Benchmarking_AI-Generated_ICCV2025_paper.html) | 社交传播、多轮传输、再数字化的真实扰动 | 设计截图、重编码和再拍摄测试 | 数据覆盖范围有限，需补充项目授权集 |
| [Semi-Truths, NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/d5cdf7e56422f2a229c497dd89c3b995-Abstract-Datasets_and_Benchmarks_Track.html) | 大规模局部 AI 增强图和扰动元数据 | 训练和评测局部编辑分支 | 局部编辑标签需与项目场景对齐 |
| [ASL copy detection, AAAI 2023](https://ojs.aaai.org/index.php/AAAI/article/view/25366) | 编辑复制具有方向性和 hard negatives | 把版权分数改成 query→reference 有向匹配 | 需要编辑变换标注和 CID 聚合 |
| [PixTrace, ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Lu_Tracing_Copied_Pixels_and_Regularizing_Patch_Affinity_in_Copy_Detection_ICCV2025_paper.html) | 追踪复制像素与 patch 对应关系 | 研究局部热图和可解释匹配 | 需要可追踪的合成编辑数据 |
| [Stable Signature, ICCV 2023](https://openaccess.thecvf.com/content/ICCV2023/html/Fernandez_The_Stable_Signature_Rooting_Watermarks_in_Latent_Diffusion_Models_ICCV2023_paper.html) | 生成器主动嵌入可检测签名 | 作为合作生成平台的主动来源信号 | 未加签名的图片无法反推人类 |
| [A Sanity Check/AIDE, ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/hash/b0303773962ea1b5394c3a83cc7dd066-Abstract-Conference.html) | Chameleon 难集和 CLIP + 高频/低频 patch + SRM | 作为单图被动检测基线和失败样本来源 | 论文明确指出问题远未解决，不能当作通用鉴定 |
| [B-Free, CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Guillaro_A_Bias-Free_Training_Paradigm_for_More_General_AI-generated_Image_Detection_CVPR_2025_paper.html) | 用语义对齐的真实/生成配对和内容增广减少内容、格式捷径 | 构造同源、同内容的训练对和 hard negatives | 仍然是合成训练，不能代表野外/法律准确率 |
| [Community Forensics, CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Park_Community_Forensics_Using_Thousands_of_Generators_to_Train_Fake_Image_CVPR_2025_paper.html) | 4,803 个生成器、270 万张图，研究生成器多样性 | 扩大训练生成器覆盖，按生成器时间/家族切分 | 更大的训练集不能消除未知生成器和传播扰动风险 |
| [AIGIBench, NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/fb693c67f61e5321746ffce8b6fdd2d0-Abstract-Datasets_and_Benchmarks_Track.html) | 多源泛化、退化鲁棒性、增广敏感性和野外图综合评测 | 作为 external/online/augmentation 的协议参考 | 仍需加入 Smart Shadow 授权图库和局部编辑标签 |
| [AI-GenBench, 2025](https://arxiv.org/abs/2504.20865) | 按生成器发布时间做时间序列增量评测 | 把“下一代生成器”作为主测试门，而非随机切分 | 当前版本仍需补充局部编辑和中国平台传播链 |
| [PixTrace, ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Lu_Tracing_Copied_Pixels_and_Regularizing_Patch_Affinity_in_Copy_Detection_ICCV2025_paper.html) | 显式像素坐标追踪和 patch 亲和约束 | 训练 source-conditioned 局部对应和 ROI 热图 | 需要可追踪的编辑变换与真实 hard negatives |
| [DICE, ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Baraldi_What_Changed_Detecting_and_Evaluating_Instruction-Guided_Image_Edits_with_Multimodal_ICCV2025_paper.html) | 检测局部变化并评估变化是否符合编辑指令 | 借鉴“变化区域 + 变化一致性”的双头输出 | 需要编辑指令或可靠的编辑标签，不能直接当来源证据 |
| [DiffSeg30k, 2025](https://arxiv.org/abs/2511.19111) | 30k 多轮扩散局部编辑、像素级标注和八类模型 | 用于局部 AI 编辑检测、分割和多轮扰动测试 | 公开数据分布不能替代项目授权图库 |
| [SIDA, CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Huang_SIDA_Social_Media_Image_Deepfake_Detection_Localization_and_Explanation_with_CVPR_2025_paper.html) | 社媒图检测、篡改定位和解释联合输出 | 参考 ROI + 解释的工作台展示 | 文本解释必须单独测 faithfulness，不能当证明 |
| [SAFE Challenge, WACV 2026](https://openaccess.thecvf.com/content/WACV2026W/SynRDinBAS/html/Nguyen_The_SAFE_Image_Authenticity_Challenge_Detecting_and_Localizing_Partial_and_Fully_Synthetic_Manipulations_WACVW_2026_paper.html) | 同时覆盖完整生成、局部 AI 编辑和传统篡改的检测/定位 | 采用多任务评测：类型、是否篡改、区域定位 | 挑战集指标不能直接转成商业 SLA |
| [Generator-Aware Prototypes, CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/papers/Qin_Scaling_Up_AI-Generated_Image_Detection_with_Generator-Aware_Prototypes_CVPR_2026_paper.pdf) | 用生成器感知 prototype 缩小多生成器空间，指出冻结编码器瓶颈 | 作为开放集归因和 prototype/OOD 支路的基线 | 生成器归因不能替代 AI/人类结论 |
| [PPM-CLIP, CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Wang_PPM-CLIP_Probabilistic_Prompt_Modeling_for_Generalizable_AI-Generated_Image_Detection_CVPR_2026_paper.html) | 用输入自适应的概率提示代替固定判别边界 | 作为未来单图检测器的对照，不进入第一代码切片 | 仍需在真实传播和局部编辑上独立验证 |
| [MIRAGE, AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/37421) | 人工核验野外 AIGI 与多生成器数据，加入推理时自适应 | 作为慢速审计路径和人工复核排序参考 | VLM 成本高，数据筛选和来源必须审计 |
| [OCC-CLIP, ECCV 2024](https://www.ecva.net/papers/eccv_2024/papers_ECCV/html/7930_ECCV_2024_paper.php) | 把生成器来源归因做成 few-shot one-class 验证 | `generator_hypotheses` 使用 prototype/one-class + reject | 闭集或少样本结果不能当未知生成器事实 |
| [Authenticated Contradictions, CVPRW 2026](https://openaccess.thecvf.com/content/CVPR2026W/APAI/papers/Nemecek_Authenticated_Contradictions_from_Desynchronized_Provenance_and_Watermarking_CVPRW_2026_paper.pdf) | 研究 C2PA 与水印发生冲突时的跨层审计 | 建立 `provenance × watermark × visual` 冲突矩阵 | 冲突检测仍需要可信 verifier 和人工复核 |
| [ForensicHub, NeurIPS 2025](https://papers.neurips.cc/paper_files/paper/2025/file/5d8a47fc1cb0a143f149ee07321621c9-Paper-Datasets_and_Benchmarks_Track.pdf) | 统一多任务、多数据集和 adapter 评测 | 固定预处理、adapter 和 cross-domain 表 | 论文分数不可直接当线上 SLA |
| [OpenAI provenance verification](https://openai.com/index/advancing-content-provenance/) | C2PA + SynthID 多层信号；无信号时不排除生成来源 | 作为 `no_signal_or_unknown` 和“供应商范围”设计的现实案例 | 只能验证支持的 OpenAI 来源，不是通用 AIGC 检测 |
| [NTIRE 2026 Robust AIGC Detection](https://arxiv.org/abs/2604.11487) | 42 个生成器、36 类图像变换的野外鲁棒性挑战 | 作为传播扰动和大规模外部测试参考 | 挑战数据和排行榜不能替代客户授权数据 |
| [Open-source detector benchmark, 2026](https://arxiv.org/abs/2602.07814) | 不同数据集上的检测器排名不稳定，现代商业生成器上性能明显下降 | 作为“不承诺通用准确率”的最新反证 | 预印本结果需要独立复现，不能直接写成定论 |

研究共识是：跨生成器和真实传播条件下不存在可靠的单一通用检测器。Smart Shadow 的贡献机会应放在“来源凭证 + 取证模型 + 局部版权匹配 + 拒判”的工程化联合协议，而不是声称重新发明一个基础模型。

### 3.1 这批新论文对 Smart Shadow 的共同约束

1. **生成器多样性比样本数量更关键**：Community Forensics 显示训练生成器的数量和多样性影响未见生成器泛化；因此项目必须保留 `generator_family`、发布时间和时间切分，不能只随机划分图片。
2. **真实传播会改变任务**：AI-GenBench 把生成器时间顺序作为评测轴，RRDataset/SAFE/DiffSeg30k 又把传播、局部编辑和定位纳入任务。项目的主指标必须按生成器、传播链和编辑类型分层报告。
3. **局部编辑不能被整图标签掩盖**：PixTrace、DICE 和 DiffSeg30k 都把区域对应、差异一致性或像素级标注放在核心位置，这与 Smart Shadow 已有登记原件和六区域检索天然相容。
4. **固定的 CLIP 空间存在瓶颈**：CVPR 2026 的生成器感知 prototype 工作提示，单纯冻结预训练编码器难以覆盖大规模新生成器。Smart Shadow 应把 CLIP 作为检索/对齐基线，取证头和开放集头独立校准，后续再验证是否需要端到端微调。

5. **“检测”与“合规标签”是两层任务**：中国标识办法和 C2PA 都允许“已验证来源、用户声明、疑似痕迹、无信号”并存。模型输出四态用于取证，传播/合规适配器另输出 `verified_ai`、`user_declared_ai`、`suspected_ai`、`no_signal_or_unknown`，不能把 `no_signal` 翻译成 `human`。

6. **模型本身也要作为证据链管理**：近期工作指出训练数据、checkpoint 和第三方数据可能引入偏差甚至后门。Smart Shadow 至少要保存模型权重 digest、训练/校准 manifest digest、依赖版本和签名评测结果，并为新模型做 trigger/red-team 检查；否则“模型分数”无法审计。

### 3.2 2026 年一手论文刷新：应新增的对照与可迁移结论

这轮刷新只纳入会议官方页面或论文全文，新增结果仍是外部研究证据，不能当作 Smart Shadow 已取得的效果。

| 工作 | 论文给出的技术方向 | Smart Shadow 的具体动作 | 不能直接推出的结论 |
| --- | --- | --- | --- |
| [Diversity over Uniformity, CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/He_Diversity_over_Uniformity_Rethinking_Representation_in_Generated_Image_Detection_CVPR_2026_paper.html) | 通过抑制特征坍缩保留互补取证线索，改善跨生成器泛化 | 将语义、频域、残差流保留为可审计的独立证据，并做流级消融 | 不证明多流融合在本项目数据上有效 |
| [Leveraging Arbitrary Data Sources, CVPR 2026 Findings](https://openaccess.thecvf.com/content/CVPR2026F/html/He_Leveraging_Arbitrary_Data_Sources_for_AI-Generated_Image_Detection_Without_Sacrificing_CVPRF_2026_paper.html) | 单类数据的 attribution space 和稳定边界，减少生成器依赖 | 增加 only-real / only-generated / mixed-source 的训练协议对照，防止把数据来源当标签 | 论文的跨模型提升不能替代时间切分和传播评测 |
| [Detecting Compressed AI-Generated Images via Phase Spectrum Robustness, CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Li_Detecting_Compressed_AI-Generated_Images_via_Phase_Spectrum_Robustness_CVPR_2026_paper.html) | 利用压缩下更稳定的相位谱特征，针对社交平台压缩 | 在 propagation slice 增加 phase/频域流作为 A2/A6 对照，并单独测 JPEG 多轮退化 | 不能把压缩鲁棒性当成未知生成器鲁棒性 |
| [AI-generated Image Detection: Passive or Watermark?, CVPR 2026 Workshop](https://openaccess.thecvf.com/content/CVPR2026W/SAFE/html/Guo_AI-generated_Image_Detection_Passive_or_Watermark_CVPR_2026_paper.html) | 系统比较被动检测与主动水印的效果、鲁棒性和效率 | 把 provenance/watermark 与 passive forensic 分开记账，建立 conflict matrix 和成本指标 | 水印阳性只说明绑定信号，水印缺失不能证明人类创作 |
| [MLEP, NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/63db94e06ce85dde10871c99dd39ad98-Abstract-Conference.html) | 多尺度局部熵模式，降低语义内容偏差 | 作为轻量 pixel-dependency 对照，比较它和 SRM/DCT 在内容、压缩和局部编辑上的差异 | 单一低层统计仍可能被再生成或再压缩破坏 |
| [FerretNet, NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/3bfcc45018b4156b92197db47e9742bd-Abstract-Conference.html) | 局部像素依赖的轻量检测器，强调效率和跨模型测试 | 纳入 L1 低成本候选分支，报告每千张成本和 P95，而非只报 AUROC | 外部 benchmark 上的准确率不能转成线上 SLA |
| [TAP into the Patch Tokens, CVPR 2026 Workshop](https://openaccess.thecvf.com/content/CVPR2026W/SAFE/html/Abdullah_TAP_into_the_Patch_Tokens_Leveraging_Vision_Foundation_Model_Features_for_AI-Generated_Image_Detection_CVPRW_2026_paper.html) | 比较不同视觉基础模型的 patch token 对 AIGI 检测的影响 | 保持 backbone、patch 尺度和训练预算可替换，避免把 CLIP 固定为唯一答案 | 更换 backbone 不能解决来源缺失、标签噪声和开放集拒判 |

这一轮论文使算法路线更明确：第一阶段不追求再堆一个分类器，而是将“多视角取证、传播稳健特征、主动来源信号、开放集拒判、局部原件条件”作为可以逐项证伪的模块。A8 的核心仍然是 source-conditioned ROI；2026 年的多流和相位谱工作只作为对照流，不能取代该问题定义。

### 3.3 本轮最新证据：从“静态检测器”转向“传播稳健 + 持续适配”

截至 2026-09-20，新增检索到的工作进一步削弱了“训练一个足够大的二分类器就能解决 AIGC”的假设：

| 工作 | 直接证据 | 对本项目的动作 | 证据等级与限制 |
| --- | --- | --- | --- |
| [GlobalForge，2026 预印本](https://arxiv.org/abs/2607.14684) | 将传播退化下的性能下降归因于局部伪影捷径，提出抑制局部组件、加强远距离结构推理和 degradation-contrastive loss，并用 RealDeg-Bench 测 7 类退化及复合链 | 在 source-conditioned 分支之外增加“全局结构稳定性”对照；对每个样本记录单步/复合传播链，报告分数漂移和 coverage-risk | 目前是 arXiv 预印本；论文结果不能直接替代本项目授权数据，且全局结构可能削弱小区域编辑定位 |
| [Fleet，ICML 2026 / arXiv](https://arxiv.org/abs/2606.31082) | 将开放世界检测从静态泛化改为少样本持续适配；报告 64 个模型、20 个商业引擎，并在新引擎上用少量样本恢复性能 | 把“新生成器 5/10-shot 更新”列为运维能力实验；只更新 prototype/router 和 calibration，冻结历史评测集，比较适配前后 selective risk 与旧类退化 | 仍需要项目自有数据和数据权限；不能把少样本新引擎适配写成通用检测能力 |
| [WaRPAD，NeurIPS 2025](https://arxiv.org/abs/2511.14030) | 训练免依赖地利用高频扰动和裁剪一致性，在 23 个生成模型和测试时破坏上评估 | 作为无需训练的 L1 支路；比较 patch 均值、质量加权均值和 source-residual 的稳定性 | 训练免依赖不等于开放集保证；其 score 仍需独立校准和拒判 |
| [Detective SAM，ICLR 2026](https://openreview.net/pdf?id=GKJHPHNFIx) | 将扰动伪影转成 SAM2 的粗到细 mask，并用 AutoEditForge 持续生成新编辑样本；报告新编辑器会使定位崩溃，少量新样本可恢复 | 采用“新编辑器小样本增量集 + ROI 定位回归”而非只追求一次性大训练集；source-residual 作为可解释基线，SAM/分割模型作为后置高成本支路 | 外部 benchmark 的 IoU 不代表本项目效果；自动生成编辑样本仍可能引入合成偏差 |
| [NeXT-IMDL，2025 预印本，已撤稿](https://arxiv.org/abs/2512.23374) | 撤稿前版本把编辑模型、操作类型、语义内容和伪造粒度作为四个泛化轴，指出跨轴评测会显著失败 | 保留“四轴 manifest”作为评测设计启发，但不把该论文的数字当作已发表证据；在本项目中独立实现同类切分 | 该 arXiv 记录明确标注 withdrawn，不能作为稳定结果或排行榜依据 |

这批证据将算法路线从“找一个万能伪影”收敛为三个可独立验证的能力：

1. **传播稳健性**：同一 source/query 在不同压缩、截图和复合链下，证据排序应保持稳定；低质量时宁可拒判。
2. **新生成器持续适配**：新引擎到来时用小样本更新原型、路由或校准，不能重写历史结果，也不能污染测试集。
3. **来源条件定位**：有高质量登记原件时输出局部变化 ROI；无原件或匹配不可靠时回退到 `unknown_or_inconclusive`。

因此，PARFD 的实质创新候选可以进一步表述为：**把“原件条件的局部证据”与“传播稳定性/持续适配门”联合成一个可审计的拒判系统**。这仍是研究假设，必须用 A0–A8、四轴切分、传播复合链和新生成器 few-shot 实验进行证伪。

### 3.4 论文证据进一步收口：应优先做的对照

文献数量已经足够多，下一步不应继续堆论文，而应挑选能改变实现决策的对照：

| 优先级 | 对照 | 实现问题 | 发布门 |
| --- | --- | --- | --- |
| P0 | [AIGIBench](https://papers.nips.cc/paper_files/paper/2025/hash/fb693c67f61e5321746ffce8b6fdd2d0-Abstract-Datasets_and_Benchmarks_Track.html)、[NTIRE 2026 Robust AIGI](https://arxiv.org/abs/2604.11487) 的传播/跨生成器切分 | 当前模型是否只记住生成器或压缩模式 | 必须报告已知、未见、商业黑盒和复合传播链，不能只报 IID AUROC |
| P0 | [SAFE](https://openaccess.thecvf.com/content/WACV2026W/SynRDinBAS/html/Nguyen_The_SAFE_Image_Authenticity_Challenge_Detecting_and_Localizing_Partial_and_Fully_Synthetic_Manipulations_WACVW_2026_paper.html)、[DiffSeg30k](https://arxiv.org/abs/2511.19111) | 全图检测和局部定位是否互相掩盖 | 同时报四态、编辑类型、ROI IoU、pixel F1 和 unknown rate |
| P0 | [QuAD](https://openaccess.thecvf.com/content/CVPR2026W/APAI/html/Guillaro_Quality-Aware_Calibration_for_AI-Generated_Image_Detection_in_the_Wild_CVPRW_2026_paper.html) | 传播版本的质量差异是否让聚合结果失真 | 统计近重复误配率，并比较单图、均值、质量加权、稳健中位数的 ECE/selective risk |
| P1 | [Generator-Aware Prototypes](https://openaccess.thecvf.com/content/CVPR2026/html/Qin_Scaling_Up_AI-Generated_Image_Detection_with_Generator-Aware_Prototypes_CVPR_2026_paper.html)、[IncreFA](https://openaccess.thecvf.com/content/CVPR2026/html/Qin_IncreFA_Breaking_the_Static_Wall_of_Generative_Model_Attribution_CVPR_2026_paper.html) | 新生成器如何加入而不污染历史校准和产生灾难性遗忘 | 版本化 prototype/memory，执行 5/10-shot 适配、回滚和旧类回归 |
| P1 | [VIB-Net](https://openaccess.thecvf.com/content/CVPR2025/html/Zhang_Towards_Universal_AI-Generated_Image_Detection_by_Variational_Information_Bottleneck_Network_CVPR_2025_paper.html)、[SPAI](https://openaccess.thecvf.com/content/CVPR2025/html/Karageorgiou_Any-Resolution_AI-Generated_Image_Detection_by_Spectral_Learning_CVPR_2025_paper.html)、[Phase Spectrum Robustness](https://openaccess.thecvf.com/content/CVPR2026/html/Li_Detecting_Compressed_AI-Generated_Images_via_Phase_Spectrum_Robustness_CVPR_2026_paper.html) | 内容捷径、分辨率和 JPEG 退化分别影响多少 | 作为 A2/A6 低层和谱流消融，分层报告内容、分辨率、压缩和局部编辑跌落 |
| P2 | [OmniGuard](https://openaccess.thecvf.com/content/CVPR2025/html/Zhang_OmniGuard_Hybrid_Manipulation_Localization_via_Augmented_Versatile_Deep_Image_Watermarking_CVPR_2025_paper.html)、[Passive or Watermark?](https://openaccess.thecvf.com/content/CVPR2026W/SAFE/html/Guo_AI-generated_Image_Detection_Passive_or_Watermark_CVPRW_2026_paper.html) | 主动来源信号和被动取证是否应合并 | 合作生成器才启用水印；水印阳性作为来源绑定，缺失/冲突保留 unknown，不参与人类概率 |

最新的来源规范也支持这一分层：C2PA 2.4 新增 `c2pa.ai-disclosure` 等声明，但规范的验证对象仍是 assertion 与资产的绑定、签名和完整性；[OpenAI 对 C2PA/SynthID 的说明](https://openai.com/index/advancing-content-provenance/)也明确“没有找到信号”不能排除受支持来源生成。项目应将这些作为 `provenance` 证据写入证据链，不能把它们转换成无条件的 AIGC 概率。

另一个可纳入研究对照的是 [Forensic Self-Descriptions，CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Nguyen_Forensic_Self-Descriptions_Are_All_You_Need_for_Zero-Shot_Detection_Open-Set_CVPR_2025_paper.html)：它从真实图像自监督学习多尺度预测残差，用于零样本检测、开放集来源归因和聚类。该方向适合检验“只用真实数据建立负例/拒判边界”的可行性，但官方代码为 CC BY-NC-SA 4.0，不能直接作为商业服务依赖；其对高质量真实数据和后处理分布也有要求。Smart Shadow 可以把它重实现为 A2/A7 研究基线，同时保留模型来源、许可和复现结果的隔离。

同样，[B-Free 官方代码/数据仓库](https://github.com/grip-unina/B-Free)标注为 informational/nonprofit only。项目可以借鉴其 content-matched real/fake 配对协议，不能直接把仓库或数据作为商业依赖；若后续需要商业化，只能在完成许可审计后重实现协议或替换为客户授权数据。

## 4. 提议的算法：PARFD

暂定名：**Provenance-Aware Regional Forensic Detector（来源感知区域取证检测器）**。这是项目研究假设，只有完成消融、开放集和扰动评测后才能称为创新结果。

```text
输入图片
  ├─ A. 来源证据：C2PA/Content Credentials、GB 标识、EXIF/XMP、可信水印
  ├─ B. 区域语义：全图 + 多尺度重叠 patch（保留六区域作为基线）
  ├─ C. 低层伪影：SRM/high-pass、DCT 高频/低频、FFT 统计
  ├─ D. 重建支路：LaRE²/AEROBLADE-lite；低置信时离线触发
  └─ E. 开放集归因：生成器 prototype、energy/距离阈值、conformal 校准
                  ↓
             证据级融合与拒判
                  ↓
  四态状态 + 校准置信度 + 区域热图 + 生成器候选 + 原始证据
```

### 4.1 来源证据层

C2PA 2.4 的目标是对来源和编辑历史提供可验证、抗篡改的绑定，并不对内容“好/坏、真/假、人类/AI”作价值判断（见 [C2PA 2.4 说明](https://spec.c2pa.org/specifications/specifications/2.4/explainer/Explainer.html)）。项目应保存 `manifest_hash`、签名者、验证状态、时间戳、动作和 ROI，并在 adapter manifest 中锁定 C2PA 版本；没有凭证时记录 `provenance_unavailable`。同时读取中国《[人工智能生成合成内容标识办法](https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm)》要求的显式/隐式标识，但把 EXIF 等普通元数据定义为弱证据，因为它可以丢失或伪造。

### 4.2 区域—伪影联合层

保留现有六区域 CLIP 作为检索基线，增加共享区域编码器和独立取证头：

- 语义流：CLIP/OpenCLIP 的全图与局部 patch 表示，用于版权相似和局部编辑定位。
- 伪影流：SRM/high-pass 残差、DCT 高频/低频 patch、FFT 径向/角向统计，用于捕捉扩散纹理和重编码残留。
- 可选重建流：只在低置信、高风险或审计任务中触发 LaRE²/AEROBLADE-lite；在线默认路径不能因为重建失败而报告“人类”。

区域注意力可以写成 `α_i = softmax(MLP([semantic_i, artifact_i, quality]))`，但检索头必须与取证 logit 分开。这样同一张图片既可以是版权近邻，又可能是 AIGC，两个分数不会互相污染。

### 4.3 开放集归因与拒判

生成器归因采用 prototype/验证式距离：只有与某一生成器家族的距离低于校准阈值，才输出 `generator_hypotheses`；否则输出 `unknown_generator`。使用 energy/OOD 距离、温度缩放和 conformal coverage-risk 校准，禁止把闭集 softmax 最大类直接当作事实。

### 4.4 证据级融合输出

建议新增响应字段，旧 `is_aigc` 仅保留兼容：

```json
{
  "aigc_status": "human_supported|ai_generated_supported|ai_edited_supported|unknown_or_inconclusive",
  "confidence": 0.0,
  "unknown_reason": "missing_provenance|conflicting_evidence|ood|model_unavailable|low_margin",
  "evidence": [{"type": "c2pa_valid|watermark_positive|metadata_weak|artifact_raw|reconstruction_raw", "value": 0.0, "version": "..."}],
  "generator_hypotheses": [{"family": "...", "distance": 0.0, "accepted": false}],
  "regions": [{"region_id": "...", "score_raw": 0.0, "mask_ref": "..."}],
  "detector_version": "...",
  "calibration_id": "..."
}
```

### 4.5 核心创新候选：Source-Conditioned Regional Edit Forensics

PARFD 中真正值得验证的创新不是把几个现成分类器简单相加，而是利用 Smart Shadow 已经登记的原件，把问题改写成“这张查询图相对于哪个已知原件、哪些局部区域发生了什么变化”。建议先固定一个检索候选 (r^*)，再对 query (q) 和 reference (r^*) 做局部配准：

```text
r* = argmax_r S_retrieval(q, r)
A_ij = softmax_j((cos(e_q_i, e_r_j) + λ · geometry_ij) / τ)
w_i = source_match_i × quality_i
E_edit = Σ_i(w_i · e_i) / (Σ_i w_i + ε)
```

其中 (e_q_i,e_r_j) 是 query/reference 的局部语义或 patch 表示，`geometry` 是可选的坐标/仿射一致性，(e_i) 由以下差异特征产生。对已经配准的灰度区域，先估计 (delta=mathrm{median}(q-r))，再使用 (|(q-r)-delta|) 作为局部残差，避免整体亮度/色调变化伪装成局部 AI 编辑：

- 去除全局偏移后的 `|(q_i-r_i)-δ|`、p95 residual 和 residual coverage，同时保留原始残差和 `δ` 供审计；
- SRM/high-pass 与 DCT 频域差异；
- 颜色/边缘/压缩质量差异；
- 可选的 latent reconstruction error；
- 是否落在已知编辑 mask 或低质量区域。

第一版可以用 `aigc/forensic_features.py` 的 `source-residual-v1` 输出原始观察，再由校准模型学习 (e_i)。训练时必须把同一原件的普通裁剪、缩放、JPEG、滤镜、截图作为“非 AI 变化” hard negatives，把 inpaint、outpaint、img2img、AI upscale 和人类图 + 局部 AI 编辑作为正例，避免模型把任何像素差异都学成 AI：

```text
L = L_pairwise(source/query)
  + λ1 · L_roi(edit_mask)
  + λ2 · L_hard_negative(classical_transform)
  + λ3 · L_calibration(held_out_generator/time split)
```

这条路线的可证伪预测是：在有高质量原件、局部编辑和传播退化的子集上，`source-conditioned` 头应比单图 A0–A7 基线拥有更低的 selective risk、更好的 ROI IoU/pointing-game 和更高的证据包一次复核率；在没有原件、原件匹配低或质量不足时，它必须主动退回 `unknown_or_inconclusive`，不能为了覆盖率强行输出结论。

合规适配器再把取证结果映射为传播事实，不改变模型原始证据：

```text
verified_ai       = trusted C2PA/GB/watermark binding says AI
user_declared_ai  = user declaration without trusted binding
suspected_ai      = explicit/visual/model evidence reaches calibrated suspicion
no_signal_unknown = no reliable evidence, conflict, OOD or model failure
```

`no_signal_unknown` 永远不能降级为 `human_supported`；`c2pa_ai` 与 `watermark_human` 等冲突组合进入人工复核。

## 5. 训练数据和评测协议

评测 manifest 的最小字段和校验命令见 [`eval/README.md`](../eval/README.md)；仓库不提交第三方图片和受限模型权重。

### 5.1 数据分层

- 真实集：相机照片、数字绘画、扫描件、截图，保留来源和授权信息。
- 生成集：SD 1.5/XL/SD3、Midjourney、DALL·E、Flux、GAN/VAE 等多家族。
- 局部编辑：inpaint、outpaint、img2img、AI upscale、风格滤镜和人类图 + AI 局部编辑。
- 外部测试：GenImage/WildFake 训练或基线，Chameleon 难集、RRDataset 传播扰动和 Semi-Truths 局部增强作为外部测试；不能把外部数据授权状态或分布直接当成商业数据。

每张样本应保存 `source_model`、`prompt`、`seed`、`edit_mask`、`postprocess_chain`、分辨率、色彩配置、C2PA 状态和数据许可。

### 5.2 切分和扰动

按作者、原始作品、prompt、生成器和时间分组切分；至少保留整类生成器做 zero-shot 测试。每个样本生成 JPEG 质量 30–100、缩放、5–20% 裁剪、旋转、模糊/锐化、滤镜、截图、再拍摄、社交平台多轮重编码和局部重绘链。不得随机把同一源图的不同压缩版本拆到训练和测试两边。

### 5.3 指标和消融

报告 AUROC、AUPRC、FPR@TPR95 或 TPR@FPR1%、macro-F1、ECE/Brier、unknown rate、coverage-risk/Selective risk、按生成器/来源/分辨率/扰动分层跌落、生成器 top-1/top-5 归因、局部 IoU/pointing game、P95 延迟和显存。版权检索另报 Recall@1/10、mAP、R@P90、CID 聚合误报率。

固定消融序列：

```text
A0 现有元数据 + 旧二分类器（历史基线）
A1 全图 CLIP
A2 AIDE 风格：CLIP + DCT + SRM
A3 A2 + 多尺度重叠区域/局部热图
A4 A3 + LaRE²/AEROBLADE-lite 二阶段复核
A5 A4 + C2PA/水印/元数据证据层和开放集拒判
A6 A5 + 质量感知的近重复/传播融合
A7 A6 + few-shot generator prototype/adaptation
A8 A7 + source-conditioned 原件对齐 residual 与 ROI 取证
```

只有 A8 相对 A0–A7 在未见生成器、局部编辑、传播扰动和校准/拒判指标上稳定改善，且没有把来源字段泄漏到标签，才可以提交“方法创新”或论文主张。若 A8 只在有原件子集有效，应诚实地把贡献限定为 source-conditioned 局部取证，而不是通用 AIGC 检测。

## 6. 首个算法代码切片

在阶段 1–3 的错误、身份和恢复门通过后，按以下顺序实现：

1. **planned provenance adapters**：未来解析 C2PA/EXIF/XMP/GB 标识，输出 valid/missing/invalid/unverified，不改变版权相似度。当前 `aigc/provenance.py` 只接收外部 verifier 结果并检查绑定摘要，不实现 C2PA 密码验证或 GB 标识解析。
2. `aigc/schema.py`：实现四态响应、原始证据和版本字段；`is_aigc` 只由新状态派生。
3. `aigc/source_conditioned.py`：把已登记原件和查询图的区域对齐分数聚合成 ROI 原始证据，不直接作法律判断。
4. **已完成的无重量特征切片**：`aigc/forensic_features.py` 对已经对齐的 reference/query 灰度区域计算绝对残差、p95 残差、一阶边缘残差、残差覆盖率和质量门，输出 `source-residual-v1` 原始证据；`source-residual-roi-v1` 在稳健去除全局偏移后输出候选 bbox/mask，供 ROI IoU 和人工复核评测；`eval/source_residual_eval.py` 只在合成 hard negatives/局部编辑上做确定性回归。`aigc/compliance.py` 将可信来源、用户声明、水印和视觉结果映射成传播标签并保留冲突；这些模块都不读取真实图片、不判定 AIGC，也不替代校准器。
5. **planned detector adapters**：未来在 `aigc/regional_detector.py` 中保留六区域基线，增加多尺度重叠 patch、独立 retrieval/forensic head；该文件当前不存在。
6. `aigc/calibration.py`、**planned open-set/evaluation adapters**：当前已实现保守 operating point、负例 conformal p-value 和拒判契约；`aigc/open_set.py` 与 `evaluate.py` 尚未创建。`NegativeConformalProfile` 只提供负例一致性观察，不把非拒判转成“人类”，也不把拒判转成“AI”。
7. **planned reconstruction adapter**：`aigc/reconstruction.py` 尚未创建；未来才评估低置信样本的 LaRE²/AEROBLADE-lite 复核。

当前切片还加了三个数据边界：不同 `alignment_version` 不混合、同一 aggregate 的 `region_id` 不重复、空输入和非法 bool/维度直接拒绝。它们是工程防错，不是效果证明；真实图像适配仍需 Pillow/NumPy 或其他已审查依赖。

## 7. 可验证的研究创新边界

当前可以提出的研究假设是：

1. 来源凭证与被动取证分层，能减少元数据缺失和模型漂移导致的错误结论。
2. 多尺度局部区域与有向版权匹配，能同时处理裁剪复制和局部 AI 编辑。
3. 高成本重建只服务于低置信样本，能在可接受 P95 延迟下提高审计召回。
4. 开放集拒判和人工复核链，能降低把未知生成器误报为已知生成器或人类的风险。

以上都不是已证实的创新点。必须用固定数据版本、完整消融和外部测试证明后，再更新项目决策和论文材料。

## 8. 论文证据收口：把外部结论转成可证伪实验

下面只保留与 Smart Shadow 当前路线直接相关、且能落到现有评测门的论文。表中的“项目实验”是待执行协议；论文中的数字和结论不属于本仓库的效果结果。

| 一手来源 | 外部证据能支持的判断 | Smart Shadow 的可证伪实验 | 不能直接推出 |
| --- | --- | --- | --- |
| [AIGIBench，NeurIPS 2025](https://papers.neurips.cc/paper_files/paper/2025/hash/fb693c67f61e5321746ffce8b6fdd2d0-Abstract-Datasets_and_Benchmarks_Track.html) | 23 个伪造子集覆盖多来源、退化、增强和测试预处理；受控测试中的高分在野外会明显下降 | 对 A0–A5 固定模型做 `known_generator`、`commercial_black_box`、`propagation` 和 `temporal_next_period` 分层报告 | 不能把外部 benchmark 的下降幅度当作本项目模型的下降幅度 |
| [SAFE，WACV 2026 Workshop](https://openaccess.thecvf.com/content/WACV2026W/SynRDinBAS/html/Nguyen_The_SAFE_Image_Authenticity_Challenge_Detecting_and_Localizing_Partial_and_Fully_Synthetic_Manipulations_WACVW_2026_paper.html) | 同时要求全图真实性、篡改类型和像素级定位，并提供可追踪的操作历史；现有系统在定位上仍脆弱 | `partial_edit` 必须同时报告四态分类、编辑类型 macro-F1 和 ROI IoU/coverage；保留编辑链与 mask digest | 不能把全图 AUROC 当作局部编辑定位能力 |
| [QuAD，CVPR 2026 Workshop](https://openaccess.thecvf.com/content/CVPR2026W/APAI/html/Guillaro_Quality-Aware_Calibration_for_AI-Generated_Image_Detection_in_the_Wild_CVPRW_2026_paper.html) | 近重复传播版本的质量差异会改变检测分数；按质量融合比简单平均更稳定 | 对已登记 CID 的传播版本建立 `near_duplicate_group`，比较单图、简单平均和质量加权的 ECE、balanced accuracy 与 unknown rate | 不能假设近重复检索无误；漏检和误配必须单独计入失败率 |
| [MCID，ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/papers/Huang_MCID_Multi-aspect_Copyright_Infringement_Detection_for_Generated_Images_ICCV_2025_paper.pdf) | 将版权风险拆为内容、风格、结构和 IP 四类，并用法律专家标注数据评测可解释结果 | 在证据包中分别保存四类风险分数与证据，做四类 macro-F1、校准和人工复核一致性；任何一类都只输出风险提示 | 多维风险标签不等于法律上的侵权成立，也不替代权利链核验 |
| [WaRPAD，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/1d8f05e4da49a4e1e1b052a3046bceac-Abstract-Conference.html) | 利用自监督模型对裁剪和高频扰动的敏感性，提供免训练的轻量检测支路 | 将其作为 L1 被动支路，比较原图、裁剪、resize、JPEG 和截图下的 AUROC、P95 延迟与每千张成本 | 免训练不代表开放集可靠；未知生成器和对抗再生成仍需拒判测试 |
| [DICE，ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Baraldi_What_Changed_Detecting_and_Evaluating_Instruction-Guided_Image_Edits_with_Multimodal_ICCV_2025_paper.html) | 原图—编辑图差异可以与编辑指令一致性分开评估，适合局部变化解释 | 仅在有登记原件时比较 residual ROI 与人工 mask，并把“变化存在”和“变化是否符合指令”分成两个字段 | 编辑质量/指令一致性不是来源证明，不能替代 C2PA 或人工权属判断 |
| [X-Edit，CVPRW 2025](https://openaccess.thecvf.com/content/CVPR2025W/XAI4CV/papers/Bazyleva_X-Edit_Detecting_and_Localizing_Edits_in_Images_Altered_by_Text-Guided_CVPRW_2025_paper.pdf) | 将文本引导扩散局部编辑定义为成对检测与定位任务，强调原图—编辑图和编辑区域 | 用于冻结 `source/query/edit_mask` 三元组及传播后 ROI 评测，比较配准 residual 与 inversion/segmentation 支路 | 外部成对数据集不等于客户授权数据；局部检测结果不自动说明谁拥有权利 |
| [Region-Level Data Attribution，ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/papers/Nguyen_Region-Level_Data_Attribution_for_Text-to-Image_Generative_Models_ICCV_2025_paper.pdf) | 把生成内容追溯到训练数据的影响区域，说明“近邻检索”和“训练来源归因”是不同任务 | 将训练数据来源/许可审计列为中长期扩展；证据包分开记录相似近邻、模型来源假设和许可证据 | 训练来源归因需要模型侧日志或可验证数据，不能由图片相似度单独推出侵权 |
| [AIGI-Holmes，ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/papers/Zhou_AIGI-Holmes_Towards_Explainable_and_Generalizable_AI-Generated_Image_Detection_via_Multimodal_ICCV_2025_paper.pdf) | 解释数据和偏好对齐可改善人类可核验的说明层 | 只把解释用于复核界面；对 evidence-to-explanation 一致性做盲评，不允许自由生成文本覆盖原始证据 | 可解释文本本身不是伪造证明；基础检测分数仍需独立校准 |
| [Detecting Origin Attribution，WACV 2025](https://openaccess.thecvf.com/content/WACV2025/papers/Xu_Detecting_Origin_Attribution_for_Text-to-Image_Diffusion_Models_WACV_2025_paper.pdf) | 闭集生成器归因可利用风格/结构特征，但归因结果受生成器集合影响 | 以 `generator_hypotheses` 做 prototype/energy 距离和拒判曲线，分已知、同家族未见、架构未见报告 coverage-risk | 闭集超过 90% 的结果不能支持未知生成器归因或人类/AI 二分类结论 |
| [Diversity over Uniformity，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/He_Diversity_over_Uniformity_Rethinking_Representation_in_Generated_Image_Detection_CVPR_2026_paper.html) | 抑制特征坍缩、保留互补伪影线索，有助于跨生成器泛化 | 对语义、频域、残差三路做流级消融，比较 `unseen_architecture` 和 `temporal_next_period` 的 coverage-risk 与 ECE | 外部提升不能证明多流在本项目授权数据上有效 |

这张表把“主要创新点”收敛为可检验的组合：**来源证据分层、原件条件的局部取证、开放集拒判、传播近重复质量融合和多维版权风险筛查**。只有在同一 manifest、同一校准规则和 A0–A8 消融中同时改善质量指标与成本指标后，才可以把其中某项写成项目创新结果。

## 9. 2026-09 深度调研补充：把研究假设收敛为可执行对照

本节只补充外部研究对现有路线的约束。论文或预印本中的数字不属于 Smart Shadow 的实验结果；任何模型接入前都需要通过授权数据、时间/生成器切分和独立校准集验证。

### 9.1 传播质量、校准和近重复

- [QuAD，CVPR 2026 APAI Workshop](https://openaccess.thecvf.com/content/CVPR2026W/APAI/html/Guillaro_Quality-Aware_Calibration_for_AI-Generated_Image_Detection_in_the_Wild_CVPRW_2026_paper.html) 将同一图片的网络近重复视为质量条件样本，而不是可以直接平均的独立观测。其核心思路是分别拟合 `l | q, y=1` 和 `l | q, y=0` 的质量条件分布，再计算质量条件似然比。Smart Shadow 当前的 `quality_score ** quality_power` 只能保留为 raw evidence；后续应把 QuAD 风格的质量条件 log-likelihood 与简单均值、稳健中位数并列消融，并保存质量估计版本、近重复误配率和完整传播链。
- [Your AI-Generated Image Detector Can Secretly Achieve SOTA Accuracy, If Calibrated，AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/38146) 和 [Enhancing Synthetic Generated-Images Detection through Post-Hoc Calibration，WACV 2025 Workshop](https://openaccess.thecvf.com/content/WACV2025W/AI4MFDD/html/Dimitri_Enhancing_Synthetic_Generated-Images_Detection_through_Post-Hoc_Calibration_WACVW_2025_paper.html) 都支持把 calibration 当作独立实验因素。每个 detector/传播 profile 必须保存 `calibration_id`、校准集 digest、temperature/Platt/isotonic 版本、ECE/NLL 和 coverage-risk；未经校准的 logit 不能在接口中命名为概率。

### 9.2 未知生成器、开放集和持续适配

| 外部工作 | 对 Smart Shadow 的研究动作 | 不能直接推出 |
| --- | --- | --- |
| [HSIC Bottleneck for Cross-Generator and Domain-Incremental Synthetic Image Detection，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/7c68f26cecf67f0b76fed25a702ddd94-Abstract-Conference.html) | 增加“按时间顺序加入新生成器”的增量实验；只更新 prototype/router/calibration，冻结历史测试集，并用 replay 版本记录旧类回归 | 论文的跨族泛化不能推出本项目在新模型或中文平台上的泛化 |
| [GFRE，IJCAI 2026](https://www.ijcai.org/proceedings/2026/131) | 作为通用视觉表征重建误差的轻量 baseline，与 LaRE²/AEROBLADE-lite 比较质量、显存和 P95 延迟 | 外部 accuracy/generalization 提升不能迁移为项目效果 |
| [One for All: Synthesis-Free Fingerprint Learning，AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/40851) | 以 amplitude-spectrum fingerprint/prototype 做生成器来源候选和开放集 OSCR 对照；输出只能作为 `generator_hypotheses` | 生成器归因不是 AIGC 真实性或法律权属结论 |
| [Few-Shot Learner Generalizes Across AI-Generated Image Detection，ICML 2025](https://proceedings.mlr.press/v267/wu25r.html) | 固定 5/10-shot 支持集版本，比较适配前后 selective risk、ECE、unknown rate 和旧生成器退化；支持集不得混入历史测试集 | 少量样本适配不能被写成通用持续学习能力 |
| [Test-Time Curriculum for Open-Set AIGC Detection，arXiv 2608.00559](https://arxiv.org/abs/2608.00559) | 若研究 test-time adaptation，只允许离线 shadow profile；记录适配前后、回滚和旧类回归，线上请求不得直接改生产模型 | 该工作是预印本，且伪标签自训练存在漂移和错误累积风险 |

开放集实验至少应区分：已知生成器、同家族未见模型、架构未见模型、时间上下一代模型和普通传播 hard negative。所有类别都需报告 unknown/abstain rate 与 coverage-risk，不能只报告 closed-set top-1。

### 9.3 局部编辑、过程定位和内容偏差

- [SAFE Image Authenticity Challenge，WACV 2026 Workshop](https://openaccess.thecvf.com/content/WACV2026W/SynRDinBAS/html/Nguyen_The_SAFE_Image_Authenticity_Challenge_Detecting_and_Localizing_Partial_and_Fully_Synthetic_Manipulations_WACVW_2026_paper.html) 要求同时输出全图真实性、篡改类型和 pixel-level mask。项目 manifest 因此要保留 `edit_type`、`edit_mask_digest`、全图状态和 ROI；评测要同时报告类型 macro-F1、ROI IoU/Dice/boundary-F1 和人工复核一致性。
- [RITA，CVPR 2026 Findings](https://openaccess.thecvf.com/content/CVPR2026F/html/Zhu_Revisiting_Image_Manipulation_Localization_under_Realistic_Manipulation_Scenarios_CVPRF_2026_paper.html) 将一次性 mask 扩展为按编辑步骤的层级/顺序预测。对 Smart Shadow 的直接约束是保存 `edit_steps[]` 和 mask lineage；单步编辑、多步编辑、传播后定位必须分层报告，不能用单张最终 mask 代替过程证据。
- [SFLD，WACV 2025](https://openaccess.thecvf.com/content/WACV2025/papers/Gye_Reducing_the_Content_Bias_for_AI-Generated_Image_Detection_WACV_2025_paper.pdf) 用内容近似的真实/生成配对降低内容捷径。授权数据应优先构造同源或同语义 hard negative；随机抽取不同内容的 real/fake 对不能证明模型没有内容偏差。

这些工作支持的项目假设是：source-conditioned ROI 取证应在有高质量原件时更有价值，但必须把普通裁剪、缩放、JPEG、截图和滤镜作为非 AI 变化的同源反事实，避免把任何像素差异学成 AI 编辑。

### 9.4 来源、水印和证据冲突矩阵

[C2PA 2.4 Specification](https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html) 新增 `c2pa.ai-disclosure`，可记录模型类型、模型标识、科学领域和人工监督级别；`actions`、`digitalSourceType`、ingredients 和签名表达来源/编辑绑定。它验证的是声明和资产的绑定与完整性，不是图像事实真伪。项目应锁定 C2PA 版本并保存 manifest digest、签名者、动作、验证错误和审计时间。

对来源凭证和水印的组合，先实现审计矩阵，再决定是否进入融合：

| 状态 | manifest | watermark | 处理 |
| --- | --- | --- | --- |
| Q1 `silent_zone` | 无效/缺失 | 无 | `no_signal_or_unknown`，不能映射为人类创作 |
| Q2 `fragile_provenance` | 无效/缺失 | 有 | 记录水印来源和验证范围；若不能绑定资产则进入复核 |
| Q3 `authenticated_content` | 有效 | 无 | 保留已验证来源/编辑链；仍不自动判断内容真伪 |
| Q4a `verified_synthetic` | 有效 | 有 | manifest 明确 AI 来源时输出 `verified_ai` 适配标签，并保留取证结果 |
| Q4b `integrity_clash` | 有效 | 有 | manifest 未披露 AI 或与水印冲突时进入人工复核/拒判 |

[Authenticated Contradictions，CVPR 2026 APAI Workshop](https://openaccess.thecvf.com/content/CVPR2026W/APAI/papers/Nemecek_Authenticated_Contradictions_from_Desynchronized_Provenance_and_Watermarking_CVPRW_2026_paper.pdf) 的受控实验支持把 Q4b 当作冲突审计场景，但不能把其 100% 分类结果外推为通用安全保证。[Erasing the Invisible，NeurIPS 2025 Datasets and Benchmarks](https://proceedings.neurips.cc/paper_files/paper/2025/hash/15389039ccef67b6bed9b2df8414400f-Abstract-Datasets_and_Benchmarks_Track.html) 也提醒水印可被高质量移除，因此水印始终只是证据层之一。

### 9.5 Paired Counterfactual Source-Conditioned Forensic Test（研究假设）

在现有 source-residual 和传播质量融合之上，新增一个可证伪的组合假设：对 query 与登记原件 `r*` 做局部配准，并为每条实际传播链 `g` 构造同传播族、无局部编辑的 `g(r*)` 反事实。对 observed 与 counterfactual 在相同 patch/ROI 上提取语义差异、残差、频域和质量特征：

```text
delta_i = evidence_observed_i - evidence_counterfactual_i
```

在同源普通变换 hard-negative 上按传播族/质量分组估计 null 分布，使用经验 FPR 或 conformal 校准；ROI 采用 group-wise/spatial correction，避免把相邻 patch 当独立样本；再与 QuAD 风格质量条件 likelihood 聚合比较。缺少原件、反事实、传播族覆盖不足、参考误配、质量过低或 OOD 时必须输出 `unknown_or_inconclusive`/`abstained`。

这是一项尚未证明学术新颖性的研究假设。已有工作分别覆盖近重复质量聚合、传播鲁棒、局部 mask 和开放集适配；在完成 prior-art 检索与 A0–A8 消融前，不得把上述组合写成已证实创新。其最低验收应包括：普通传播 hard-negative 误报率、参考误配率、分数漂移、coverage-risk、ROI 指标、P95 延迟和证据包一次复核率。

## 10. 2025–2026 一手论文增补：PC-SCFT 的直接约束

本节只追加能改变 Smart Shadow 实验设计的近期一手来源。证据等级定义如下：

- **A**：主会或正式期刊的同行评审论文，并可在会议/出版社页面取得全文或正式摘要。
- **B**：正式 workshop、challenge 或 findings 论文；适合约束评测协议和工程边界，不能单独证明通用算法效果。
- **C**：arXiv/技术报告/尚未完成同行评审的工作；只作为研究假设或红队用例。

等级是来源的出版证据等级，不是 Smart Shadow 的验证等级。下面所有“项目实验”都属于待执行协议；论文中的数字不能写成仓库结果。

### 10.1 局部 AI 编辑、二阶差分与原件条件对照

| 一手来源 | 等级 | 外部贡献 | 对 PC-SCFT 的实验映射 | 不可推出 |
| --- | --- | --- | --- | --- |
| [A Difference-in-Difference Approach to Detecting AI-Generated Images，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Qi_A_Difference-in-Difference_Approach_to_Detecting_AI-Generated_Images_CVPR_2026_paper.html) | A | 用重建误差的二阶差分降低一次重建误差的方差，提升跨生成器检测。 | 在 A2/A4/A8 中并列比较 `first_order_reconstruction`、`second_order_difference` 与 `observed-counterfactual`；要求同一传播链、同一 ROI 和同一质量分层。 | 该工作是单图/全局检测思路，不能直接证明有登记原件的局部编辑定位，也不能证明法律来源。 |
| [HIDE: Detecting Diffusion-Based Inpainting via Latent h-Space Representation，CVPRW 2026](https://openaccess.thecvf.com/content/CVPR2026W/SAFE/html/Ji_HIDE_Detecting_Diffusion-Based_Inpainting_via_Latent_h-Space_Representation_CVPRW_2026_paper.html) | B | 把扩散模型中间层 h-space 语义先验与频域特征结合到分割网络，针对扩散修补。 | 作为 PC-SCFT 的语义/统计辅助流；在已对齐 patch 上比较 h-space、SRM/DCT 和 `delta` 的 ROI IoU、unknown rate。 | 论文以 Stable Diffusion 1.5 修补为主，不能推出对未知生成器、全局重生成或中国平台传播有效。 |
| [DiffusionPrint: Learning Generative Fingerprints for Diffusion-Based Inpainting Localization，CVPRW 2026](https://openaccess.thecvf.com/content/CVPR2026W/AIMS/html/Giakoumoglou_DiffusionPrint_Learning_Generative_Fingerprints_for_Diffusion-Based_Inpainting_Localization_CVPRW_2026_paper.html) | B | 学习 patch 级生成指纹，并用跨类别 hard negative 提高未见编辑 mask 的定位。 | 作为 generator-fingerprint 支路；做“指纹分数 vs. PC-SCFT delta”消融，显式测试生成器变化是否被误认为编辑证据。 | 生成器指纹是被动线索，不等于来源凭证；即使未见 mask 泛化，也不能推出未知生成器开放集保证。 |
| [Detecting AI-Generated Forgeries via Iterative Manifold Deviation Amplification（IFA-Net），CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/papers/Zhang_Detecting_AI-Generated_Forgeries_via_Iterative_Manifold_Deviation_Amplification_CVPR_2026_paper.pdf) | A | 以真实图像 MAE 流形为先验，先粗定位再用任务提示放大重建残差。 | 作为低置信/离线复核支路；比较单次 residual、IFA 式迭代 residual 与 PC-SCFT 的 coverage-risk 和 P95。 | 四个扩散修补 benchmark 的定位提升不能推出高保真新生成器、来源证明或线上实时可用。 |
| [The SAFE Image Authenticity Challenge，WACV 2026 Workshop](https://openaccess.thecvf.com/content/WACV2026W/SynRDinBAS/html/Nguyen_The_SAFE_Image_Authenticity_Challenge_Detecting_and_Localizing_Partial_and_Fully_Synthetic_Manipulations_WACVW_2026_paper.html) | B | 同时要求全图真实性、篡改类型和像素 mask，并保留可追踪编辑历史。 | 将 `edit_type`、`edit_steps[]`、`edit_mask_digest` 加入 manifest；A8 必须同时报告四态、类型 macro-F1、ROI IoU/Dice 和 unknown rate。 | 全图 AUROC 或挑战排名不能替代局部定位、证据链或商业 SLA。 |
| [OpenSDI: Spotting Diffusion-Generated Images in the Open World，CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Wang_OpenSDI_Spotting_Diffusion-Generated_Images_in_the_Open_World_CVPR_2025_paper.html) | A | 用多 VLM、SD1.5/2.1/XL/3/Flux 和全局/局部编辑构造开放世界检测与定位。 | 建立 `known_generator`、`same_family_unseen`、`architecture_unseen`、`local_edit` 四个切分；PC-SCFT 只在 source match 可靠的子集承诺 ROI，其他样本必须拒判。 | OpenSDI 的 benchmark 提升不能外推到 Smart Shadow 授权图库，也不能把模型输出当来源或法律结论。 |
| [Forensic-Friendly Image Manipulation via Controllable Latent Diffusion，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Chen_Forensic-Friendly_Image_Manipulation_via_Controllable_Latent_Diffusion_CVPR_2026_paper.html) | A | 在生成端用可控投影、隐式检测和显式引导，使编辑区域更利于第三方取证。 | 若有生成平台合作，将其作为“主动可取证编辑”对照；比较普通编辑、FFIM 编辑与 PC-SCFT 的 ROI 召回、视觉质量和水印/manifest 保留。 | 这是生成端协同方案，不是对任意既有图片的被动检测；不能把可取证生成器的效果外推到全网内容。 |

`A Difference-in-Difference` 与 PC-SCFT 都含“差分抑制传播/重建噪声”的思想，因而 PC-SCFT 的新颖性不能只写成“使用二阶差分”。可辩护的差异应限定为：**有登记原件、同传播族无编辑反事实、区域配准、质量条件校准和拒判证据链的组合协议**；仍需 prior-art 对照和 A0–A8 消融证明。

### 10.2 开放集、跨生成器和持续鲁棒性

| 一手来源 | 等级 | 外部贡献 | 对项目实验的映射 | 不可推出 |
| --- | --- | --- | --- | --- |
| [NTIRE 2026 Challenge on Robust AI-Generated Image Detection in the Wild](https://openaccess.thecvf.com/CVPR2026_workshops/NTIRE) | B | 42 个开源/闭源生成器、108,750 张真实图、185,750 张生成图和 36 类变换，直接评估真实传播鲁棒性。 | 将 NTIRE 风格的生成器×变换矩阵加入 A6–A8；报告每一生成器/变换的 AUROC、FPR、ECE、unknown rate、分数漂移和 P95，而不是只报总体 ROC。 | challenge 数据分布和排行榜不能证明本项目在中文平台或客户图库上的效果；它也不包含 PC-SCFT 所需的登记原件配对。 |
| [Diversity over Uniformity: Rethinking Representation in Generated Image Detection（DoU/AFCL），CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/He_Diversity_over_Uniformity_Rethinking_Representation_in_Generated_Image_Detection_CVPR_2026_paper.html) | A | 通过 Cue Information Bottleneck、Adaptive Feature Correlation Learning 和多阶段 CLIP 保留互补伪影，缓解特征坍缩和单一捷径。 | 将 DoU/AFCL 作为 A2/A7 的训练型对照；记录语义、频域、残差三流的独立贡献、相关性和 leave-one-generator-out coverage-risk，再与 PC-SCFT 融合前后比较。 | 互补表征在公开 benchmark 的跨模型提升不能推出来源条件 ROI 有效，更不能把“多流”当作自动开放集保证。 |
| [Improving Synthesized Image Detection by Disentangling Generator-Shared and Generator-Specific Image Artifacts，CVPR 2026 Findings](https://openaccess.thecvf.com/content/CVPR2026F/html/Yang_Improving_Synthesized_Image_Detection_by_Disentangling_Generator-Shared_and_Generator-Specific_Image_Artifacts_CVPRF_2026_paper.html) | A | 显式分离生成器共享伪影、生成器特有伪影和真实图特征，减少跨生成器捷径。 | 在训练和报告中加入 `shared_artifact`/`generator_specific` 消融；PC-SCFT 的 counterfactual null 需按生成器家族分层，避免把特有伪影当局部编辑。 | OOD accuracy 提升不能推出时间上下一代模型或传播后版本的覆盖保证。 |
| [PPM-CLIP: Probabilistic Prompt Modeling for Generalizable AI-Generated Image Detection，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Wang_PPM-CLIP_Probabilistic_Prompt_Modeling_for_Generalizable_AI-Generated_Image_Detection_CVPR_2026_paper.html) | A | 用输入条件概率 prompt 和 patch-wise 对比学习替代固定二分类边界。 | 作为无原件时的单图回退基线；比较静态 detector、PPM-CLIP、PC-SCFT 的 selective risk 和校准，禁止把 prompt 生成器当证据来源。 | 跨域 benchmark 结果不能推出未知生成器的概率保证，也不能解决来源缺失。 |

### 10.3 来源凭证、水印和冲突审计

| 一手来源 | 等级 | 外部贡献 | 对项目实验的映射 | 不可推出 |
| --- | --- | --- | --- | --- |
| [GenPTW: Latent Image Watermarking for Provenance Tracing and Tamper Localization，AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/37412) | A | 统一 LDM/VAR 的生成中与生成后嵌入，以语义 cross-attention 和空间融合同时做来源追踪与篡改定位。 | 在合作生成器路径增加 provenance watermark adapter；比较 watermark-only、PC-SCFT-only 和 conflict-aware fusion，并记录密钥/验证器版本。 | 水印阳性只支持“受支持生成链的绑定证据”；水印缺失、可移除或第三方图片不能被转译为人类创作。 |
| [Dual-Guard: Dual-Channel Latent Watermarking for Provenance and Tamper Localization in Diffusion Images](https://arxiv.org/abs/2604.19090) | C | 用初始噪声 Gaussian Shading 做全局来源信号，用最终 latent fingerprint 做局部锚点，区分 reprompting 与局部编辑。 | 作为红队/未来合作生成器对照：验证“全局来源阳性、局部锚点破坏”的冲突状态，并检查 PC-SCFT 是否错误地把 watermark 残差当编辑。 | arXiv 预印本的 2,400 样本结果不能支持生产安全或跨供应商泛化；其方案依赖生成端控制和密钥。 |
| [Rel-Zero: Harnessing Patch-Pair Invariance for Robust Zero-Watermarking Against AI Editing，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Chen_Rel-Zero_Harnessing_Patch-Pair_Invariance_for_Robust_Zero-Watermarking_Against_AI_Editing_CVPR_2026_paper.html) | A | 从编辑相对稳定的 patch-pair 关系生成不修改原图的 zero-watermark。 | 对已登记原件比较 Rel-Zero 关系、PC-SCFT 对齐 residual 和 C2PA；把 zero-watermark 作为来源检索/版本归并信号，不直接进入 AIGC 概率。 | zero-watermark 的匹配成功不能说明编辑者、创作贡献或侵权事实；大范围重生成和未登记原件仍是开放问题。 |
| [AI-generated Image Detection: Passive or Watermark?，CVPRW 2026](https://openaccess.thecvf.com/content/CVPR2026W/SAFE/html/Guo_AI-generated_Image_Detection_Passive_or_Watermark_CVPRW_2026_paper.html) | B | 在四数据集、八类普通扰动和三类对抗扰动下比较被动 detector 与 watermark detector 的效果、鲁棒性和效率。 | 建立 `provenance × watermark × visual` 冲突矩阵；分别报告可验证来源覆盖率、被动取证 FPR、冲突率和人工复核率。 | 论文的“某类 watermark 更强”不能推出任意供应商水印都可靠；水印验证范围和密钥信任必须单独审计。 |
| [From Detection to Audit: Deterministic Where/When OoC Verification with EvidenceSPOTL，CVPRW 2026](https://openaccess.thecvf.com/content/CVPR2026W/PPMisDet/html/Matsukura_From_Detection_to_Audit_Deterministic_WhereWhen_OoC_Verification_with_EvidenceSPOTL_CVPRW_2026_paper.html) | B | 用可重放证据记录、透明规则和 NEI-by-design 的拒判策略，将检测结果变成可审计证据链。 | 借鉴其 `evidence record → normalized claim → commit/abstain` 流程；PC-SCFT 只在原件、反事实、质量和校准字段齐全时提交，缺字段固定进入 `unknown_or_inconclusive`。 | 该论文针对时空语境核验，不证明图像 AIGC 检测准确；可审计规则也不等于法律裁决。 |

### 10.4 传播质量、神经压缩与校准边界

| 一手来源 | 等级 | 外部贡献 | 对项目实验的映射 | 不可推出 |
| --- | --- | --- | --- | --- |
| [QuAD: Quality-Aware Calibration for AI-Generated Image Detection in the Wild，CVPRW 2026](https://openaccess.thecvf.com/content/CVPR2026W/APAI/html/Guillaro_Quality-Aware_Calibration_for_AI-Generated_Image_Detection_in_the_Wild_CVPRW_2026_paper.html) | B | 用近重复树和真实网络近重复按质量条件校准、聚合 detector 分数，提出 AncesTree 与 ReWIND。 | 在同一 `near_duplicate_group` 内比较 plain mean、quality-weighted、quality-conditional likelihood 和 PC-SCFT delta；记录误配率、质量估计版本、ECE/NLL 和 coverage-risk。 | 质量加权只改善证据聚合，不构成 AIGC 概率或原件匹配保证；近重复误配必须单独计入失败率。 |
| [Is JPEG AI going to change image forensics?，ICCVW 2025](https://openaccess.thecvf.com/content/ICCV2025W/APAI/html/Cannas_Is_JPEG_AI_going_to_change_image_forensics_ICCVW_2025_paper.html) | B | 发现 JPEG AI 神经压缩痕迹会降低合成检测和拼接定位，并制造与生成伪影相似的误报。 | 将 JPEG AI/神经压缩作为显式传播 hard negative；比较 PC-SCFT `observed-counterfactual`、传统 JPEG 和 JPEG AI 的 FPR、残差分布和拒判率。 | 未验证的 JPEG AI 版本、编码器或参数不能被当作通用攻击；单次误报下降不能推出所有神经压缩都可识别。 |
| [Are High-Quality AI-Generated Images More Difficult for Models to Detect?，ICML 2025](https://proceedings.mlr.press/v267/xiao25g.html) | A | 发现人类感知质量与 detector 难度不必单调，饱和度、对比度和纹理等内容因素会同时影响二者。 | `quality_score` 只能作为“取证适用性”或校准条件；必须测质量分层的 FPR/TPR，禁止把高质量直接当成低 AIGC 概率或把低质量排除当作安全。 | 外部质量—检测关系不能迁移为本项目阈值；质量指标与来源真实性是不同变量。 |

### 10.5 可解释取证与证据到文本的一致性

| 一手来源 | 等级 | 外部贡献 | 对项目实验的映射 | 不可推出 |
| --- | --- | --- | --- | --- |
| [FakeXplain: AI-Generated Image Detection via Human-Aligned Grounded Reasoning，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/701ec28790b29a5bc33832b7bdc4c3b6-Abstract-Conference.html) | A | 用带 bbox 与说明的 FakeXplained 数据训练检测、定位和人类对齐解释，强调 OOD 和视觉证据落地。 | 在证据包增加 `evidence_regions`、`caption_ref` 和 mask-out faithfulness；对 PC-SCFT 热图做区域遮挡回归，解释不能改变 raw score。 | 解释与人工偏好一致不等于检测器正确；公开数据上的 IoU/accuracy 不能支持法律结论。 |
| [Pixels Don't Lie (But Your Detector Might): DeepfakeJudge，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Kuckreja_Pixels_Dont_Lie_But_Your_Detector_Might_Bootstrapping_MLLM-as-a-Judge_for_CVPR_2026_paper.html) | A | 将解释可信度作为独立 meta-evaluation，用 OOD 伪造集、人工标注和 judge 评估 groundedness/faithfulness。 | 只把 MLLM judge 用于离线解释审计；对同一 raw evidence 比较 explanation faithfulness、区域指向和人工复核时间，不让语言模型覆盖 `aigc_status`。 | judge 分数、用户偏好或自然语言流畅度都不是来源真实性；不能用 MLLM 解释替代校准 detector。 |
| [ReAlign: Generalizable Image Forgery Detection via Reasoning-Aligned Representation，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/papers/Huang_ReAlign_Generalizable_Image_Forgery_Detection_via_Reasoning-Aligned_Representation_CVPR_2026_paper.pdf) | A | 将高质量推理文本蒸馏进轻量 detector，尝试获得语义敏感和跨域泛化。 | 作为未来轻量模型对照；要求 reasoning text 与 PC-SCFT ROI/manifest 对齐，并用 mask-out、counterfactual swap 检验是否真的依赖图像证据。 | 蒸馏推理文本可能复制数据集偏差；跨域 accuracy 不能证明解释因果性、开放集保证或来源证据。 |

### 10.6 由增补论文确定的最小实验矩阵

将新增工作压缩为五组可复现实验，避免继续无边界堆模型：

```text
E1  局部编辑：SAFE/OpenSDI 切分，A0–A8，四态 + edit_type + ROI IoU/Dice + unknown rate
E2  差分对照：first-order reconstruction vs Difference-in-Difference vs PC-SCFT delta
E3  跨生成器/传播：NTIRE 42 generators × 36 transforms，并加入 JPEG AI hard negative
E4  来源冲突：C2PA/manifest × GenPTW/Dual-Guard/Rel-Zero watermark × passive evidence
E5  可解释审计：FakeXplain/DeepfakeJudge 风格 mask-out faithfulness、证据完整性和人工复核时间
```

PC-SCFT 只有在 E1–E5 中同时满足以下条件，才可以考虑写成方法创新：相对 A0–A7 在有原件子集降低 selective risk、提升 ROI 指标和校准质量；在普通传播和 JPEG AI hard negative 上不增加 FPR；来源冲突时保持可审计拒判；解释区域与 raw evidence 通过遮挡回归。任何单项提升都只能写成对照结果，不能写成“解决 AIGC”。

### 10.7 本轮官方页面复核：高分辨率、压缩和持续定位

本轮重新核对了 ICLR/CVPR 官方论文页面，新增结论只用于调整 Smart Shadow 的实验优先级：

| 一手来源 | 直接观察 | 对 Smart Shadow 的具体动作 | 边界 |
| --- | --- | --- | --- |
| [No Pixel Left Behind / HiDA-Net，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/820e42f39773c6cbbd875553db45658f-Abstract-Conference.html) | 论文指出把高分辨率图片统一缩放或中心裁剪会丢失局部伪影；HiDA-Net 用全分辨率局部 tile + 全局视图聚合，并加入 token 级定位和 JPEG 质量估计。 | 将 Smart Shadow 的区域网格从固定六块扩展为“全局 + 覆盖式 tile”对照；质量估计必须作为传播条件和审计字段，不能作为 AIGC 概率。 | HiRes-50K 和论文模型结果不能替代授权图库；tile 覆盖也不能解决原件误配或未知生成器。 |
| [Detective SAM，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/262dd62fd1bbb30d6a6b4d578f5e65ff-Abstract-Conference.html) | 论文把扰动取证线索转成 SAM2 mask，并用 AutoEditForge 生成新编辑样本；作者明确指出新编辑器会令定位系统崩溃，少量新样本可恢复性能。 | 设计“慢速复核 + 新编辑器小样本适配”路径：只更新新版本 prototype/router/calibration，旧评测集冻结并做遗忘回归；不把自动生成样本当客户真实性证据。 | 其适配依赖编辑器样本和训练预算；500 个样本的恢复结果不能推出 Smart Shadow 的真实覆盖率。 |
| [Detecting Compressed AI-Generated Images via Phase Spectrum Robustness，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Li_Detecting_Compressed_AI-Generated_Images_via_Phase_Spectrum_Robustness_CVPR_2026_paper.html) | 论文将相位谱作为压缩下较稳定的取证流，并讨论压缩伪影会同时破坏生成痕迹、制造误导信号；方法可在没有完整原图—压缩配对时训练。 | 在传播矩阵加入 phase-spectrum stream，与现有 residual/quality/counterfactual 做流级消融；显式区分“压缩鲁棒”与“跨生成器鲁棒”。 | 论文的压缩设置不能证明截图、打印扫描、神经压缩或局部编辑场景；仍需独立校准和拒判。 |
| [All in One: Unifying Deepfake Detection, Tampering Localization, and Source Tracing with a Robust Landmark-Identity Watermark，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Wu_All_in_One_Unifying_Deepfake_Detection_Tampering_Localization_and_Source_CVPR_2026_paper.html) | 论文在受控人脸场景把主动 watermark、定位和来源追踪联合起来，强调主动取证和被动检测的职责不同。 | 将主动 watermark 作为合作生成器/红队通道，独立报告 watermark 验证覆盖率、密钥与版本、篡改定位和 passive evidence；冲突时进入复核。 | 该工作聚焦人脸和受控 watermark，不能外推为一般图片的来源证明；水印缺失不能推出人类创作。 |

这轮复核把下一项可证伪创新收敛为：**PC-SCFT 的区域 delta 不直接过阈值，而是用同传播族普通变换的 group-wise null 做质量条件的保守 conformal 校准，再由覆盖率、坐标帧一致性和开放集门共同决定是否拒判。** 这样可检验的主张是“在登记原件且传播族可覆盖的子集降低 selective risk/误报”，不是“解决所有 AIGC”。

### 10.8 2026 年正式页面补充：跨模态、零样本和证据可迁移性

以下来源均已核对会议/出版社页面。它们用于更新 Smart Shadow 的对照实验和边界，不把外部 benchmark 数字写成项目结果。

| 一手来源 | 等级 | 直接证据 | 对 Smart Shadow 的具体动作 | 不可推出 |
| --- | --- | --- | --- | --- |
| [Cross-modal Representation Learning for Diffusion-generated Image Detection，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Gong_Cross-modal_Representation_Learning_for_Diffusion-generated_Image_Detection_CVPR_2026_paper.html) | A | 将 RGB 与 neighboring-pixel-relationship（NPR）两种输入放入 Cross-Modal Contrastive Learning（CMCL）和 Cross-Modal Mutual Distillation（CMMD），目标是学习更偏取证的表征；在 GenImage、DRCT-2M、Co-Spy-Bench 上报告跨数据集实验。 | 在 A2 中加入 RGB、NPR/SRM/DCT 和 source-residual 三路流级消融，分别报告已知、未见生成器和传播变换的 coverage-risk、ECE、P95；检验低层流是否与 PC-SCFT 的原件差分互补。 | 跨模态表征提升不等于来源绑定、区域归因或法律证据；公开数据上的结果不能迁移到客户授权图库。 |
| [General and Domain-Specific Zero-shot Detection of Generated Images via Conditional Likelihood（CLIDE），WACV 2026](https://openaccess.thecvf.com/content/WACV2026/html/Betser_General_and_Domain-Specific_Zero-shot_Detection_of_Generated_Images_via_Conditional_WACV_2026_paper.html) | A | 用条件似然近似，把待测图与真实图条件关系用于零样本检测，并专门评估艺术等域；论文主张无需持续维护完整生成器标签集即可做域适配。 | 作为“无登记原件时”的单图回退基线，与静态 A0/A1 和 PPM-CLIP 并列；增加艺术/数字绘画/扫描件域切分，报告 unknown rate、风险覆盖曲线和跨域校准，而非只报告 closed-set AUC。 | 零样本检测仍是被动模型证据，不能替代 C2PA/水印或登记原件；域适配实验不证明未知生成器的概率保证。 |
| [All in One: Unifying Deepfake Detection, Tampering Localization, and Source Tracing with a Robust Landmark-Identity Watermark，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Wu_All_in_One_Unifying_Deepfake_Detection_Tampering_Localization_and_Source_CVPR2026_paper.html) | A | 在受控人脸场景设计 152 维 landmark-identity watermark 和 factorized-head decoder，同时做检测、篡改定位与来源追踪；这是主动取证通道而非纯被动检测。 | 将其作为主动水印边界对照：单独记录 watermark 验证率、定位 IoU、密钥/版本和篡改冲突；只有在合作生成器中才考虑接入，不混入通用图片 detector。 | 人脸专用、受控密钥和主动嵌入不能推出一般图片来源证明；水印缺失或被移除不能推出人类创作。 |
| [Diffusion Probe: Generated Image Result Prediction Using CNN Probes，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Huang_Diffusion_Probe_Generated_Image_Result_Prediction_Using_CNN_Probes_CVPR_2026_paper.html) | A | 从扩散早期 cross-attention 的统计特征预测最终生成质量，论文报告跨 SDXL、FLUX、Qwen-Image 和多种质量指标的早期相关性；它预测生成质量，不判断图片来源真实性。 | 如果项目未来控制生成流程，可把它作为“生成前质量门/主动采样”记录；在被动取证中只作质量协变量，不能把 probe 分数当 AI 判定或把低质量样本静默丢弃。 | 生成过程内部信号对用户上传图片不可得；质量预测与 AIGC 检测、版权风险和来源权属是不同任务。 |
| [ForensicConcept: Transferable Forensic Concepts for AIGI Detection，ICML 2026 论文清单；方法页面为预印本](https://icml.cc/Downloads/2026) | B/C | ICML 2026 官方下载清单列出该论文；公开摘要描述从 attribution 选出的关键 patch 聚类为可审计 concept codebook，以 CleanDIFT generation trace 和 CKNNA 评估跨 backbone 可迁移性。当前可直接核验的全文仍是 arXiv 版本。 | 将“概念级证据”作为解释审计对照：从 PC-SCFT/低层分数生成 evidence regions，做 mask-out faithfulness、跨 backbone 稳定性和人工复核时间；概念分支不得覆盖原始 raw evidence。 | 官方清单本身不提供完整实验细节；预印本结果不能当作正式项目效果。可迁移概念也不等于来源证明或开放集安全保证。 |

这组来源进一步把 Smart Shadow 的创新边界收敛成四层职责：

1. **被动取证表征层**：RGB/NPR、频域、残差和多尺度区域，回答“哪些视觉证据与检测相关”；
2. **来源条件层**：登记原件、同传播族反事实、区域配准和质量校准，回答“相对该来源发生了什么变化”；
3. **主动来源层**：C2PA、合作生成器 watermark 和版本链，回答“声明是否绑定并可复核”；
4. **审计决策层**：概念/区域解释、开放集拒判和人工复核，回答“证据是否足够提交结论”。

后续实验不得用第一层的 AUC 代替第二层的 ROI/反事实指标，也不得用第三层的凭证阳性代替图像事实判断。最有希望形成项目独立贡献的仍是 **登记原件 + 同传播族无编辑反事实 + 区域配准 + 质量条件校准 + 可审计拒判** 的组合；其学术新颖性必须由 A0–A8 和 E1–E5 消融结果决定。

### 10.9 本轮新增的四个可迁移对照：局部场景、置信拒判、归因检索和自适应复核

本节只补充前文尚未展开的方法细节。它们改变的是实验协议和代码边界，不是 Smart Shadow 已取得的效果。

| 一手来源 | 直接方法和数据证据 | 可证伪实验 | 建议代码切片 | 不可推出 |
| --- | --- | --- | --- | --- |
| [Zooming In on Fakes: BR-Gen/NFA-ViT，AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/37240) | BR-Gen 有 150,000 张局部生成图，专门补足 object 之外的 stuff/background 场景，并用语义校准的自动 Perception–Creation–Evaluation 流程生成 mask。NFA-ViT 从噪声指纹挖掘异质区域，再通过正常/异常区域注意力传播弱局部痕迹。 | 在 `object / stuff / background` 三层分别测 PC-SCFT ROI IoU、boundary-F、hard-negative 激活率和 `source_match_failure`；要求普通天空/地面替换、裁剪、JPEG 与 AI 局部编辑分开，验证六区域 CLIP 是否把背景差异误报为编辑。 | 新增 `region_type`、`edit_mask_digest` 和 `semantic_source` 到 manifest 校验；写只读的 BR-Gen adapter/评测 runner，先输出 mask 对齐和分层统计，不把公开数据直接混入客户图库。 | BR-Gen 的公开合成分布不代表客户作品；NFA-ViT 的定位提升不能证明来源绑定、版权侵权或未知生成器开放集安全。 |
| [Exploiting the Source-Asymmetry Confidence Gap（SACG），CVPR 2026 Findings](https://openaccess.thecvf.com/content/CVPR2026F/html/Zheng_Exploiting_the_Source-Asymmetry_Confidence_Gap_for_Generalizable_AI-Generated_Image_Detection_CVPRF_2026_paper.html) | 观察到训练中真实图来源多样而伪造图只来自少数生成器，导致未见真实/伪造的置信度分离。SACG 用 GEN score 放大该差距，并用只依赖真实图的条件决策规则做后验校准；官方摘要在 Community Forensics 的 21 个生成模型上评估。 | 做 `real_only` 校准与 temperature/Platt/isotonic、负例 conformal 的并列消融；严格按作者/生成器/时间切分，报告 unknown rate、coverage-risk、FPR@TPR95 和在未见生成器上的校准漂移。关键反事实是：只用真实校准是否会在高质量 AI 图上产生过度自信；若不能控制风险，必须退回 `unknown`。 | 在 `aigc/calibration.py` 增加版本化 `RealOnlyConfidenceProfile`（detector、score schema、真实校准 manifest digest、operating point），输出 `calibrated_observation` 而非直接四态；与 `NegativeConformalProfile` 并列，禁止覆盖原始分数。 | 只用真实集校准不是概率保证，也不能把高真实置信度转成人类创作；论文 benchmark 的生成器集合和阈值不能迁移到本项目。 |
| [Attribution as Retrieval: Model-Agnostic AI-Generated Image Attribution（LIDA），CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Wang_Attribution_as_Retrieval_Model-Agnostic_AI-Generated_Image_Attribution_CVPR_2026_paper.html) | 将生成器归因改写为实例检索而非固定分类；Low-Bit Fingerprint Generation 生成输入，先无监督预训练，再做 few-shot attribution adaptation。官方补充在 WildFake 按 1/5/10-shot 和 diffusion/GAN/other 家族报告 Rank-1、mAP，并评估未见生成器。 | 用 `generator_hypotheses` 做独立检索头，比较 1/5/10-shot 与 zero-shot 的 Recall@K、mAP、OSCR、unknown recall 和旧类遗忘；将 source CID 检索和 generator attribution 分开，测试生成器候选错误时 PC-SCFT 是否仍能拒判。 | 新增 `aigc/generator_attribution.py` 的低比特/频域 fingerprint adapter 和 prototype index；输出候选及距离、支持集 digest、`attribution_status`，不改变 `aigc_status`。先用合成 fingerprint fixture 验证 schema，再接授权生成器样本。 | 生成器归因不是 AIGC 真实性、作品来源或侵权结论；WildFake 的家族标签和 few-shot 结果不能支持商业图库的开放集概率。 |
| [MIRAGE / MIRAGE-R1，AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/37421) | MIRAGE 同时包含人工核验的网络 AIGI、与真实图来自相同在线语境的样本，以及多生成器协作和后处理的 composite pipeline。MIRAGE-R1 将 heuristic-to-analytic reasoning、反思纠错和 inference-time adaptive thinking 结合，按快速印象的置信度决定是否进入慢速复核。 | 把它映射为有限预算的证据获取实验：比较只跑 L1 detector、低置信样本触发 L2/VLM/重建、固定全量 L2 三条路径的 risk-coverage-cost；另做 explanation faithfulness 和人工一次复核时间，验证“自适应思考”是否真的减少成本而不放大错误。 | 扩展 `aigc/evidence_budget.py`：预算、触发阈值、每次操作哈希/耗时/失败原因和 profile 版本写入 evidence chain；慢速模型只能产生补充 raw evidence，不能直接覆盖四态或静默改变校准。 | MIRAGE 的 VLM 和数据筛选可能含平台/模型偏差；自适应推理不是拒判保证，外部 SOTA 数字不能转成 Smart Shadow 的准确率或部署 SLA。 |

四个对照共同支持的实现顺序是：先补 `region_type` 和局部 mask 分层，再加真实集后验校准，随后做独立生成器归因，最后把慢速 VLM/重建接到预算化证据链。每一步都要保留原始分数、校准身份、数据摘要和失败原因；任何对照若只改善 closed-set AUC 而不改善 unknown/ROI/成本指标，不得升级为项目创新。

### 10.10 Patch coverage 与四篇 ICLR 2026 工作的直接对应

新增的 `aigc/patch_coverage.py` 不是一个新的 AIGC 分类器，而是把区域 delta 的**空间形状**作为后续路由证据。它与下面四篇工作的关系应写成“研究启发 → 项目可证伪假设”，不能写成已经复现论文方法：

| 一手来源 | 外部启发 | 对 Smart Shadow 的可检验映射 | 当前边界 |
| --- | --- | --- | --- |
| [Panoptic Patch Learning，ICLR 2026](https://openreview.net/pdf?id=ob7PJs8kPU) | 论文指出检测器可能产生 `few-patch bias`，分布更广的 patch 证据更有利于跨生成器稳健性。 | `coverage_raw`、`effective_patch_ratio_raw` 和 `concentration_raw` 用来区分分布式与集中式正 delta；`global_like` 只路由到全图复核，不能直接当作整图 AI 结论。后续应做 patch mask-out、patch 数量和来源匹配失败率消融。 | 当前只有 5 个标量 fixture；没有真实 patch artifact mask、跨生成器或 mask-out 效果。 |
| [No Pixel Left Behind / HiDA-Net，ICLR 2026](https://openreview.net/pdf/d3bd6393bdc32d6878e6d07aaceb1bbf5a6451cf.pdf) | 全分辨率 local tile 与 global view 聚合，结合 token 级定位和 JPEG 质量估计，针对缩放/中心裁剪丢失局部伪影的问题。 | 将 `global_like/localized_like` 作为“全图 tile 路径/ROI 路径”的实验路由；把质量门与传播条件一起记录，并比较固定六区域、覆盖式 tile、全图缩放三种输入。 | 当前区域来自 NumPy 配准和标量 delta，不是 HiDA-Net；质量分数不是 AIGC 概率，也没有高分辨率真实图片评测。 |
| [X-AIGD，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/65b4e84b66ed049f8066919a803e3942-Abstract-Conference.html) | 提供像素级、类别化伪影标注，并显示分类器注意力与可感知伪影可能不一致。 | `localized_like` 后续必须接 `edit_mask_digest`、`region_type` 和 artifact category，报告 ROI IoU/Dice、类别 macro-F1 与 mask-out faithfulness；解释层只能引用原始 evidence regions。 | 当前 patch coverage 没有 artifact category 或人工 mask，只输出 raw routing；不能宣称可解释 AIGC 检测。 |
| [DACOM，ICLR 2026](https://openreview.net/pdf/9a9ad3cc252735dcd9be4a445b8f7f984d73a689.pdf) | 失真会使 detector raw logit 失去样本级置信含义；失真感知置信度可支持筛选、融合和 abstention，但跨数据集仍会退化。 | 将 `quality_score`、传播族、detector/schema 和拒判原因作为路由条件；比较 raw threshold、质量条件校准和 group-wise conformal 的 risk-coverage-cost，验证低质量样本是否更容易进入 `abstained`。 | 当前质量和来源门只是协议默认值；没有真实传播失真、校准集或 coverage guarantee，不能把 `weighted_quality_raw` 命名为 confidence/probability。 |

因此，`global_like`/`localized_like` 的研究假设分别是“证据覆盖足够广，值得走全图复核”和“正证据集中，值得优先看 ROI”；`ambiguous`/`abstained` 则是“证据形状或质量不足，停止自动升级”。四种状态都不等于 `human_supported`、`ai_generated_supported` 或 `ai_edited_supported`，只有真实授权数据、独立校准和 A0–A8/E1–E5 评测通过后，才能讨论是否形成项目创新。

### 10.11 下一轮应优先实现的五个对照支路

这五项用于比较 PC-SCFT 的边界，不改变当前“原始证据与四态结论分离”的决策：

| 一手来源 | 可复用方法 | 建议代码切片 | 必须验证的指标 | 不可推出 |
| --- | --- | --- | --- | --- |
| [EditTrack，arXiv/ICLR 2026 under review](https://arxiv.org/abs/2510.01173) | 用 base image、疑似编辑图和 re-edit consistency 判断是否同源，并进一步归因编辑模型。 | `aigc/re_edit_probe.py`、`eval/re_edit_probe_eval.py`；只输出 re-edit raw evidence。 | 0/1/5-shot、已知/未见编辑模型、普通传播 hard negative、unknown rate、P95。 | 预印本方法不能作为已证实创新；重编辑一致性不是来源或侵权证明。 |
| [X-Edit，CVPRW 2025](https://www.openaccess.thecvf.com/content/CVPR2025W/XAI4CV/papers/Bazyleva_X-Edit_Detecting_and_Localizing_Edits_in_Images_Altered_by_Text-Guided_CVPR2025W_XAI4CV_paper.pdf) | 原图—编辑图成对检测、Stable Diffusion inversion discrepancy 和局部 mask。 | 建立 `source/query/edit_mask/edit_model/edit_type` paired adapter，与 source-residual、inversion discrepancy、PC-SCFT 比较。 | ROI IoU、Dice、boundary-F、source-match failure、JPEG/resize/screenshot 后的 abstain。 | 外部 paired 数据不等于客户授权图库；定位结果不说明权利归属。 |
| [DACOM，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/482847908fd916b5b6b9e82525c773ad-Abstract-Conference.html) | 用失真类型、质量和 detector 特征估计“当前样本是否可检测”，支持 selective filtering 和路由。 | 增加独立 `detectability_profile`；与 raw threshold、质量条件校准、group-wise conformal 做 risk-coverage-cost 对照。 | 分 JPEG/resize/截图的 coverage-risk、unknown rate、P95、每千张成本和误报复核分钟。 | detectability confidence 不是 AIGC 概率，也不能把低分直接翻译成人类创作。 |
| [Beyond Generation，CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Zhong_Beyond_Generation_A_Diffusion-based_Low-level_Feature_Extractor_for_Detecting_AI-generated_CVPR2025_paper.html) | 用扩散去噪预训练提取真实照片低层流形，做 one-class deviation。 | `aigc/real_manifold_profile.py`；输出 real-null distance/OOD evidence，与 `NegativeConformalProfile` 和 real-only calibration 并列。 | 时间/生成器/传播切分、unknown/coverage-risk、真实流形误拒率。 | 落在真实流形内不等于人类创作；one-class 距离不是法律证据。 |
| [SPAI，CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Karageorgiou_Any-Resolution_AI-Generated_Image_Detection_by_Spectral_Learning_CVPR2025.html) | masked spectral learning 和 spectral reconstruction similarity，面向任意分辨率与传播扰动。 | 低成本 `spectral_recon_stream`，与 phase-spectrum、SRM/DCT、source-residual 做流级消融。 | 按尺寸、压缩、局部编辑分层的 AUROC、ECE、unknown、P95。 | 频谱证据仍是被动信号，不能证明来源、作者或侵权。 |

优先顺序应是 **X-Edit/PC-SCFT 成对定位 → DACOM 可检测性拒判 → real-manifold one-class → spectral stream**。如果新增支路只提升 closed-set AUC，却没有降低有原件子集的 selective risk、改善 ROI 或控制成本，就保留为对照，不升级为项目创新。

### 10.12 先做重合排除，再做最小创新主张

本轮 prior-art 复核后的判断是，PC-SCFT 不能把已有单项组件重新命名为新算法：X-Edit 已覆盖原图—编辑图成对定位，EditTrack 覆盖 re-edit consistency 和编辑模型归因，Difference-in-Difference 覆盖二阶重建差分，DICE 覆盖变化与指令一致性分离，QuAD 覆盖近重复质量条件聚合，DACOM 覆盖失真感知的 selective abstention，BR-Gen/NFA-ViT 覆盖 `object/stuff/background` 局部痕迹。因而当前可辩护的最小主张只能写成一个 **source-conditioned evidence test**：

```text
同一登记资产 + 同一传播变换 g
→ query 与无编辑 counterfactual 成对观察
→ 同一坐标帧的区域配准
→ 质量条件的区域 delta
→ 传播族/质量分层 null 的保守校准
→ coverage/quality/source-match 不足时 abstain
```

这仍是待证研究假设。真实授权数据必须按以下门推进，不能跳过合成 runner 直接声称效果：

| 门 | 最小证据 | 必须记录的结果 |
| --- | --- | --- |
| G0 | `source/query/edit_mask/edit_type`、传播链、质量、生成器家族、时间、C2PA/水印状态和 decoder/model/schema digest；同组不跨 split | manifest、权限、身份和数据许可审计 |
| G1 | 同源 JPEG、resize、crop、blur、截图、再拍摄和神经压缩等 paired counterfactual | 分传播族 null、FPR 及 95% CI |
| G2 | 授权 human edit 与至少三类生成器的 inpaint/outpaint/img2img/upscale，带 mask 和 lineage | ROI IoU/Dice/boundary-F、source-match failure |
| G3 | 相似但非同源参考、无原件、低质量、元数据冲突和未见生成器 | coverage-risk、unknown rate、拒判原因 |
| G4 | 冻结 operating point 后的分层测试 | FPR、漂移、P95、每千张成本和证据包完整率 |
| G5 | A0/A1 基线、低层支路、X-Edit/inversion、Difference-in-Difference、QuAD/DACOM 及去掉 counterfactual/quality/ROI 的消融 | 只有同时改善 selective risk/ROI/成本才保留为主线 |
| G6 | 复核人员使用真实证据包的流程验收 | 一次复核率、人工分钟、回放成功率和上线回滚条件 |

如果收益只存在于“高质量登记原件 + 局部编辑”子集，论文和产品表述必须限定为 `source-conditioned local edit forensics`；没有原件或质量不足时 coverage 可以下降，但 `unknown/abstained` 必须上升，不能强行归类为人类创作。

当前已将这条最小主张落成离线协议 `aigc/pc_scft.py`：它把区域质量/来源/覆盖门、paired-delta null 校准和 patch 形状门组合成 `candidate_edit`、`null_consistent`、`review`、`insufficient` 四种 raw-evidence 路由。该实现只证明证据组合契约和可回放 digest；真实图片、跨生成器、ROI、FPR、coverage-risk 和人工复核收益仍未验证。

### 10.13 2026-09 外部刷新：现代局部编辑、持续适配与主动探针的边界

本轮把 2026 年较新的公开工作加入研究边界。它们进一步说明“训练一个更大的二分类器”不能作为 Smart Shadow 的创新结论：

| 一手来源 | 新增约束 | 对 A0–A10 的动作 | 不可推出 |
| --- | --- | --- | --- |
| [DailyBench，arXiv 2607.24016](https://arxiv.org/abs/2607.24016) | FakeBench 与对象级 ManipulationBench 显示，GenImage 上的高分在现代商业/局部编辑测试会明显下降。 | A1/A7 增加现代生成器和 object-level image-conditional edit；区分全图、局部、同源和非同源参考。 | 外部 benchmark 数字不能当 Smart Shadow 真实准确率。 |
| [Test-Time Curriculum，arXiv 2608.00559](https://arxiv.org/abs/2608.00559) | 开放集测试时自训练、伪标签和跨尺度 refinement 已覆盖静态 detector → 适配器路径。 | A10 只能做 shadow-mode 版本化 prototype/router/calibration，并做旧集回归、回滚和遗忘测试。 | 不能把持续适配写成已解决未知生成器。 |
| [Progressive Decision-Making for Localizing Open-Ended AI-Generated Image Forgeries](https://arxiv.org/abs/2607.29156) | 不确定性/边界引导的顺序区域更新已覆盖“自适应定位”单项。 | A9 与 static one-pass、全量 probe、Progressive-DM 对比；Smart Shadow 的差异收窄为原件条件、同传播族反事实、成本约束和可回放 evidence chain。 | “顺序看更多区域”本身不是独立创新。 |
| [Detective SAM，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/262dd62fd1bbb30d6a6b4d578f5e65ff-Abstract-Conference.html) | evidence→mask 和少量新编辑器适配已被覆盖。 | A8/A10 把新编辑器小样本适配作为定位/遗忘对照，保持旧 profile 不可静默重算。 | 少量适配结果不能推出真实开放集覆盖率。 |
| [Diversity over Uniformity，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/He_Diversity_over_Uniformity_Rethinking_Representation_in_Generated_Image_Detection_CVPR2026_paper.html) | 特征坍缩和伪影冗余会限制跨生成器泛化；多流简单拼接不足以证明互补。 | A2 做语义/频域/残差流的相关性、feature/cue redundancy 和 patch-mask-out 消融。 | 多流 AUC 提升不能推出 source-conditioned ROI 有效。 |
| [IncreFA，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Qin_IncreFA_Breaking_the_Static_Wall_of_Generative_Model_Attribution_CVPRF_2026_paper.html) 与 [LIDA，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Wang_Attribution_as_Retrieval_Model-Agnostic_AI-Generated_Image_Attribution_CVPR2026_paper.html) | 时间序列生成器归因、latent memory 和 few-shot fingerprint retrieval 已有公开先例。 | A5/A10 把 `generator_hypotheses` 做独立检索头，报告 Recall@K、unknown recall、旧类遗忘和支持集 digest；不改变 `aigc_status`。 | 生成器归因不是 AIGC 真实性、作品来源或侵权结论。 |
| [NIST GenAI Image Discriminators Evaluation Plan](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=959543) | 评测计划要求冻结测试期间的 detector，并报告 confidence/Brier 等不确定性指标。 | A0–A8 冻结模型和 profile；A10 单独 shadow-mode；增加 ECE/Brier、risk@coverage，不能只报 AUROC。 | NIST 计划是评测约束，不证明任何项目模型效果。 |

因此，本项目当前最小可辩护创新主张进一步收窄为：**在已登记原件和同传播族无编辑反事实可用时，使用坐标帧区域差分、质量/传播族 null 校准、语义区域形状门和限预算可回放 probe，把局部编辑候选路由到人工复核；其他情况主动拒判。** `aigc/evidence_budget.py`、`aigc/sequential_evidence.py` 和 `aigc/policy_calibration.py` 已实现离线工程原语；执行器对真实模型、授权策略回放和 risk-coverage-cost 仍未验证。

### 10.14 G1 字节级普通传播生成器

`aigc/propagation_transforms.py` 把 G1 从“标量 fixture 中声明同一传播族”推进为可回放的图片字节变换。第一版支持 `identity`、JPEG 重编码、resize、center crop、blur、screenshot simulation 和有限步数的 composite；source/query 由同一个 `TransformSpec` 生成，并分别记录父哈希、输出哈希、格式、尺寸、参数摘要、操作链、Pillow 版本和配置摘要。

它的研究作用是生成 ordinary-propagation null 和 hard negative，帮助校准“传播本身造成的局部激活”；它不生成 AI 编辑、不验证 C2PA、不判断来源，也不输出 AIGC 状态。`eval/propagation_transform_eval.py` 和对应契约测试只证明合成输入的确定性、配对和 fail-closed 行为。真实传播链、打印/扫描/再拍摄、授权 manifest 和跨生成器效果仍必须通过 G1–G6 后续门。

### 10.15 2026 年论文刷新：哪些方向值得接入，哪些不能当成解决方案

这轮只采用正式会议或组织方页面，结论用于改变实验设计和代码优先级，不把论文结果外推为 Smart Shadow 效果。

| 来源 | 直接结论 | 对 Smart Shadow 的动作 | 不可外推 |
| --- | --- | --- | --- |
| [AIGIBench，NeurIPS 2025](https://papers.neurips.cc/paper_files/paper/2025/hash/fb693c67f61e5321746ffce8b6fdd2d0-Abstract-Datasets_and_Benchmarks_Track.html) | 23 个 fake 子集覆盖多来源、退化、增强和社交/AI 平台野外样本；受控高分在真实条件明显下降。 | 把 multi-source、degradation、test-time preprocessing 和 `temporal_next_period` 设为发布门；禁止只报 IID AUC。 | benchmark 数字不能作为本项目模型效果。 |
| [Phase Spectrum Robustness，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Li_Detecting_Compressed_AI-Generated_Images_via_Phase_Spectrum_Robustness_CVPR2026_paper.html) | 相位谱在压缩下更稳定，可在不依赖原图/压缩配对的情况下增强压缩鲁棒性。 | 作为低层 phase stream 对照，与 source-residual、DCT/SRM 分开做压缩分层和流级消融。 | 压缩鲁棒不等于未知生成器、局部编辑或来源鲁棒。 |
| [No Pixel Left Behind / HiDA-Net，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/820e42f39773c6cbbd875553db45658f-Abstract-Conference.html) | 全分辨率 local tiles + global view，结合 token 定位和 JPEG 质量估计，减少中心裁剪丢失局部线索。 | 将固定六区域、覆盖式 tile、全图缩放列为 A2/A3 对照；质量估计只作为 detectability gate。 | 高分辨率 benchmark 不能证明客户图片或线上 P95。 |
| [SAIDO，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/papers/Hu_SAIDO_Generalizable_Detection_of_AI-Generated_Images_via_Scene-Aware_and_Importance-Guided_CVPR2026_paper.pdf) | 通过场景专家和重要性引导的持续学习处理已知/未见生成器的稳定性与可塑性。 | A10 只在 shadow mode 更新 scene/prototype/router；冻结旧 profile，做新类收益、旧类遗忘和回滚测试。 | 论文的开放世界提升不能转成自动在线更新或通用保证。 |
| [Detective SAM，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/262dd62fd1bbb30d6a6b4d578f5e65ff-Abstract-Conference.html) | 将 forensic clue 转成 mask，并用约 500 个新编辑器样本恢复定位性能；新编辑器会使旧定位器崩溃。 | 增加 editor-drift slice：新编辑器少样本适配、旧类回归、ROI/遗忘和证据 mask 回放。 | 少样本恢复不能证明开放集覆盖率或商业安全。 |
| [FakeXplain，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/701ec28790b29a5bc33832b7bdc4c3b6-Abstract-Conference.html) | 用人工对齐框和描述训练 grounded artifact explanation。 | 解释只作为 evidence sidecar；增加 mask-out/faithfulness 和人工复核一致性，不让生成式文字覆盖 raw evidence。 | 语言解释可能幻觉，不能作为来源或侵权证明。 |
| [Ignoring the Decoy，WACV 2026 Workshop](https://openaccess.thecvf.com/content/WACV2026W/SynRDinBAS/html/Staelens_Ignoring_the_Decoy_Exposing_and_Tackling_Forensic_Distractions_in_Image_WACVW_2026_paper.html) | 无关但强烈的 forensic distraction 会显著破坏定位；掩蔽干扰可恢复部分性能。 | 对 PC-SCFT 增加 distraction/decoy hard negatives、mask-out 和 ROI 稳定性测试，避免把背景压缩纹理当编辑证据。 | 外部定位提升不证明源图条件协议有效。 |
| [Leveraging Arbitrary Data Sources，CVPR Findings 2026](https://openaccess.thecvf.com/content/CVPR2026F/html/He_Leveraging_Arbitrary_Data_Sources_for_AI-Generated_Image_Detection_Without_Sacrificing_CVPRF_2026_paper.html) | 单类 attribution space 可减少对特定生成器的依赖，支持 real-only 或 generated-only 训练协议。 | 加入 real-only、generated-only、mixed-source 与 source-conditioned 的校准对照；记录数据来源而非只记录二分类标签。 | 单类边界仍需时间/传播/开放集验证，不能把拒绝单类当作人类证明。 |

这些论文共同把“解决 AIGC”改写为四个可验证目标：

1. 在 `H0=普通传播`、`H1=局部 AI 编辑`、`H2=未知/证据不足` 三种状态间保持可审计的拒判边界；
2. 用登记原件和同传播族 counterfactual 估计传播激活，把 content、propagation 和 edit evidence 尽量分离；
3. 以质量、传播族和语义区域类型为条件做校准，报告 risk-coverage、FPR、ROI 和成本，而不把 raw score 叫概率；
4. 用 shadow-mode 持续适配应对新编辑器，但历史 profile 不静默重算，任何新模型必须可回滚。

因此下一阶段的研究优先级不是再堆一个闭集分类器，而是：**真实图片契约与 raw adapter → phase/tile/质量对照 → patch-level ROI 与 distraction 红队 → 独立开放集校准 → 新编辑器小样本适配**。只有当 PC-SCFT 相对 A0–A3 同时改善局部 ROI、selective risk 和人工证据包复核效率，才有资格把它称为项目创新；否则保持为可审计的研究协议。

### 10.16 2026-09 研究刷新：来源不对称、生成指纹、相机端恢复与持续采集

本节补入上一轮尚未进入索引的六个来源。它们均只用于约束对照实验、数据治理和证据分层；外部论文结果不能写成 Smart Shadow 的模型结果。

| 一手来源 | 等级 | 外部方法/证据 | 对 Smart Shadow 的最小可迁移动作 | 不可外推 |
| --- | --- | --- | --- | --- |
| [Exploiting the Source-Asymmetry Confidence Gap for Generalizable AI-Generated Image Detection（SACG），CVPR Findings 2026](https://openaccess.thecvf.com/content/CVPR2026F/html/Zheng_Exploiting_the_Source-Asymmetry_Confidence_Gap_for_Generalizable_AI-Generated_Image_Detection_CVPRF_2026_paper.html) | B | 论文指出训练真实图往往来自多源，而假图来自少量生成器；提出 GEN score 和仅用真实集校准的条件决策，在 Community Forensics 的 21 个生成模型上评估。 | 作为无原件 fallback 的 `real_only` 校准对照，与温度/Platt/isotonic、负例 conformal 并列；按生成器、时间和传播条件报告 unknown rate、coverage-risk、ECE/Brier。 | 真实集后验校准不是概率保证；高真实置信度不能译为人类创作；Community Forensics 的生成器集合和阈值不能迁移到客户图库。 |
| [ReAlign: Generalizable Image Forgery Detection via Reasoning-Aligned Representation，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Huang_ReAlign_Generalizable_Image_Forgery_Detection_via_Reasoning-Aligned_Representation_CVPR_2026_paper.html) | A | 用 GRPO 优化的多模态模型生成伪影解释文本，再用图像—文本对比学习将推理语义蒸馏到轻量 detector。 | 只作为慢速解释/候选排序或训练辅助；对 reasoning text、caption、label-only、pixel-only 做消融，并以 mask-out、counterfactual swap 检验解释是否依赖图像证据。 | 解释文本可能复制数据集偏差；跨域 accuracy 不证明解释因果性、开放集保证、来源绑定或法律结论；未核验代码/权重不得作为商业依赖。 |
| [DiffusionPrint: Learning Generative Fingerprints for Diffusion-Based Inpainting Localization，CVPRW 2026](https://openaccess.thecvf.com/content/CVPR2026W/AIMS/html/Giakoumoglou_DiffusionPrint_Learning_Generative_Fingerprints_for_Diffusion-Based_Inpainting_Localization_CVPRW_2026_paper.html)；[arXiv](https://arxiv.org/abs/2604.12443)；[代码](https://github.com/mever-team/diffusionprint) | B | 以 patch 级对比学习和跨类别 hard negatives 学习扩散修补生成器指纹，输出 forensic feature map，并作为 TruFor/MMFusion 等定位器的辅助模态。 | 接入时仅作为 `generator_hypotheses`/区域辅助流；与 source-residual、DCT/phase 和 PC-SCFT delta 做流级消融，显式测参考图误配和普通传播 hard negative 的 ROI 激活。 | 生成器指纹是被动线索，不是来源凭证；未见 mask 或架构上的外部提升不能推出未知生成器开放集保证；代码、权重和数据许可需单独核验。 |
| [Addressing Image Authenticity When Cameras Use Generative AI，CVPRW 2026](https://openaccess.thecvf.com/content/CVPR2026W/APAI/papers/Masud_Addressing_Image_Authenticity_When_Cameras_Use_Generative_AI_CVPRW_2026_paper.pdf)；[arXiv](https://arxiv.org/abs/2604.21879) | B | 针对相机 ISP 在数字变焦/低光增强中的捕获阶段幻觉，使用图像特定 MLP decoder 和 modality encoder 恢复未经过幻觉增强的版本，并可将约 180 KB 参数保存到 JPEG/HEIC 元数据。 | 若有设备协作，新增 `capture_time_recovery_sidecar` 来源证据层；sidecar 缺失、篡改、过期或与图像摘要不匹配必须 `unknown`，恢复图只作为设备过程证据参与回放。 | 该方案依赖设备端中间图和厂商流程；恢复结果不能直接称“真实原图”，不能对普通上传图假设存在 sidecar，也不能替代 C2PA/视觉取证。 |
| [Self-Supervised AI-Generated Image Detection: A Camera Metadata Perspective，TPAMI 2026](https://scholars.cityu.edu.hk/en/publications/self-supervised-ai-generated-image-detection-a-camera-metadata-pe/)；[DOI](https://doi.org/10.1109/TPAMI.2026.3654274)；[官方实现](https://github.com/Ekko-zn/SDAIE) | A | 仅用相机照片的 EXIF 标签做自监督预训练，再以真实照片 GMM 做 one-class 检测，并在高频残差和空间打乱 patch 上做 binary detector；官方页面标注 2026-01-14 online publication。 | 把 EXIF 作为弱域协变量和 real-null profile 条件；做 EXIF 保留/删除/伪造、跨设备、截图和社交平台重编码切分，并报告 real false reject、unknown rate、ECE/Brier。 | EXIF 可丢失或伪造；有 EXIF 不等于真实来源、无 EXIF 不等于 AI；官方实现许可需核验，不能把其 one-class 结果直接作为产品判定。 |
| [Automated In-the-Wild Data Collection for Continual AI Generated Image Detection，MAD '26 / arXiv 2605.02567](https://mever-team.github.io/WildFC/)；[arXiv](https://arxiv.org/abs/2605.02567) | C（论文页面/预印本；项目页列 MAD '26） | 以事实核验文章检索构造弱监督 WildFC，并将野外数据、少量新生成器数据和 replay buffer 做持续适配；项目页列出 2,884 张 WildFC AI 图和 5,439 张来自 19 个近期模型的 AIGenImages2026。 | 仅在 shadow mode 建立版本化的月度/平台/传播 evidence profile；保留 URL、抓取时间、原文证据、人工抽样审计、撤回和许可状态；回放旧版 PC-SCFT 与 hard negatives 后才讨论校准更新。 | 弱标签有来源和版权/平台条款风险；外部数据量和论文平均准确率不能转成项目效果；禁止把未审计野外样本静默写入生产 calibration manifest。 |

这六项共同强化四条边界：`real_only`、EXIF 和 ReAlign 只能是无原件 fallback；DiffusionPrint 只能提供生成器/区域候选；相机端 sidecar 属于主动过程证据；WildFC 只能驱动可回滚的 shadow adaptation。它们都不能取消 PC-SCFT 的同传播族 counterfactual、质量条件 null 和证据不足拒判门。

### 10.17 2026-09 深度刷新：来源条件局部编辑、物理来源与可预算拒判

本节是本轮新增的唯一证据小节。条目均已用会议正式页面、作者项目页或作者预印本复核；它们是 prior art 和实验设计约束，不是 Smart Shadow 的运行结果。与前文已收录的 Detective SAM、HSIC、WildFC、Progressive Decision-Making、Phase Spectrum 和 EXIF 工作不重复。

| 一手来源 | 等级/角色 | 外部证据 | 对 Smart Shadow 的最小可迁移动作 | 不可外推边界 |
| --- | --- | --- | --- | --- |
| [Rethinking Where to Edit: Task-Aware Localization for Instruction-Based Image Editing](https://arxiv.org/abs/2604.20258) | C，作者预印本；局部编辑 prior art | 该工作利用编辑模型内在的 source/target 双流，把 addition、removal、replacement 等操作的定位线索分开，并用任务条件 mask 约束非编辑区域。 | G2/G5 将 `edit_type` 从单一局部编辑标签拆为 add/remove/replace 等操作；分别记录 source-stream、target-stream、双流 union 与 `non_edit_consistency`，作为 PC-SCFT 区域差分的可迁移对照。 | 这是生成器内部编辑控制，不是登记原件取证、来源凭证或未知生成器保证；预印本和伪真值 mask 不能证明项目 ROI 效果。 |
| [GAP-SAM: A Global Artifact Prior for Generalizable AI-Generated Image Manipulation Localization](https://arxiv.org/abs/2608.20929) | C，作者预印本；OOD 定位 prior art | 论文指出局部定位会黏附到语义边界，并用 Canny/depth 条件的 COCO-ControlNet 对齐合成数据，再以全局 artifact token 调制 SAM 解码；报告对压缩、模糊、缩放的分层结果。 | 增加 `semantic_boundary_adhesion`、真实编辑边界与语义边界的偏差，以及 Canny/depth 对齐和普通 Mask-VAE 合成方式的 A8 对照；将 GAP-SAM 作为无原件 OOD localizer，和 source-residual/PC-SCFT 分开测。 | 外部合成数据与六数据集结果不能外推到授权图库；全局 artifact prior 不提供 source match、版权来源或开放集拒判保证。 |
| [RCEdit-500K: Reference Completion for Image-Conditioned Image Editing](https://carpedkm.github.io/RCEdit-500K/) | B，作者/研究机构项目页；参考图数据 prior art | 项目页称 ECCV 2026，构造 477K 个对齐四元组（输入、指令、编辑目标、参考图），覆盖 add/remove/replace/background/style/alter 六类参考图编辑。 | 在 G2 manifest 中增加 `reference_image_digest`、`reference_role` 和 `source_reference_conflict`；把“登记原件”与“编辑参考图”分开，测参考图误配、同源/非同源和 reference-only 对照。 | 数据由自动合成和 VLM 过滤构造，许可、真实用户分布和会议最终版本需单独核验；参考图一致性不能转成来源真实性、作者贡献或侵权结论。 |
| [Look Again Before You Abstain: Budgeted Conformal Evidence Acquisition for Reliable Vision-Language Models](https://arxiv.org/abs/2606.16667) | C，作者预印本；selective/abstention prior art | BCEA 将决策扩为 answer/abstain/acquire，并明确指出把 zoom/crop 等采集直接接到已校准阈值会破坏交换性；必须把完整采集策略纳入分数后重新校准。 | A9 比较 static one-pass、全量 probe 与预算化 acquire；校准集必须复现同一 probe policy，报告 risk@coverage、unknown rate、P95、每千张成本和采集次数，并保留 `policy_digest`。 | 原论文针对 VLM 事实性主张，不是 AIGC/ROI 证明；其有限样本保证不覆盖未授权数据、模型异常或 source-match 失败。 |
| [Zero-shot Detection of AI-Generated Image via RAW-RGB Alignment](https://openaccess.thecvf.com/content/CVPR2026/papers/Wu_Zero-shot_Detection_of_AI-Generated_Image_via_RAW-RGB_Alignment_CVPR_2026_paper.pdf) | A，CVPR 2026；频域/物理来源 prior art | 论文用真实 RAW–RGB 配对学习相机 ISP 产生的 alignment trace，以物理来源一致性做零样本检测，并评估未见生成器；其目标边界是是否来自物理世界，而非记住生成器。 | 另设授权相机子集，保存 RAW/RGB 配对摘要和 ISP 版本；在 print-scan、截图、再编码和纯数字编辑上比较 RAW–RGB、phase/DCT/SRM 与 source-residual，缺 RAW 时明确输出 `unavailable`。 | 需要捕获时 RAW 和相机流程，不能对普通上传图假设存在；再拍摄可给数字图制造物理来源，故不能把 alignment 阳性直接当人类作者或版权来源。 |
| [Data Provenance for Image Auto-Regressive Generation](https://proceedings.iclr.cc/paper_files/paper/2026/hash/5a1667459d0cdeb2fe6b2f0dffc5cb9d-Abstract-Conference.html) | A，ICLR 2026；生成器 provenance prior art | 论文发现自回归图像模型输出即使没有水印也有可用于模型来源追踪的模式，采用后处理框架，不要求改动生成过程或输出。 | `generator_hypotheses` 增加 IAR family 与 diffusion family 的分层支持集；报告 attribution Recall@K、unknown recall、传播后分数漂移和支持集 digest，且不改变四态 `aigc_status`。 | 模型 provenance 不是内容真实性、自然人创作或版权归属；IAR 支持集和外部结果不能覆盖未知架构、局部编辑或项目客户数据。 |
| [Identifying Provenance of Generative Text-to-Image Models](https://www.usenix.org/conference/usenixsecurity26/presentation/ha) | A，USENIX Security 2026；黑盒模型 lineage prior art | 该工作只用黑盒查询，通过输出视觉特征分布、Jensen–Shannon divergence 和统计检验判断模型是从头训练还是由哪个基础模型微调而来，并测试后处理/权重扰动。 | 将“模型 lineage probe”独立于图片 detector：保存 prompt 集、查询预算、参考模型池、JS 距离和假设检验版本；在时间切分中新模型上测 parent/unknown 召回与遗忘，不把 lineage 当图片来源。 | 需要对生成器有查询权限，不能从任意用户图片回溯其生成模型；论文的七个模型和平台样本不能外推到未知商业服务或法律证明。 |
| [Apple Reference Image: A New Approach for Verified Photography](https://security.apple.com/blog/apple-reference-image) | B，厂商官方安全研究；硬件/元数据 provenance prior art | Apple 公开了传感器签名、传感器/设备元数据、上下界时间戳、可验证处理环境、撤销与隐私保护组成的捕获链；它把“相机捕获事实”与后续编辑历史分开。 | EvidenceV1 为主动捕获来源增加 `sensor_signature`、`capture_time_bounds`、`processing_attestation`、`revocation_state`；冲突矩阵中区分设备来源阳性、C2PA、被动取证和缺失/过期 sidecar，缺字段进入 `unknown`。 | 这是 iPhone 18 Pro 的可选闭环，不是通用 C2PA 兼容层或公开 benchmark；硬件来源阳性不等于内容无编辑、自然人创作或版权所有权。 |

这批证据把后续实验进一步收敛为四个可审计动作：一是按编辑操作和 source/target 证据流分层，而不是把所有局部变化压成一个 mask；二是把语义边界黏附、参考图误配和普通传播列为 hard negative；三是任何主动 probe 都必须在完整采集策略上重新校准并受预算约束；四是 RAW、IAR、模型 lineage 和硬件签名都只进入 provenance/候选证据层，不得覆盖 `human_supported`、`ai_generated_supported`、`ai_edited_supported`、`unknown_or_inconclusive` 的状态门。真实授权 manifest、跨生成器/时间切分、传播链和 `docs/07-验证与运行记录.md` 记录完成前，上述条目仍只能改变实验设计，不能升级为项目效果或部署能力。


### 10.18 多流独立证据与冲突拒判：当前可证伪切片

2026-09-20 新增的 `aigc/multistream.py` 把 pixel residual 与 phase/spectral 作为两条独立 raw-evidence 流接到同一个选择性路由边界。该设计受到多视角/互补取证方向的启发，但本身不声称学术新颖性；它的可证伪点是：在同一登记原件和传播族上，双流一致是否比任一单流减少普通传播误报，同时在局部编辑子集提高可复核 ROI，且流冲突时 coverage 下降、unknown/人工复核上升。

每条流必须保留：

```text
score_raw, quality_score, paired,
detector_version, score_schema, config_digest,
input_digests, evidence_digest, region details
```

路由规则固定为：两路达到当前 raw gate 才能 `candidate_edit`；两路均低于 gate 才能 `null_consistent`；高低分 spread 超过配置 margin 进入 `conflict_review`；缺流、未配对、质量不足或样本数不足进入 `insufficient`。后两类强制 abstain，且任何路由都不等于 `human_supported`、`ai_generated_supported`、`ai_edited_supported` 或 `unknown_or_inconclusive`。`null_consistent` 更不能被解释为人类创作。

`eval/multistream_eval.py` 当前只使用 NumPy/标准库及已有 residual/spectral 原语构造四类 synthetic fixture：局部变化、同源普通传播 hard negative、跨流分数冲突和频谱流缺失。runner 输出的 route、raw score、stream digest 和 dataset digest 只证明 sidecar/路由契约可重复，不是 AIGC 准确率、概率、真实图片效果或法律证据。真实授权数据、独立 stream 校准、时间/生成器切分、传播链和 P95 仍未验证。

### 10.19 2026-09 官方会议刷新：真实图回退与视频/多模态扩展边界

本节只加入本轮检索中尚未出现在本文件或外部证据索引的 2026 年正式会议论文。前两项直接约束现有图像算法；后六项主要说明 Smart Shadow 将来向视频、多模态和商业生成器扩展时应怎样设计数据与拒判门。所有外部指标都是 prior art，不能写成 Smart Shadow 的效果。

| 一手来源 | 等级/角色 | 外部方法与直接证据 | 对 PC-SCFT/后续实验的最小迁移动作 | 不可外推边界 |
| --- | --- | --- | --- | --- |
| [RealNet: Efficient and Unsupervised Detection of AI-Generated Images via Real-Only Representation Learning，AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/41234) | A；图像 real-only 回退 | 只用真实图，通过双重对抗去噪得到与语义尽量解耦的表示，再在特征空间生成伪负样本训练轻量判别器；官方摘要明确覆盖 GAN、扩散和 VAR，并把未见生成器泛化作为问题。 | 在无登记原件时加入 `real_only` baseline，与单图 detector、负例 conformal 和 PC-SCFT 分层比较；冻结 real-null profile，报告按生成器/时间/传播条件的 FPR、unknown rate、ECE/Brier 和 risk@coverage。 | “只用真实图训练”仍是被动分布假设，不能证明未知生成器、真实传播或人类创作；外部 accuracy/AP 不能转成项目概率或 SLA。 |
| [Dual-Branch Asymmetric Discrepancy Learning Based on Fake Image Pattern-Coexistence for AI-Generated Image Detection，AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/37071) | A；图像多尺度伪影对照 | 论文提出 synthetic image 同时含真实模式与生成模式的 pattern-coexistence 假设，用双分支、多尺度特征和非对称 discrepancy loss：真实图压低分支差异，假图放大分支差异，并以 DWT/patch 分析验证。 | 增加 `branch_discrepancy_raw` 作为独立对照流；比较它与 pixel residual、phase/spectral、paired counterfactual 的相关性、mask-out 稳定性和普通传播 hard negative；不得把分支差异直接接入四态。 | 论文是闭集二分类，不能证明登记原件匹配、局部编辑来源或开放集拒判；pattern-coexistence 在客户图库和截图链上的稳定性需重新验证。 |
| [Your One-Stop Solution for AI-Generated Video Detection，AIGVDBench，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Ma_Your_One-Stop_Solution_for_AI-Generated_Video_Detection_CVPR_2026_paper.html) | A；视频 benchmark | 官方页面称覆盖 31 个生成模型、超过 440,000 个视频，运行超过 1,500 次评测，包含 33 个检测器、四类方法及多项跨模型分析。 | 作为 P2 视频扩展的数据契约参考：manifest 增加 `frame_digest`、时间区间、帧级/片段级 mask、生成任务和传播链；将图像的 `observed-counterfactual` 推广为同视频同变换的时间配对，并按帧覆盖率与时序稳定性拒判。 | 视频 benchmark 的模型、帧率和内容分布不能外推图像效果；规模和排行榜不证明 Smart Shadow 有视频数据权限、实时能力或跨模态来源证明。 |
| [Skyra: AI-Generated Video Detection via Grounded Artifact Reasoning，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Li_Skyra_AI-Generated_Video_Detection_via_Grounded_Artifact_Reasoning_CVPR_2026_paper.html) | A；视频解释与定位 | 以 ViF-CoT-4K 的人工细粒度时空伪影标注训练 MLLM，采用 SFT+RL；ViF-Bench 包含约 3,000 个由十多个生成器产生的样本，输出伪影类别、时间和空间证据。 | 仅将其证据 sidecar 设计迁移到视频：记录 `temporal_regions`、artifact category、解释与原始 mask 的 faithfulness；比较 L1 轻量 detector、慢速 MLLM 和人工复核的 risk-coverage-cost，语言解释不能改写 raw route。 | MLLM 的语言解释不等于来源证明，视频生成器和人工标注分布不能外推图像；推理成本、伪影偏差和解释幻觉必须单独验收。 |
| [FVBench: Benchmarking Deepfake Video Detection Capability of Large Multimodal Models，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Wang_FVBench_Benchmarking_Deepfake_Video_Detection_Capability_of_Large_Multimodal_Models_CVPR_2026_paper.html) | A；视频开放集/模型评测 | 官方摘要称数据超过 120,000 个视频，覆盖真实、AI 编辑和完整生成，伪造来自 42 个视频合成/编辑模型，并专门评测 LMM 的深伪识别能力。 | 为未来视频/多模态切分增加 `real/partial/full`、已知/未见生成器、编辑任务和 LMM probe 成本；把 LMM 仅作为冲突或低置信的 evidence acquisition，不让零样本回答绕过来源、质量和反事实门。 | LMM 在视频上的零样本表现不能外推图像 AIGC 概率；公开数据与模型权限、许可、时间切分和真实传播均需项目单独冻结。 |
| [SAGA: Source Attribution of Generative AI Videos，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Kundu_SAGA_Source_Attribution_of_Generative_AI_Videos_CVPR_2026_paper.html) | A；视频生成器 lineage 对照 | SAGA 用时空编码器和 hard-negative mining 做五层归因（真实性、生成任务、模型版本、开发团队、具体生成器），并提出可视化 temporal attention signatures；论文摘要报告每类只用约 0.5% 有标签数据的训练策略。 | 将 `generator_hypotheses` 明确成独立 provenance 候选层；在新生成器、同族未见和传播后版本上报告 Recall@K、unknown recall、旧类遗忘和支持集 digest，不能改变 `aigc_status`。 | 生成器 lineage 需要有代表性的支持集，不能从任意用户图片反推真实来源；少量标签结果不能推出开放集保证、版权归属或法律结论。 |
| [CoCoVideo: The High-Quality Commercial-Model-Based Contrastive Benchmark for AI-Generated Video Detection，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Feng_CoCoVideo_The_High-Quality_Commercial-Model-Based_Contrastive_Benchmark_for_AI-Generated_Video_Detection_CVPR_2026_paper.html) | A；商业生成器 hard negative | CoCoVideo-26K 覆盖 13 个商业生成器并提供语义对齐的真实/伪造视频对；CoCoDetect 以 R3D-18 提取时空表示，再由置信门把不确定样本路由给 MLLM 做物理合理性和场景一致性判断。 | 把“商业生成器、语义配对、confidence-gated slow path”列为 P2 视频消融；图像侧只借鉴路由和配对 manifest，比较单流、PC-SCFT、慢速 probe 的 selective risk、成本和拒判率。 | 商业模型数据的许可、去水印和代表性需核验；视频配对/物理合理性不能替代图像登记原件、C2PA 或人工权利链。 |
| [Omni-Fake: Benchmarking Unified Multimodal Social Media Deepfake Detection，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Li_Omni-Fake_Benchmarking_Unified_Multimodal_Social_Media_Deepfake_Detection_CVPR_2026_paper.html) | A；多模态检测/定位/解释 benchmark | 官方摘要称 Omni-Fake-Set 超过 100 万样本、OOD 集超过 10 万，覆盖图像、音频、视频和音视频人像；图像/音频/视频采用 real、partially manipulated、fully synthetic 三元任务并提供空间或时间定位。 | 作为未来多模态 EvidenceV1 的字段参考：分别保存 modality、edit scope、spatial/temporal mask、source evidence 和冲突状态；现阶段只做图像三元 raw-evidence fixture，不把统一 MLLM 当作线上依赖。 | 数据集与 Omni-Fake-R1 尚不能证明跨模态统一泛化；“partial/full”标签也不能替代来源凭证、创作贡献或法律确权，且官方摘要称代码将发布，依赖可用性需再次核验。 |

这批来源把下一步分成两条清晰路线：图像主线先做 RealNet/DADL 的无原件 fallback 对照，但保留 PC-SCFT 的来源条件和拒判边界；视频/多模态只能作为 P2 研究扩展，先冻结时间证据、生成器层级、模态缺失和传播链，再做 selective risk、定位和成本评测。任何“检测器可解释”“生成器可归因”都只是候选 raw evidence，不能自动升级为 `human_supported`、`ai_generated_supported` 或 `ai_edited_supported`。

### 10.20 多流独立 null 校准：把“联合支持”变成可证伪协议

前一节的多流路由仍使用 raw threshold，不能说明两条流的联合支持是否具有统计意义。本轮新增 `aigc/multistream_calibration.py`，将 pixel residual 与 spectral/phase 作为两个独立的 ordinary-propagation null 假设：每条流单独冻结 `StreamNullProfile`，对查询 raw score 计算 ties-inclusive conformal p-value，并记录 profile、detector/schema、null group、transform family 和配置 digest。

默认采用 `alpha / N` 的保守交集门。它把可证伪问题明确为：在同一登记原件、同一传播族和相同质量分层下，双流交集是否相对任一单流降低 ordinary-propagation FPR，同时保持局部编辑 ROI 和可接受 coverage；如果流间冲突增加，系统是否正确转为 `conflict_review` 并接受 coverage 下降。没有足够 null、流缺失、schema 不匹配或质量不足时必须 `insufficient`，不能用另一条流的分数填补。

```text
all stream p_i <= alpha / N       -> candidate_edit
all stream p_i >  alpha / N       -> null_consistent
mixed or borderline p-values      -> conflict_review / abstain
missing, unpaired, poor, mismatch -> insufficient / abstain
```

本节中的“新增 6 项、全量 138 项”是该切片完成时的历史快照；后续曾记录 196 个测试、23 个 runner，当前轻量验证已推进到 321 个测试、35 个 runner，实时数字以 [07-验证与运行记录.md](07-验证与运行记录.md) 为准。

对应的 synthetic runner `eval/multistream_calibration_eval.py` 固定覆盖 `local_edit`、`ordinary_propagation_hard_negative`、`cross_stream_conflict` 和 `missing_spectral_stream`，dataset digest=`63683ed8e11ba44e1597fe9e6f1f6f3cf583004a1a71eb7ead0cb29396771576`。新增 6 项契约测试与全量 138 项测试已通过；该结果只证明有限样本 p-value、profile digest、独立 sidecar 和 fail-closed 路由可回放。

它不是新的 AIGC 分类器，也不是把两个分数平均后的“更高置信度”。真实授权数据门仍要求 G0–G6：冻结普通传播 null、跨生成器/时间切分、流间相关性分析、单流/双流消融、risk-coverage、ROI、P95、成本和人工复核效率。未通过前，`candidate_edit` 只是进入局部编辑复核的候选路线，`null_consistent` 也不表示人类创作。

### 10.21 2026 年图像论文收口：像素去语义、局部定位和目标域校准不能互相替代

本轮重新核验了三条容易被混用的路线。它们分别解决“检测器依赖语义捷径”“伪影是否能被定位”和“目标域阈值漂移”，都不能单独解决 Smart Shadow 的来源条件局部编辑问题。

| 一手来源 | 外部事实 | 对 Smart Shadow 的最小对照 | 不能外推 |
| --- | --- | --- | --- |
| [Beyond Semantic Features: Pixel-level Mapping for Generalized AI-Generated Image Detection，AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/40927) | 论文用 pixel-level mapping 打乱像素值分布，削弱语义捷径，迫使 detector 更多依赖高频生成痕迹；官方摘要报告在 GAN 和 diffusion 跨生成器测试中改善泛化。 | 为单图 fallback 增加 `pixel_mapping` 开关，做原图、mapping、patch shuffle、phase/SRM 与 source-residual 的流级消融；对每种预处理分别保存输入 digest，并在普通传播 hard negative、局部编辑 mask-out、截图/再编码下报告 coverage-risk、ECE 和 ROI 漂移。 | 预处理带来的跨生成器提升不能证明来源绑定或局部编辑定位；mapping 可能损伤细节和配准，不能偷偷作用于 reference 而不记录坐标帧。 |
| [DiffusionFF: A Diffusion-based Framework for Joint Face Forgery Detection and Fine-Grained Artifact Localization，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Peng_DiffusionFF_A_Diffusion-based_Framework_for_Joint_Face_Forgery_Detection_and_Fine-Grained_Artifact_Localization_CVPR_2026_paper.html) | 受控人脸场景使用 detector encoder 与 diffusion artifact decoder 联合生成细粒度定位图，再与语义特征融合；官方页面把定位和检测作为同时任务。 | 只把“粗检测→细化 mask→联合评测”作为区域头设计参考；在 PC-SCFT 中比较 raw residual/phase mask、可选重建 mask 和人工 edit mask 的 pixel AP、mIoU、boundary-F、pointing-game，增加 mask-out 后分数下降的 faithfulness 检查。 | 人脸受控 benchmark、扩散解码器和外部 SOTA 数字不能外推普通图片、登记原件配准或法律证据；定位图不是编辑来源证明。 |
| [Your AI-Generated Image Detector Can Secretly Achieve SOTA Accuracy, If Calibrated，AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/38146) | 论文指出目标域 fake 分布和先验变化会使 logit 阈值系统性偏移，提出只用少量目标域样本学习 scalar logit correction 的 post-hoc calibration，并保持 backbone 冻结。 | 将目标域校准严格放在独立 profile 层：`calibration_id`、校准样本 digest、是否有标签、校准时间窗、旧 profile 回归和回滚版本必须进入 evidence chain；比较未校准、temperature/Platt/isotonic、scalar correction 和 conformal reject 的 risk-coverage、ECE/Brier 与 unknown rate。 | 少量目标样本的校准不提供跨生成器保证；无标签校准不能自动产生人类结论，且目标数据可能含攻击样本或选择偏差。它也不能替代同传播族 counterfactual null。 |

因此新增一个可证伪的 A11 组合对照，但不改变当前路由：

```text
A11 = {pixel_mapping, localization_refinement, target_domain_calibration}
```

A11 只允许作用于相应 raw stream 或其校准 profile。验收必须包含：

1. 预处理一致性：reference、observed、counterfactual 使用同一 mapping/spec；否则固定 `insufficient`，不比较分数。
2. 局部性：整图分数提升不能代替 ROI 改善；报告 mask-out 分数下降、false-positive ROI 激活率和 boundary-F。
3. 时间隔离：校准集在时间/生成器上与测试集隔离；新 profile 不覆盖历史 evidence，漂移触发回滚或 `unknown`。
4. 组合消融：A0 单图、A2 低层流、A8 PC-SCFT、A11 三个因素逐一加入；同时报告成本、P95 和人工一次复核时间。

A11 仍是研究计划。当前仓库没有真实生成器、真实授权图片、目标域校准样本或 DiffusionFF/像素 mapping 模型实现；本节来源只改变实验设计和失败边界，不改变已验证能力。

### 10.22 Patch contribution：把 forensic distraction 变成可证伪的证据质量门

`Ignoring the Decoy` 的直接启发是：强烈但无关的局部模式可能把定位器吸到错误区域；`Panoptic Patch Learning` 关注 few-patch bias；`X-AIGD` 则要求区分感知伪影和可审计伪影区域。Smart Shadow 不把这些工作改写成新的分类器，而是在 PC-SCFT 之后加入 `patch-contribution-audit-v1`：先按 `patch-coverage-v2` 得到基线路由，再逐 patch leave-one-out 和 top-k mask-out，观察证据质量是否在少数 patch 被移除后崩塌。

该切片允许的最小研究主张是：对于 `global_like`，如果单 patch 贡献占比过高、top-k 后保留质量不足或路由翻转，则把样本降为 `distraction_sensitive`/人工复核；对于 `localized_like`，集中证据可以是局部编辑的合理形状，但必须记录崩塌审计，不能把集中度直接解释为编辑来源。它不证明因果归因、编辑者身份或 AIGC 概率。

可证伪实验至少包括：普通传播 hard negatives 中的边界/压缩 decoy、真实 edit mask 内外的 mask-out faithfulness、`object/stuff/background` 支持、未知生成器、时间下一周期和传播扰动。必须报告 top-k 保留质量、route flip、false-positive ROI 激活率、ROI IoU/边界偏差、coverage-risk、P95 和人工复核分钟数；单个 synthetic scalar runner 不能替代这些门。

当前 `eval/patch_contribution_eval.py` 仅覆盖 5 个标量 fixture，digest=`3941c63d151ecf96d9254cb18895dc73b3739f34b8353a1f4a500c33247c969f`。因此该方向目前是 PC-SCFT 的 red-team raw branch，不能单独命名为已证实创新，也不能改变 `aigc_result_v1` 四态边界。

### 10.23 联合 null 校准：比 Bonferroni 更有 power，但必须用 group-matched null 约束

近期 QuAD、AIGIBench、ForensicHub 和多流表征工作共同暴露一个问题：传播质量和流间相关性会让“分数平均”失去可解释性，单一流或固定阈值也会在未知生成器上漂移。Smart Shadow 的研究分支 `joint-stream-null-calibration-v1` 因此只组合**各流已校准的 p-value**，再用同一 ordinary-propagation group 的联合经验 null 做第二层校准。

该分支的可证伪问题是：在同一授权 manifest 上，多个中等但一致的流是否能在不提高普通传播 FPR 的情况下改善 candidate coverage；如果不能，保留 Bonferroni 的更保守结果。必须直接比较：

| 对照 | 目的 |
| --- | --- |
| 单流 conformal | 测量单路 coverage-risk 和未知生成器退化 |
| Bonferroni 交集 | 提供保守控制基线 |
| 联合 null + Cauchy 组合 | 测量依赖感知的 selective power |
| raw score 平均 | 作为容易误用的负面对照 |
| 去掉 counterfactual/质量分层 | 验证来源条件协议的增量 |

候选路由需要联合 calibrated p-value 通过、至少两个流支持、p-value 分歧低、patch contribution 稳定和同传播族配对完整；任何一项失败都进入 `conflict_review` 或 `insufficient`。联合 profile 不提供通用概率保证，必须按普通传播 family、quality、region_type、生成器和时间层报告 policy-level empirical FPR 及置信区间。当前 4 case runner 的 digest 由 `eval/joint_null_calibration_eval.py` 输出，仍不能证明真实 AIGC 效果。

这一分支也收紧创新边界：Cauchy 组合、conformal 校准和多流本身都有 prior art；可讨论的最小组合创新只能是登记原件条件、同传播族 counterfactual、group-matched joint null、patch distraction gate 和可回放证据链共同作用，并通过 A0–A8 与 EditTrack/X-Edit/DICE/QuAD 对照。

### 10.24 A9 顺序主动取证：从动作计划到策略级校准

下一项算法切片不是再添加一个闭集 detector，而是把已有 `evidence_budget` planner 扩展为可回放状态机。每个 probe（来源核验、重对齐、同传播族反事实、局部放大或重复观察）完成后，必须重新计算 PC-SCFT、多流校准和 patch contribution 审计，并保存动作顺序、目标、参数、输入/输出 digest、耗时、失败原因、剩余预算和 `policy_digest`。

BCEA 的方法学警告直接适用于这里：如果根据前一步分数自适应选择下一次 probe，简单 conformal exchangeability 不再自动成立。A9 v1 因此只允许两种可审计做法：固定版本化 action policy，或在独立 ordinary-propagation null 上完整回放并按策略校准。报告必须使用 policy-level empirical FPR 和 95% 置信区间，同时报告 risk@coverage、unknown/review、ROI、P50/P95、每千张成本和人工复核分钟；策略、detector、预处理、schema 或 profile 变化后重新校准。

真实实验要比较 `static one-pass`、`全量 probes` 和 `budgeted sequential policy`，并加入单流、Bonferroni、joint-null、raw score 平均和无 counterfactual/质量分层的消融。探针失败、流冲突、patch distraction、route flip、证据不稳定或 profile/schema 不匹配必须转 `review`/`insufficient`；`candidate_edit` 仍只是局部人工复核候选，`null_consistent` 仍不表示人类创作。当前仓库已实现顺序状态机和合成策略级 FPR/CI runner；真实授权策略回放、真实 FPR、ROI、coverage-risk、P95、成本和部署仍未验证，故 A9 仍属于离线研究工程切片。


### 10.25 2026-09 新增诊断证据：解释、连续编辑链和水印攻击不能混为检测结论

本轮继续核验三类容易被产品文案混用的方向：

| 来源 | 直接启发 | Smart Shadow 的实验约束 | 不能外推 |
| --- | --- | --- | --- |
| [SalArt-VQA，2026 预印本](https://arxiv.org/abs/2606.12671) | 把图像级检测、语义定位、空间 grounding 和证据支持拆开；artifact-free reference 可检验模型是否在没有伪影时仍会编造解释。 | 将 VLM/MLLM 只作为低置信慢速 probe；增加 `artifact_presence`、`evidence_region`、`grounding_supported` 和 `reference_negative` 字段，要求解释区域与 raw mask 的遮挡回归一致。 | 语言解释的高召回不代表定位正确或证据充分，不能覆盖 PC-SCFT 的来源、传播和校准门。 |
| [SEED，2026 预印本](https://arxiv.org/abs/2604.10522) | 将连续深伪表示为逐步操作链，支持顺序 provenance 和证据聚合。 | P2 视频/多模态扩展才引入 `edit_steps[]`、时间区间和每步 digest；图像主线先把版本图中的新增版本、counterfactual 和人工确认分开，不能从最终外观反推完整编辑历史。 | 连续人脸编辑 benchmark 不能证明普通图片来源或法律链；操作链标签必须有真实授权和独立时间切分。 |
| [Attack-Resistant Watermarking，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/51e2aaa731e8a5edfbda95fd8bd8948b-Abstract-Conference.html) | 水印验证、攻击检测和语义级定位可以联合设计，但它们依赖密钥、覆盖和攻击模型。 | 在 provenance sidecar 保存 `watermark_status`、攻击迹象、密钥/验证版本和与 pixel/phase/PC-SCFT 的冲突；水印阳性可提高复核优先级，缺失或被移除必须进入 unknown/review。 | 水印阳性不证明版权归属，缺失不证明人类创作；外部攻击成功率不能外推项目鲁棒性。 |

这三类证据把创新方向进一步收紧为“有依据的选择性取证”：视觉检测负责 raw signal，区域/版本图负责来源绑定，VLM 解释负责复核辅助，水印负责可验证来源信号；任一层缺失或冲突都不能被另一层静默补齐。A9 的策略级校准必须把这些慢速 probe 的 action、失败和成本纳入回放，否则解释或水印探针本身也会引入选择偏差。

### 10.26 2026-09-20 一手论文刷新：把“检测 AIGC”收敛为三条可证伪算法路线

本节只纳入会议正式页面、官方 proceedings 或论文全文。它们用来重新划分 prior art、项目已有原语和可辩护的组合创新；外部论文的准确率、数据量和阈值不是 Smart Shadow 的实验结果。

| 一手来源 | 已有 prior art 的边界 | 对 Smart Shadow 的最小可迁移动作 | 不能外推 |
| --- | --- | --- | --- |
| [DeCLIP，WACV 2025](https://openaccess.thecvf.com/content/WACV2025/html/Smeu_DeCLIP_Decoding_CLIP_Representations_for_Deepfake_Localization_WACV_2025_paper.html) | 用自监督/CLIP 表征和卷积解码器定位局部操纵，并报告对未见生成器的泛化；说明“CLIP + mask”本身不是新颖性。 | 保留 CLIP 为语义对齐和检索基线；比较 query-only、reference/query residual 和三元 counterfactual residual 的 ROI 及 mask-out faithfulness。 | 论文使用 Dolos 等外部数据，不能证明登记原件匹配、普通传播 null 或项目四态路由。 |
| [LOTA，ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/papers/Wang_LOTA_Bit-Planes_Guided_AI-Generated_Image_Detection_ICCV2025_paper.pdf) | 从低位平面生成噪声图，以最大梯度 patch 选取和轻量分类头做低成本检测；“再加一个频域/噪声支路”不是新颖性。 | 将 `bit_plane_raw` 作为 L1 独立流，与 phase、SRM、DCT、source-residual 分开校准；记录位深、色彩空间、输入 digest、P50/P95 和传播后分数漂移。 | ICCV/GenImage 结果不能外推局部编辑、未知生成器、截图/再拍摄或授权图库；低位平面容易被量化/重编码破坏。 |
| [Detecting Generated Images by Fitting Natural Image Distributions，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/2cfa9b0d9be8a5c01cf3eb7f21b4f2b8-Abstract-Conference.html) | 把生成图看作自然图分布的 OOD，以 ID energy/流模型放大流形差异，支持只用真实数据的泛化假设。 | 无原件时增加 `natural_manifold_energy` fallback；只输出 raw/OOD 证据和拒判观察，与 SACG real-only 校准、负例 conformal 并列，不替代 PC-SCFT。 | “只用真实图”不等于未知生成器保证，也不能把低 energy 或高置信度译成“人类创作”。 |
| [Breaking Latent Prior Bias，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/2c2be72635379ec8600eea13df4743e3-Abstract-Conference.html) | OMAT 在扩散 latent 上生成仍位于生成器流形的 hard negatives，并以 GenImage++ 测试新生成器；说明像素级扰动会制造不真实的训练捷径。 | 在有 latent 访问权的训练/研究集内加入 `on_manifold_hard_negative`，冻结测试集和校准集；比较普通 augmentation、pixel attack、OMAT 和 source-conditioned 分支。 | 需要生成器 latent/条件访问；OMAT 训练提升不能证明商业黑盒、局部编辑或真实传播上的开放集覆盖。 |
| [ForensicHub，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/5d8a47fc1cb0a143f149ee07321621c9-Abstract-Datasets_and_Benchmarks_Track.html) | 以可组合 adapter、数据集、变换、模型和评估器统一四类图像取证任务；说明可复现评测基础设施本身已有先例。 | 将 Smart Shadow 的 manifest、transform、detector、calibration 和 evaluator 固定为版本化 adapter；同一记录同时产出图像级、ROI、selective-risk、成本指标。 | 外部 benchmark 的跨域数字不能转为项目效果；adapter 统一不解决授权、来源匹配或法律边界。 |
| [NeuroRenderedFake，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/56bdf726a96d43ee1e66172d14c63a61-Abstract-Datasets_and_Benchmarks_Track.html) | 将 NeRF、3D Gaussian Splatting 等神经渲染纳入生成图检测，并专门分析跨域和频谱退化；提示“GAN/扩散之外”的未知生成族不能忽略。 | 在时间/生成器切分中增加 `neural_rendering` 与 `hybrid_rendering` family；把 phase/bit-plane/source-residual 的 family-wise risk 单独报告。 | 外部数据分布与项目图片不一致；神经渲染 family 的结果不能证明对任意未知生成器或客户传播链有效。 |

#### 10.26.1 路线一：Source-Conditioned Triadic Evidence（SCTE）

**问题定义。** 当存在登记原件 `r` 时，不再问“`q` 是否像 AI 图”，而问“`q` 相对 `r` 的局部差异，是否超过同一传播族普通变换的差异”。为每个已配准区域 `i` 保存：

```text
e_obs_i  = d(q_i, r_i)                         # 观察到的 query/reference 差异
e_null_i = d(c_i, r_i),  c ~ ordinary-propagation(r)  # 同族普通传播差异
e_edit_i = e_obs_i - Q_{0.95}(e_null_i | quality, region_type, transform_family)
```

再把 `e_edit_i` 与 patch contribution、semantic-boundary overlap、reference-match quality 和传播链 digest 一起送入已校准的区域路由。只有配对完整、null profile 可用、至少两个独立流支持且 mask-out 后证据仍稳定时，才允许 `candidate_edit`；其他情况进入 `review`/`insufficient`。这把已有 `source-residual`、PC-SCFT、普通传播变换、联合 null 和 patch audit 组成一个可回放协议，但不把任一组件包装成新算法。

**可证伪实验。** 至少比较四个版本：A0 query-only、A1 reference/query residual、A2 A1 去掉 ordinary-propagation null、A3 SCTE 完整协议。数据必须包含授权 reference/query 对、真实或经许可的局部编辑 mask、同源普通传播 hard negatives、reference mis-match、截图/再编码/再拍摄和按生成器/时间隔离的测试。预注册指标：ordinary-propagation FPR 及置信区间、risk@coverage、unknown/review 率、ROI IoU/Dice/boundary-F、mask-out score drop、false-positive ROI 激活率、P50/P95、每千张成本和人工复核分钟。若 A3 只提高 raw AUROC、不能降低普通传播 FPR，或 mask-out/时间切分失效，就撤回“来源条件局部取证”创新主张。

**与 prior art 的差异。** X-Edit、DeCLIP、DICE 已覆盖成对编辑检测、CLIP 定位或变化一致性；QuAD 覆盖质量条件聚合；本项目可辩护的最小主张是登记原件、同传播族 counterfactual、分组 null 校准、patch distraction gate 和可回放拒判在同一坐标帧中共同工作。必须把“共同协议有增量”作为假设，以 A0–A2 和外部 prior-art adapter 证伪，不能把差分、CLIP 或局部 mask 单独称为创新。

#### 10.26.2 路线二：Open-World Natural-Manifold + On-Manifold Adaptation（ONMA）

**问题定义。** 无登记原件时，采用自然图流形 energy/real-only profile 作为保守 fallback；有 latent 访问权的研究生成器只用于构造 on-manifold hard negative；新生成器到来时仅更新独立 prototype/router/calibration profile，并保留旧 profile 可回滚。SACG 的 real-only confidence gap、自然流形 energy 和 OMAT 可作为三个独立 prior-art 对照，不能混成一个“万能 detector”。

**训练/适配数据。** `real_authorized` 只用于自然流形与负例校准；`known_generator_latent` 用于 OMAT hard negative；`unknown_black_box`、`neural_rendering`、商业模型和下一时间窗只进入冻结测试；真实传播变换在每个 split 内成对生成，不得把测试变换拿去调阈值。每次增量适配保存 `support_manifest_digest`、`prototype_version`、`calibration_id`、旧 profile 回归和回滚点。

**可证伪实验。** 并列比较 real-only energy、普通二分类器、OMAT、SACG-style real-only calibration、prototype/few-shot update 和全量重训。分别报告已知/未见/商业黑盒/神经渲染/时间下一窗的 AUROC/PR-AUC（仅描述性）、FPR@固定覆盖、risk@coverage、unknown recall、ECE/Brier、旧 family 遗忘、P95 与成本。若少样本更新只改善已见新 family、污染历史校准、提高普通传播 FPR，或更新后无法回滚，则保留为运维实验，不称为开放世界创新；任何 real-only 高置信仍不能输出 `human_supported`。

**最小新增价值。** 该路线的可辩护点是“自然流形拒判 + 生成器流形 hard negative + 版本化小样本适配”在来源缺失场景下的联合控制面，而非重新发明 energy、OMAT 或 prototype。它与 SCTE 解耦：SCTE 解决有原件的局部变化，ONMA 只负责无原件的保守回退。

#### 10.26.3 路线三：Budgeted Multi-View Evidence Acquisition（BMEA）

**问题定义。** 让系统先用低成本 `bit_plane/phase` 流，只有在证据冲突或质量不足时才获取 source-conditioned residual、重建、VLM/RAW-RGB 等慢速证据。每个动作、失败、输出 digest、成本和 policy digest 都进入状态机，并在同一 ordinary-propagation null 上完整回放校准。多流保持独立 p-value，不做未经校准的 raw-score 平均。

**固定策略示例。**

```text
L1: bit_plane + phase, quality gate
L2: source-match + SCTE residual + patch audit
L3: reconstruction / VLM / RAW-RGB only when L1/L2 conflict or low margin
route: candidate_edit / null_consistent / review / insufficient
```

**可证伪实验。** 比较 one-pass、全量 probes 和预算化 BMEA；校准集必须复现完整 action policy。指标包括 policy-level empirical FPR 及 Wilson CI、risk@coverage、unknown/review、route flip、probe failure、ROI、P50/P95、每千张成本和人工复核分钟。必须注入重复/乱序动作、缺失输出、schema/profile mismatch、普通传播 decoy 和模型不可用；任一错误不得静默补分。若预算策略只是降低 coverage 或把失败样本丢掉才显示“更准”，则撤回算法收益并保留静态 one-pass。

**最小新增价值。** 主动取证和 selective prediction 已有先例；本项目能主张的只是把预算策略、来源条件三元对照、多流联合 null、patch distraction 和版本化回放合在一个受控协议中，并证明它在相同人工复核预算下提高有效候选或减少普通传播误报。A9 当前 synthetic FPR/CI 只证明状态机契约，尚不支持该主张。

#### 10.26.4 选择顺序和停止条件

建议先做 SCTE（路线一），因为它直接复用项目登记原件和现有 raw 原语；随后以 ONMA 作为无原件 fallback，最后把 BMEA 作为成本/复核优化层。三条路线共用一份冻结 manifest，但训练、校准和测试必须按 reference、generator family、时间和传播链隔离。只有在同一授权数据上相对 A0–A2 改善 selective risk、ROI/faithfulness 和人工复核效率，且没有普通传播 FPR、未知 family risk 或 profile 漂移的代价，才允许在 README 或论文中写“研究创新”；否则只记录为 prior-art 对照或工程协议。

#### 10.26.5 工程落地：区域级 conformal/BH 选择器

为把 SCTE 的“区域路由”从单一最大 delta 推进到可审计的候选集合，本轮新增 `aigc/regional_fdr.py`。它按 `transform_family × quality_bucket × region_id × region_type` 建立 ordinary-propagation null，使用 ties-inclusive 有限样本 p-value，再以固定 q-value 做 BH 选择，保留每个区域的 p/q value、null count、stratum key 和 digest。`candidate_regions` 只表示人工 ROI 复核候选；缺失区域 null、质量/来源匹配不足、detector/schema 不匹配或 profile/config digest 不一致都进入 `insufficient`。

该选择器借鉴 conformalized multiple testing 的“选择单位并控制错误发现比例”思路，但当前只实现经验 BH 研究协议，未证明真实区域 p-value 的交换性、空间相关性或选择后 FDR。`eval/regional_fdr_eval.py` 的 24 组标量 null 只覆盖局部候选、普通传播一致和负 delta；真实实验必须与 max statistic、Bonferroni、joint-null、无 counterfactual 和无质量分层做同 manifest 对照，并报告 empirical FDR、risk@coverage、ROI IoU、route flip、P95 和人工复核分钟。该切片不能单独宣称解决 AIGC。

### 10.27 2025–2026 官方页面补充：区域复核、失真可检测性和 provenance 归因的重合审计

本节只增加本轮重新核验、且尚未在前文以同一证据用途收录的正式会议/出版社页面。论文指标仍是 prior art；Smart Shadow 只能迁移实验设计和边界，不能把外部结果写成项目效果。

| 一手来源 | 等级 | 外部事实 | 对 Smart Shadow 的最小可迁移动作 | 不能外推 |
| --- | --- | --- | --- | --- |
| [Locate-Then-Examine: Grounded Region Reasoning Improves Detection of AI-Generated Images，CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/papers/Ji_Locate-Then-Examine_Grounded_Region_Reasoning_Improves_Detection_of_AI-Generated_Images_CVPR_2026_paper.pdf) | A | LTE 先定位可疑区域，再把局部 crop 与全图交给 VLM 复核；TRACE 提供区域标注和解释，目标是让判断与像素区域绑定。 | 把 VLM/区域复核限定为 BMEA 的 L3 慢速 probe；记录 `proposal_mask_digest`、crop 参数、原图/局部两次分数、解释与 mask-out 结果，并与 PC-SCFT ROI 交叉验证。 | TRACE 的自动解释、VLM 准确率和外部 benchmark 不能证明登记原件匹配、来源真实性、局部编辑因果或法律结论；解释文字不能覆盖 raw evidence。 |
| [Enabling Your Forensic Detector Know How Well It Performs on Distorted Samples，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/482847908fd916b5b6b9e82525c773ad-Abstract-Conference.html) | A | DACOM 定义 detector distortion-aware confidence，利用质量/失真类型和 detector 中间特征估计“当前输入是否可检测”，并据此做选择性拒判和多 detector 路由。 | 为每个 detector/传播 profile 增加 `detectability_profile`；在相同完整策略下比较 raw threshold、质量条件 calibration、DACOM 风格 confidence 和 group-wise conformal 的 risk-coverage-cost；校准集必须包含截图、再编码、resize 和复合链。 | 可检测性置信度不是 AIGC 概率或人类创作证据；论文的失真关系不能外推到项目传播族，缺少独立校准时仍必须 `unknown_or_inconclusive`。 |
| [Know When to Abstain: Optimal Selective Classification with Likelihood Ratios，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/3fe2a777282299ecb4f9e7ebb531f0ab-Abstract-Conference.html) | A | 从 Neyman–Pearson 似然比重新推导选择函数，并在 covariate shift 下评估 selective classification。 | 把 likelihood-ratio selector 作为 conformal/BH 和固定 margin 的统计对照；按 `quality_bucket × transform_family × generator_family` 分层报告 coverage-risk、unknown rate、FPR 和校准漂移。 | 该工作没有提供 source/query 配对、空间相关区域 FDR 或 AIGC provenance；似然比模型在项目上必须独立估计并验证，不能直接声称最优。 |
| [Is It Certainly a Deepfake? Reliability Analysis in Detection & Generation Ecosystem，ICCV 2025 Workshop](https://openaccess.thecvf.com/content/ICCV2025W/STREAM/html/Kose_Is_It_Certainly_a_Deepfake_Reliability_Analysis_in_Detection__ICCVW_2025_paper.html) | B | 对 aleatoric/epistemic uncertainty、generator/detector 留一、校准和像素/区域不确定性做系统分析，并输出 uncertainty map。 | 为 ONMA 与 BMEA 保存 detector ensemble/MC dropout 配置（若采用）、区域不确定性摘要和 generator leave-one-out 结果；不确定性只影响路由和复核优先级。 | workshop 结果与人脸/公开生成器分布不能外推 Smart Shadow；不确定性高/低都不能单独证明 AI、人类或来源，且 MC dropout 不是正式校准保证。 |
| [Region-Level Data Attribution for Text-to-Image Generative Models，ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/papers/Nguyen_Region-Level_Data_Attribution_for_Text-to-Image_Generative_Models_ICCV_2025_paper.pdf) | A | AR detector 试图定位训练图像中影响生成对象的区域，并以 Recall@K/InverseRank@K 和区域 IoU 评估“训练数据影响归因”。 | 将 EvidenceV1 的 `nearest_reference`、`model_provenance_hypothesis`、`license_evidence` 三层分开；若未来接入有模型侧日志的生成器，单独建立训练区域归因 manifest，不把版权检索近邻当训练来源。 | 论文使用特定生成器和合成数据；训练数据影响归因需要模型/数据侧可验证信息，不能由 query/reference 相似度、PC-SCFT delta 或链上登记单独推出侵权。 |
| [Watermark-based Attribution of AI-Generated Content，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/ad77a15531fbccefa8be5e434b4b7908-Abstract-Conference.html) | A | 研究为每个 GenAI 用户分配唯一水印，并从内容中恢复用户级归因；理论和实验证明归因继承底层水印的准确率与后处理鲁棒性。 | 将 provenance schema 拆为 `generator_binding` 与 `user_binding`；只有受信任平台、密钥和验证服务提供 user-level binding 时才记录候选用户，视觉 detector、PC-SCFT 和 C2PA 不得伪造用户归因。 | 用户水印归因不等于图片真实性、自然人创作、版权归属或侵权责任；JPEG/黑盒攻击下的外部鲁棒性不能外推到客户水印，水印缺失不能推出人类创作。 |
| [InvisMark: Invisible and Robust Watermarking for AI-Generated Image Provenance，WACV 2025](https://openaccess.thecvf.com/content/WACV2025/html/Xu_InvisMark_Invisible_and_Robust_Watermarking_for_AI-Generated_Image_Provenance_WACV2025_paper.html) | A | 面向高分辨率 AI 图像的不可见水印，强调较大 payload、UUID/纠错码和多种图像操纵下的验证鲁棒性，并讨论攻击缓解。 | 作为合作生成器的 active-provenance adapter 对照；保存 `watermark_scheme`、key/verifier 版本、payload digest、攻击/失败状态，与 C2PA 和 passive evidence 分开计分。 | 外部 PSNR/SSIM/bit accuracy 不是项目结果；水印仅绑定受支持生成链，水印被移除、未嵌入或密钥不可验证时必须进入 unknown/review。 |
| [Your Text Encoder Can Be An Object-Level Watermarking Controller，ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Devulapally_Your_Text_Encoder_Can_Be_An_Object-Level_Watermarking_Controller_ICCV2025_paper.html) | A | 通过文本伪 token 与 cross-attention，在扩散生成时选择性地给对象/局部区域加水印，说明主动 provenance 也可以是区域级而非整图级。 | 若有生成平台合作，记录 `watermark_region_mask_digest`，把区域水印和 PC-SCFT 的 ROI 做冲突/一致性审计；局部阳性只提高来源复核优先级。 | 该方法依赖可控扩散生成端，不能检测任意既有图片；区域水印阳性不证明该区域没有后续编辑、作者贡献或版权归属。 |
| [Generalization-Preserved Learning: Closing the Backdoor to Catastrophic Forgetting in Continual Deepfake Detection，ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Zhang_Generalization-Preserved_Learning_Closing_the_Backdoor_to_Catastrophic_Forgetting_in_Continual_ICCV2025_paper.html) | A | GPL 以超曲面对齐和梯度投影处理连续检测中的稳定性/可塑性冲突，强调新伪造加入后减少遗忘且无需保存历史原图。 | 为 ONMA 的版本化适配增加 `adaptation_profile_digest`、旧 family 回归、梯度/参数变更摘要和回滚点；比较 prototype/router/calibration 轻量更新与完整重训。 | 论文聚焦视频/人脸 deepfake 数据和既定增量序列，不能推出图像 AIGC、局部编辑、传播鲁棒或 Smart Shadow 可在线自动更新；“无需历史图”也不等于无需审计 manifest。 |

#### 10.27.1 路线重合与最小可辩护主张

本轮核验后，四个项目路线的重合风险应明确写入评测设计：

1. **SCTE 与 PC-SCFT**：PC-SCFT 是当前成对/三元 source-conditioned 协议的总称；SCTE 只是把 `reference + query + ordinary-propagation counterfactual` 明确成三元证据和区域 null。不能把“差分”“原图对照”或“局部定位”各自重新命名成独立创新。与 X-Edit、DICE、LTE、Region-Level Data Attribution 的区别只可能来自登记原件、同传播族 null、质量分层和拒判共同验证。
2. **ONMA 与已有 open-world/continual 工作**：自然流形 energy、real-only calibration、OMAT、single-class attribution、GPL/HSIC 和 prototype attribution 都已有先例。ONMA 的最小主张只能是“无原件 fallback + latent hard-negative（有权限时）+ 版本化小样本适配 + 旧 profile 回归/回滚”的运维协议；不能声称重新发明开放集 detector。
3. **BMEA 与 DACOM/选择性预测**：DACOM 已覆盖失真可检测性和 detector 路由，likelihood-ratio selective classification 已覆盖 covariate-shift 下 abstain，QuAD 已覆盖质量条件聚合。BMEA 只有在完整 probe policy、预算、失败状态、策略级重新校准和证据回放同时纳入，并在同一 ordinary-propagation null 上降低人工复核成本/误报时，才有组合创新空间；不能把“按需调用慢模型”单独称为新算法。
4. **来源/水印与四态输出**：C2PA、InvisMark、对象级水印和用户级水印归因覆盖主动 provenance 的不同粒度；IAR provenance/LIDA/IncreFA 覆盖模型来源候选。Smart Shadow 必须把 `generator_binding`、`user_binding`、`training_data_influence` 和 passive visual evidence 分层保存，任何一层都不能覆盖 `unknown_or_inconclusive` 或生成法律结论。

因此，下一轮只保留一个组合假设供真实数据证伪：**在登记原件且传播族可覆盖的样本上，SCTE/PC-SCFT 的区域证据经 DACOM 风格 detectability gate、group-matched conformal/BH 和 BMEA 完整策略校准后，是否比 A0/A1/A2 降低 ordinary-propagation FPR 与 selective risk，并在相同人工复核预算下保持 ROI/faithfulness；在无原件或未知生成器上，ONMA 是否能提高拒判质量而不把阴性翻译成人类。**任一条件失败，回退到 raw evidence/人工复核，不升级为“解决 AIGC”。

### 10.28 2024–2026 一手来源刷新：水印压力测试、反取证与非扩散 provenance

本节补充本轮通过会议/出版社官方页面核验的来源。它们专门检验当前三条路线没有覆盖的失败面：主动水印会不会被移除、扩散模型会不会抹掉被动取证痕迹，以及非扩散的自回归生成是否需要独立 provenance 适配器。论文中的数据、数字和代码均是外部证据，不是 Smart Shadow 的运行结果。

| 一手来源 | 等级 | 论文问题与方法 | 外部证据 | 对 Smart Shadow 的可迁移设计 | 不能外推 |
| --- | --- | --- | --- | --- | --- |
| [DiffForensics: Leveraging Diffusion Prior to Image Forgery Detection and Localization，CVPR 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Yu_DiffForensics_Leveraging_Diffusion_Prior_to_Image_Forgery_Detection_and_Localization_CVPR_2024_paper.html) | A | 针对图像篡改检测与定位，以扩散去噪的自监督先验分离宏观/微观表征，再用 Edge Cue Enhancement Module 强化篡改边界。 | 官方摘要报告其在多个公开篡改数据集上同时改善检测、定位、泛化和鲁棒性。 | 把“mesoscopic/edge”作为 PC-SCFT 的独立语义边界流；在同一 reference/query/反事实配对上比较 edge、频谱、residual 的增量，并记录 ROI IoU、boundary-F 和 mask-out faithfulness。 | 外部篡改数据不含项目登记原件、普通传播 null 或四态路由；方法提升不能推出 AIGC 来源、未知生成器或法律结论。 |
| [Diffusion Models Meet Image Counter-Forensics，WACV 2024](https://openaccess.thecvf.com/content/WACV2024/html/Tailanian_Diffusion_Models_Meet_Image_Counter-Forensics_WACV_2024_paper.html) | A | 研究扩散 purification 如何抹除篡改留下的自然图像痕迹，以欺骗检测器，同时保持较自然的视觉外观。 | 官方页面明确把 diffusion purification 作为 counter-forensics，并报告其相对既有方法更能欺骗取证器。 | 将 diffusion purification、再生成、去噪重绘列为红队传播族；对每一条 evidence 流记录 route flip、分数漂移、unknown/review 和恢复失败，不把 residual 阴性当成人类证据。 | 反取证攻击结果不能说明所有扩散模型都能成功移除痕迹；项目尚无真实攻击、真实图片或攻击者能力假设，不能宣称鲁棒。 |
| [RAW: A Robust and Agile Plug-and-Play Watermark Framework for AI-Generated Images with Provable Guarantees，NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/ee62ab636066cf45a27246acca9545b7-Abstract.html)；[作者代码入口](https://github.com/jeremyxianx/RAWatermark) | A | 设计可在原图数据上注入的可学习水印和联合分类器，支持训练后按需注入，并用 smoothing 给出对抗移除下的误报率保证。 | NeurIPS 官方摘要说明兼容多种生成架构，并在多种扩散模型与攻击上评测；官方仓库还明确区分图像误报保证与视频支持范围。 | 仅在合作生成器/登记时启用 active-watermark adapter；保存 scheme、key/verifier、payload digest、注入时点和验证失败原因，把水印 p-value 与被动 evidence 分开。 | 论文保证依赖已部署的水印和验证器；不能检测未嵌入内容，不能从水印缺失推出人类创作，也不能把外部误报率当项目保证。 |
| [Attack-Resilient Image Watermarking Using Stable Diffusion (ZoDiac)，NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/file/43d33182360378d5c8e69dd706c24f2f-Paper-Conference.pdf)；[作者代码](https://github.com/zhanglijun95/ZoDiac) | A | 用预训练 Stable Diffusion 在 latent 空间为已有真实/生成图片注入水印，再通过 inversion 在 latent 中检测，目标是抵抗扩散式移除攻击。 | 官方论文在 MS-COCO、DiffusionDB、WikiArt 上报告 WDR>98%、FPR<6.4% 的外部结果，并讨论组合攻击。 | 可作为“已登记原件主动加固”对照：分别测 watermark-only、PC-SCFT-only 和冲突融合；水印检测需进入 provenance layer，而不改写 `aigc_status`。 | 这些数字来自外部受控 benchmark；latent 依赖、密钥和攻击模型不能外推客户图片、未知生成器、截图/再拍摄或法律所有权。 |
| [A Technical Report on “Erasing the Invisible”: the 2024 NeurIPS Competition on Stress Testing Image Watermarks，NeurIPS 2025 Datasets and Benchmarks](https://proceedings.neurips.cc/paper_files/paper/2025/hash/15389039ccef67b6bed9b2df8414400f-Abstract-Datasets_and_Benchmarks_Track.html) | A | 用 black-box 与 beige-box 两条赛道系统压力测试隐形水印移除，建立攻击基准和工具链。 | 官方摘要报告 2,722 次提交、298 个团队，前五名平均可在保持较高视觉质量下移除至少 89% 水印。 | 把 watermark-removal 作为强制红队门；每个合作水印适配器都要报告攻击前后 TPR/FPR、视觉质量、组合攻击、密钥/版本和失败路由，并把“水印可验证覆盖率”作为单独指标。 | 竞赛攻击分布和平均数字不能外推任何客户水印；水印被移除只说明 provenance signal 缺失，不说明图片为人类创作或内容为假。 |
| [Watermarking Autoregressive Image Generation，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/67cef321196556c4f1e17989ed7a8adb-Abstract-Conference.html)；[作者代码 WMar](https://github.com/facebookresearch/wmar) | A | 首次把语言模型式 token-level watermark 引入自回归图像生成，针对 re-tokenization 破坏水印的 reverse cycle-consistency (RCC) 问题，引入 tokenizer-detokenizer 微调和同步层。 | 官方摘要明确覆盖普通变换、神经压缩和移除攻击，并使用理论有依据的 p-values；作者公开代码和模型。 | 在 provenance schema 中新增 `generator_family=autoregressive` 和 token-watermark adapter；按 IAR/diffusion 分层校准 p-value，记录 re-tokenization、神经压缩和重生成的 route flip。 | 只覆盖已控制 tokenization 的生成器；不能把 IAR 水印结果外推到扩散、黑盒服务、无水印内容或自然人创作。 |
| [Data Provenance for Image Auto-Regressive Generation，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/5a1667459d0cdeb2fe6b2f0dffc5cb9d-Abstract-Conference.html) | A | 不修改生成过程或输出，利用 IAR 输出中的生成模式做 post-hoc model provenance，专门处理已发布且没有水印的内容。 | 官方摘要明确指出无需改动生成器或输出，并覆盖多个 IAR；这与已有 diffusion watermark 路径不同。 | 为 ONMA/归因头增加 `iar_posthoc` 分支；支持集、模型家族、时间窗和传播变换必须版本化，输出候选模型与 unknown recall，不进入四态结论。 | 模型来源候选不是内容真实、人类创作、版权归属或训练数据归因；外部 IAR 支持集不能覆盖未知架构、局部编辑和项目客户图库。 |

#### 10.28.1 从这批论文得到的新增约束与最小创新主张

1. **主动 provenance 与被动取证必须分层。** RAW、ZoDiac、WMar 和 IAR post-hoc provenance 解决的是“有可验证生成链时能否追踪”；PC-SCFT/SCTE 解决的是“有登记原件时局部变化是否超过普通传播”。二者只能在冲突矩阵中联合复核，不能用水印阳性替代局部编辑证据，也不能用水印阴性证明人类创作。
2. **水印攻击必须进入主评测，而不是附录。** “Erasing the Invisible”显示高质量移除是可行的红队事实；后续任何 watermark adapter 都必须在攻击前后同时报告覆盖率、误报、视觉质量和 unknown/review，不得只报告无攻击召回。
3. **反取证是 residual 路线的硬负例。** Diffusion purification 提醒单一路径的 residual/边界证据会被主动抹除；真实评测需要加入再生成、去噪重绘和神经压缩，并要求 evidence conflict 或低 detectability 时拒判。
4. **非扩散生成族不能共用默认阈值。** WMar 与 IAR provenance 表明自回归图像的 token 过程和扩散过程不同；`generator_family` 必须进入 profile/calibration 分层，未知 family 只输出候选或 `unknown_or_inconclusive`。

因此，当前可保留的新增组合假设是：**在有登记原件的样本上，把 SCTE/PC-SCFT 的 ordinary-propagation null 与可验证 provenance adapter、反取证红队和 detectability gate 绑定，能否在相同人工复核预算下减少普通传播误报及水印冲突误报；在无原件样本上，IAR/diffusion 分族的 provenance 候选能否提升归因召回而不减少拒判覆盖。**没有跨攻击、跨生成器、跨时间和真实授权数据的结果前，不能写成“解决 AIGC”。

### 10.29 MPCF：matched placebo / negative-control 研究方向

WACV 2026 的 forensic distraction 结果说明，logo、水印、边界和压缩纹理等无害区域可能成为定位器的诱导信号。MPCF 将这个问题写成可审计的控制比较：在 SCTE/PC-SCFT 已获得目标区域 `e_edit` 后，构造同资产、同传播族、同质量桶和同坐标约束下的未编辑或 decoy 区域控制，检验目标是否超过控制分布。

最小统计量为 ties-inclusive finite-sample 上尾 p-value：

```text
p_placebo = (1 + count(control_delta >= max(0, target_delta))) / (n_control + 1)
contrast = target_delta - median(control_delta)
```

MPCF 与已有切片的分工是：ordinary-propagation null 用来回答“传播是否足以解释观察差异”；MPCF 用来回答“同一资产内的匹配负对照是否也产生同样差异”；patch contribution 用来回答“删掉少数高贡献 patch 后证据是否崩塌”。这三个问题不能由一个分数或一个局部 mask 代替。

当前代码 `aigc/mpcf.py` 只提供 raw evidence 契约，控制集合缺失、身份错配、质量/来源门不满足或支持数不足会返回 `insufficient`。合成 runner 的五个 case 只验证 `candidate_edit`、`control_consistent`、identity/quality/support fail-closed 和确定性；它不支持真实 FPR、AIGC 概率或正式 multiple-testing 保证。

真实可证伪对照必须冻结控制构造和污染审计，在同一授权 manifest 上至少比较：

1. PC-SCFT + ordinary-propagation null；
2. PC-SCFT + matched placebo；
3. PC-SCFT + patch contribution mask-out；
4. ordinary null + placebo + patch audit 的联合路由；
5. 去掉 counterfactual 或随机控制的负对照。

每个对照按生成器家族、时间窗、传播链、quality bucket、region type 和 decoy 类型报告 FPR、coverage-risk、unknown/review、ROI/边界 F、route flip、P95 和人工复核分钟数。若控制集与目标共享编辑区域、控制选择依赖目标分数、或 placebo 只在合成数据上有效，则该方向保留为质量审计协议，不称为独立算法创新。

### 10.30 Source-Conditioned Crop-Consensus：多视角区域共识与 crop-null

本切片针对一个具体可证伪问题：PC-SCFT 的局部 observed−counterfactual delta 是否只是某一
个 crop、边界或压缩 patch 的偶然高分。它要求同一登记原件和同一 pair 生成多个 crop view，
把每个 view 的可见区域映射到 canonical coordinate frame，再按质量×source-match 聚合：

```text
每个 crop 的区域 delta
  -> weighted positive-view fraction
  -> 可见区域集合的 pairwise Jaccard overlap
  -> consensus_raw = fraction × overlap
  -> matched ordinary-propagation crop-null 的 ties-inclusive p-value
```

路由只包括 `consensus_candidate`、`null_consistent`、`view_inconsistent` 和
`insufficient`。不可见区域不当作负证据；view/null 必须绑定 asset、pair、manifest、canonical
frame、传播族、detector/schema 和 quality bucket，`CropNullSample` 还校验
`consensus_raw = positive_view_fraction_raw × view_set_overlap_raw`，防止 null scalar 与其
组成部分不一致。所有结果是 raw evidence，不改变 `aigc_result_v1`，也不把
`null_consistent` 翻译为人类创作。

#### 与外部工作的重合边界

| 外部来源 | 已覆盖能力 | Crop-Consensus 保留的可辩护差异 | 仍需验证 |
| --- | --- | --- | --- |
| [WaRPAD，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/1d8f05e4da49a4e1e1b052a3046bceac-Abstract-Conference.html) | 训练无关的裁剪鲁棒检测、Haar 高频扰动、多生成器测试 | source-conditioned paired delta、canonical region-set 共识和 matched ordinary-propagation crop-null | 真实传播 crop、不同 crop policy、已知/未知生成器与编辑 mask |
| [HiDA-Net，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/820e42f39773c6cbbd875553db45658f-Abstract-Conference.html) | tile + global feature aggregation、token-wise localization、JPEG quality estimation | 不提出新 backbone；把多视角一致性作为现有 PC-SCFT 的审计层，并显式保留质量/来源/null 证据 | canonical frame 误差、质量桶漂移、ROI/边界收益和 P95 |
| [RRBench/RRDataset，ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Li_Bridging_the_Gap_Between_Ideal_and_Real-world_Evaluation_Benchmarking_AI-Generated_ICCV2025_paper.html) | 真实社交传播、再数字化、detector/VLM 对照和人机复核协议 | 将 crop view、传播链、质量和 null group 绑定到同一证据包，评测 view-inconsistent 与 ordinary-crop FPR | 平台传播矩阵、截图/再拍摄、跨生成器和人工一次复核分钟 |
| [ADCD-Net，ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Wong_ADCD-Net_Robust_Document_Image_Forgery_Localization_via_Adaptive_DCT_Feature_ICCV2025_paper.html) | 文档篡改定位的 adaptive DCT/alignment 与 resize/crop 鲁棒性 | Crop-Consensus 不把 detector 架构鲁棒性当成协议创新，重点是 reference−counterfactual 与 null p-value | 非文档图像、局部 AI 编辑、source-match 和空间 decoy |
| [Ignoring the Decoy，WACV 2026 Workshop](https://openaccess.thecvf.com/content/WACV2026W/SynRDinBAS/html/Staelens_Ignoring_the_Decoy_Exposing_and_Tackling_Forensic_Distractions_in_Image_Forgery_Localization_using_Masked_Convolutions_WACVW_2026_paper.html) | logo/watermark/边界等 forensic distraction 会诱导定位 | view 共识和 placebo/crop-null 可把“跨视角一致”与“控制也同样高”分开审计 | logo/边界/压缩纹理 decoy、mask-out faithfulness 与真实 FPR |

#### 可证伪评测门

真实授权评测至少冻结：同传播族 ordinary crop-null（G1）、至少三类生成器的局部 edit mask（G2）、
未知生成器/参考误配/低覆盖 crop/logo decoy（G3）。同一 manifest 上比较单视图 PC-SCFT、简单 mean/max crop、
WaRPAD 风格 crop aggregate、去掉 canonical binding、去掉 crop-null 和完整 Crop-Consensus，报告
ordinary-crop FPR 及置信区间、ROI IoU/Dice/boundary-F、coverage-risk、unknown/view_inconsistent、
P95 和每样本成本。只有“区域共识 + matched crop-null”相对单视图提升且没有以放宽拒判门为代价，
才可讨论组合协议的研究增量；当前 runner 的 3 个 scalar case 和 digest=`0693139527b8c08901e3baef91412cb4ba09acc59dcf10e0fe959381faedab8c`
只证明契约、确定性和 fail-closed。

### 10.31 2025–2026 新增重合审查：过程级编辑、语义去偏与水印伪造

本节补充本轮官方会议页面核验、且在前文没有以同一研究用途展开的来源。它们将“局部编辑定位”“主动 provenance”“解释”和“视频扩展”拆开，避免把一个大模型或一个水印信号包装成解决 AIGC。每一行都给出一个最小可证伪假设；外部结果、数据量和指标不属于 Smart Shadow 的验证结果。

| 一手来源 | 外部事实 | 对 Smart Shadow 的最小迁移动作 | 不能外推 | 最小可证伪假设 |
| --- | --- | --- | --- | --- |
| [RITA: Revisiting Image Manipulation Localization under Realistic Manipulation Scenarios，CVPR Findings 2026](https://openaccess.thecvf.com/content/CVPR2026F/html/Zhu_Revisiting_Image_Manipulation_Localization_under_Realistic_Manipulation_Scenarios_CVPRF_2026_paper.html) | 将复杂篡改定位重写为条件序列预测，逐层预测编辑区域，并以 HSIM/HSS 评估编辑顺序和层级关系。 | 在有编辑日志或可重放合成链时，把 PC-SCFT 的单一 ROI 拆成 edit_step_id、操作类型、父子区域和顺序；与同传播族 counterfactual 绑定，保留无法确定顺序时的 unknown_trace。 | RITA 的多步合成和序列 mask 不能证明登记原件来源、未知生成器或普通传播 FPR；没有真实操作日志时不能伪造编辑顺序。 | 在冻结的多步局部编辑 manifest 上，加入 ordered trace 是否比单一 union mask 提高 step-level/层级定位，同时 ordinary-propagation FPR 不升高；日志缺失时必须拒判。 |
| [Toward Real-world Text Image Forgery Localization: Structured and Interpretable Data Synthesis，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/df34ea73a7e2108b816194200f1442be-Abstract-Datasets_and_Benchmarks_Track.html) | FSTS 收集 16,750 个真实篡改实例和多格式编辑轨迹（视频、PSD、编辑日志），用分层参数/基函数拟合真实操作分布后合成训练数据。 | 借鉴“记录过程再合成”的数据治理：manifest 保存操作序列、参数、操作者/工具版本和回放摘要；把自动 mask 合成与人工/真实编辑 trace 分层。 | 该工作面向文字图像篡改，过程分布和外部泛化不能外推 AIGC 局部编辑；合成 trace 仍不是客户真实创作证据。 | 用同一真实/合成 split 比较无 trace 的随机 mask 与 trace-conditioned hard negative，若后者只改善 IID 而不改善跨工具/传播 risk-coverage，则不保留为算法创新。 |
| [MLEP: Multi-granularity Local Entropy Patterns for Generalized AI-generated Image Detection，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/63db94e06ce85dde10871c99dd39ad98-Abstract-Conference.html) | 以多尺度 patch Shannon entropy 构造打乱语义的小块特征，论文在包含 32 个生成模型的 open-world 评测中主张增强跨模型检测。 | 作为 ONMA/多流 fallback 的低层 entropy 流；同一 source/query/counterfactual 使用相同 patch-shuffle spec，按 family、传播和语义边界报告增量与 mask-out faithfulness。 | 外部 open-world accuracy 不能转为人类创作证据；打乱小块会损伤配准和局部语义，不能直接替代 source-conditioned delta 或 provenance。 | 在独立生成器/时间切分中，MLEP 流相对 pixel/phase 单流是否降低 ordinary-propagation FPR；若仅提高整图分数、ROI 和拒判覆盖不改善，则只保留为诊断流。 |
| [FakeXplain: AI-Generated Image Detection via Human-Aligned Grounded Reasoning，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/701ec28790b29a5bc33832b7bdc4c3b6-Abstract-Conference.html) | 构造带 bbox 和伪影描述的 FakeXplained 数据集，训练 MLLM 同时输出检测、定位和文字解释，并强调 grounded reasoning。 | 仅作为 BMEA 慢速复核器：保存 proposal/crop、原图与 mask-out 分数、解释文本 digest 和人工一致性；解释不参与四态路由。 | bbox/文字解释可能继承标注和语言先验，不能证明因果、来源绑定或人类可审计证据；外部 OOD 指标不能外推客户图。 | 在同一 query 上遮掉解释所指区域后，若 MLLM 的 raw route/分数不下降，说明解释不具 faithfulness，不能作为复核证据；若没有区域证据则强制 insufficient。 |
| [StableGuard: Towards Unified Copyright Protection and Tamper Localization in Latent Diffusion Models，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/15972a9575e0f03bf82f00aebeb40774-Abstract-Conference.html) | 在 latent diffusion 生成端联合训练水印 VAE 与 MoE forensic network，同时做水印验证、局部篡改定位和频域线索融合。 | 把“生成端主动水印 + 被动局部取证”作为对照组合；EvidenceV1 分开保存 watermark_binding、tamper_roi、生成端版本和冲突状态，不让水印覆盖 PC-SCFT。 | 依赖可控 latent diffusion 服务，不能检测任意既有图片；端到端外部结果不能证明链上来源、自然人贡献或未知生成器。 | 在同一合作生成器上比较 watermark-only、PC-SCFT-only 与冲突拒判组合；攻击/重编码后，若水印阳性但 ROI 不一致，系统是否进入 review 而不是强判。 |
| [Attack-Resistant Watermarking for AIGC Image Forensics via Diffusion-based Semantic Deflection，ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/51e2aaa731e8a5edfbda95fd8bd8948b-Abstract-Conference.html) | PAI 在扩散采样轨迹中按用户 key 做语义级 deflection，目标同时提供 ownership verification、攻击检测和 tamper localization。 | 仅作为合作生成器的 active-provenance adapter；记录 key/verifier 版本、payload/region digest、攻击类型和失败原因，并与水印移除红队绑定。 | 受控生成端和外部验证率不能外推到无水印上传图；合法 key 通过也不证明自然人创作、版权归属或没有后续编辑。 | 在冻结攻击集上，主动水印 route 的 TPR/FPR 与 PC-SCFT 的冲突率是否可审计；任一 key/摘要不匹配时是否稳定回到 unknown/review。 |
| [Transferable Black-Box One-Shot Forging of Watermarks via Image Preference Models，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/47fee9cd8a252161dec7cb48ec0ca2f2-Abstract-Conference.html) | 论文展示仅需一张带水印图、无需知道水印模型即可通过偏好模型做后处理去除/伪造水印，指出 post-hoc watermark 的黑盒伪造风险。 | 将 watermark-forging 纳入 active provenance 的强制红队；保存攻击者能力假设、输入/输出摘要、验证器版本和 route flip，不把水印阳性作为最终来源结论。 | 外部攻击方法与水印实现不代表所有客户水印都可伪造；水印被伪造或移除只说明该 provenance 层失效，不能反推人类或 AI。 | 对每个合作水印，黑盒一张样本攻击后若阳性仍可通过，则必须把 coverage 降为不可用并路由 review；若不能复现攻击也不能宣称鲁棒。 |
| [AI-Generated Video Detection via Perceptual Straightening，ReStraV，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/1d9a43752c2819e03967c5c1b708169c-Abstract-Conference.html) | 用 DINOv2 表征轨迹的时间曲率和步长统计区分自然/生成视频，强调时序几何而非单帧伪影。 | 作为 P2 视频扩展的轻量时序流；manifest 保存 frame/segment digest、采样策略和传播链，与帧级局部编辑证据、时间稳定性和缺帧拒判分开。 | 外部视频 benchmark 和准确率不能外推图像 AIGC 或跨模态来源；时序几何阴性不能证明自然拍摄。 | 在同视频同传播族的编辑/普通压缩对照上，时序曲率流是否降低单帧 detector 的 route flip；若视频缺帧或重排后性能崩溃，必须回退 unknown。 |

#### 10.31.1 重合结论与新增创新门

这批论文将当前路线的重合风险收敛为四点：

1. **过程级定位已有先例。** RITA 已把多步操作、顺序和层级作为定位对象；Smart Shadow 不能把“多步 mask”单独称为新算法。可辩护的增量只在于：登记原件/observed/counterfactual 三元绑定、普通传播 null、质量分层和缺 trace 拒判共同成立。
2. **低层去语义流已有先例。** MLEP、WaRPAD、pixel mapping 等已覆盖语义扰动或 crop 鲁棒。新增 entropy/时序流必须以 source-conditioned paired delta 的互补增量为目标，且不能用整图 AUROC 替代 ROI/拒判指标。
3. **解释和主动水印各有成熟路线。** FakeXplain、StableGuard、PAI 证明解释、端到端水印和局部定位可以组合，但水印 forge 攻击说明 provenance 必须有攻击后覆盖率与冲突回放；解释不能覆盖 raw evidence。
4. **视频应保持独立证据层。** ReStraV 和现有 AIGVDBench/SAGA/FVBench 支持时间 manifest 与时序拒判，但不能将视频模型结果迁移到图像主线或线上四态。

因此下一项最小组合假设不是“再训练一个更大的 detector”，而是：**在有真实编辑过程或可重放 trace 的登记资产上，Source-Conditioned Edit Trace（有序步骤 + canonical ROI + ordinary-propagation null + matched placebo）是否相对 union-mask PC-SCFT 同时降低普通传播误报并改善 step-level ROI/faithfulness；trace 缺失、参考图误配、攻击后水印冲突或时序证据不可检测时是否稳定拒判。**这一假设需要独立 trace/传播 manifest、跨工具和跨生成器时间切分、红队攻击、人工复核和 docs/07 回放，不能由当前 synthetic runner 证明。
### 10.32 Operation-aware Edit Lineage：新增但仍受重合约束的研究切片

RITA、FSTS、EditTrack 等工作已经说明，多步编辑顺序、过程轨迹和局部定位本身不是空白。Smart Shadow 可验证的最小增量是把这些过程证据放进登记原件场景：`reference → observed` 的声明步骤链与同传播族 `counterfactual`、canonical 坐标帧、质量分层 null、matched placebo 和拒判绑定在同一证据包中。

工程上，内容编辑缺步骤 mask 或区域 `mask_overlap_raw` 时拒判；普通传播步骤保留为 `operation_scope=ordinary_propagation`，不能因为 trace 一致就路由为 AI 编辑。`lineage_consistent` 只表示 raw evidence 与声明 trace 的结构契约一致。当前 5 个 scalar fixture 的 digest 为 `92c968fc140ba2de64e37acc1c1313bf9a53eb48d693537c5a490f322989c2da`，不能支持过程 provenance、AIGC 准确率或论文创新结论。

可证伪评测必须比较：无 trace 的 union-mask PC-SCFT、仅 trace、trace+ordinary-propagation null、trace+matched placebo 和完整方案；按跨工具/生成器、时间下一周期、截图/再编码/再拍摄传播报告 step-level ROI IoU/边界 F、普通传播 FPR、unknown/review、coverage-risk、P95 和人工复核分钟。trace 缺失、过程日志不可信或操作 digest 冲突时，系统应回到 `insufficient`，不能用最终图像猜测编辑历史。

### 10.33 Ordered lineage multi-view matched-control：组合协议的最小实现

本轮把 10.32 的研究假设收敛为 `aigc/lineage_view_control.py`。它只接收已经通过
`edit_lineage` 结构校验的 trace、同一 trace 下多个 canonical view 的
observed/counterfactual 区域 delta，以及上游 MPCF 已计算的 `control_route`、
`control_contrast_raw`、`control_p_value_raw` 和 `control_digest`。本层按
`view × step × region` 重做身份和 digest 绑定，按质量×source-match 聚合 view persistence，
检查 step onset order、跨视角离散度、正负支持分歧和内容编辑的 `mask_overlap_raw`；不重新拟合
placebo，不加入新的 detector，也不把 trace 一致性当作来源真值。

与 prior art 的重合边界要写清：RITA/SEED 已有步骤或顺序定位，Crop-Consensus 已有多视角集合
共识，MPCF 已有单区域 matched placebo，本切片的主张只是把三类已绑定 raw evidence 在登记原件、
同传播族 counterfactual 和保守拒判条件下组合成可回放的 step trajectory 审计。`consistent_controlled_lineage`
只表示当前组合契约通过；`trajectory_inconsistent` 和 `insufficient` 都必须 abstain，普通传播
trace 固定为 `ordinary_propagation_scope`，三种路由均不能改写 `aigc_result_v1`、AIGC 概率、
来源/作者证明或法律结论。

当前 5 个 scalar case 的合成 runner dataset digest=`28d3ecbe0fd827e766fcdb51f1d245a3c894e575fa8da91f8e171f61050c8ba3`，只覆盖顺序正确/反序、普通传播隔离、binding 缺失和 control 支持不足。真实可证伪评测必须在同一授权 manifest 上比较 union-mask PC-SCFT、仅 trace、trace+ordinary null、trace+MPCF 与完整组合，分层报告 step-level ROI/边界 F、普通传播 FPR、unknown/review、coverage-risk、P95 和人工复核分钟；真实过程日志、编辑 mask、多视角图像、控制集独立性、空间相关性、跨生成器/时间切分和线上接入当前均未验证。

### 10.34 Evidence-grounded explanation audit：下一步最小可证伪切片

X-AIGD、Locate-Then-Examine、FakeXplain 和 AnomReason 都说明“定位或解释”已有公开先例，不能把热力图、自然语言解释或异常类别单独包装成 Smart Shadow 创新。更稳妥的工程切片是已实现的 `explanation_audit_v1`：只引用已有 `region evidence`，并用 `mask-out`、`region swap` 和 ordinary-propagation null 验证解释是否真正支撑 raw score 变化。

最小 sidecar 字段为 `evidence_region_ids`、`artifact_category`、`proposal_mask_digest`、`score_before_raw`、`score_after_maskout_raw`、`delta_raw`、`human_review_ref`、`faithfulness_route` 和 digest。固定对照为无解释、自由文本解释和 grounded sidecar；指标为 evidence completeness、ROI IoU/Dice/boundary-F、mask-out faithfulness、region-swap 误激活、普通传播误报、人工一致性、unknown/route flip、P95 和成本。

这条切片仍是阶段 7 的 raw-evidence 工程，不输出 AIGC 概率、作者/来源或法律结论，也不接线上。真实 mask、人工类别、跨生成器/时间切分和独立 null 未准备好之前，任何结果都只能写成契约或 synthetic fixture；如果 grounded sidecar 不能改善选择性风险、ROI 或复核分钟，就保留为调试层。

### 10.35 2026 AAAI real-only、校准与自然发生数据的重合审计

RealNet、ConV、One-for-All、RealOnly calibration 以及相关 natural-manifold 工作已经覆盖 real-only、开放集归因和标量校准原语。它们不能被重新命名为 Smart Shadow 的独立创新。可迁移的工程字段是 `natural_consistency_profile`、`manifold_profile_digest`、`target_domain_calibration_id`、support manifest digest、pre/post score 和 rollback 指针；研究对照需加入 ordinary-propagation null、未知生成器、时间下一窗、截图/再编码和局部编辑，并报告 ECE/Brier、risk@coverage、unknown recall、route flip 与 P95。

Real-only 阴性不等于人类创作，标量校准也不替代 source/query 配对和普通传播 null。MIRAGE 等真实网络数据工作应促使 manifest 增加自然发生 AIGI、后处理 composite、人工核验和时间字段，但外部 benchmark 数字不能转为本项目结果。当前路线顺序保持：P0 维护并真实验证 `explanation_audit_v1`，P1 natural-consistency fallback，P1 red-team evidence audit，P2 target-domain calibration，P3 合作硬件/生成器的主动 provenance。

### 10.36 研究路线总收口

2025–2026 的一手工作已经分别覆盖 real-only/natural-manifold（ConV、RealNet、SACG）、测试时语义或 prompt 适配（ATTSD、IAPL）、裁剪/传播鲁棒（WaRPAD、HiDA-Net）、区域定位和 grounded explanation（X-AIGD、FakeXplain、LTE）、主动 provenance（CustomMark、Witness Sensing）及 detector-evasion red-team（Adversarial Reality）。因此 Smart Shadow 不应把“再训练一个更大 detector”“测试时最高置信选择”“自然流形”“热力图/文字解释”单独包装为创新。

当前最小可辩护主张仍是：登记原件与 query 的 canonical 配对、同传播族 ordinary-propagation null、matched placebo、多视角/有序 trace、可检测性与策略级校准、解释 mask-out/region-swap 审计和 fail-closed evidence replay 的组合，是否在真实授权数据上降低普通传播 FPR 与人工复核成本并保持 ROI/faithfulness；其余路线只作为 fallback、对照或合作扩展。

### 10.37 Explanation audit 的 prior-art 修订

审计确认：X-AIGD、LTE、FakeXplain、DeepfakeJudge 以及通用 deletion/insertion/AOPC 已覆盖伪影区域、grounded explanation 和干预忠实性。因此 `artifact_category`、mask-out、ROI IoU、人工一致性和 digest 只能作为工程契约。唯一值得继续验证的组合假设是：同一登记原件、同一传播族 null、同一 intervention operator 下，observed-minus-null 的区域干预效应是否比 model-only explanation 更能降低普通传播误报并保持 ROI/复核效率。若去掉 null/control 后收益不下降，应撤回 source-conditioned explanation 的创新主张。

### 10.38 2026-09-20 一手审计增补：反事实分割、解释忠实性与证据干预的边界

本节补充三组此前没有以同一用途进入索引的官方论文/代码/数据页。它们不改变现有四态边界；作用是把 `explanation_audit_v1` 的“干预后分数下降”从直觉指标收紧为可被反驳的审计协议。

| 一手来源 | 已覆盖的先例 | 对 Smart Shadow 的约束 | 不能外推 |
| --- | --- | --- | --- |
| [Measuring the (Un)Faithfulness of Concept-Based Explanations（SURF，CVPR 2026）](https://openaccess.thecvf.com/content/CVPR2026/papers/Kumar_Measuring_the_UnFaithfulness_of_Concept-Based_Explanations_CVPR2026_paper.pdf)；[官方项目页](https://skumar-ml.github.io/projects/surf.html)；[官方代码](https://github.com/skumar-ml/surf-eval) | SURF 指出 deletion-based faithfulness proxy 可能因删除操作制造离流形输入而虚高，并要求简单、不可训练的 surrogate、跨所有输出类别的误差和 random-concept sanity check。 | `mask-out`/`region-swap` 只能称为 intervention response，不能单独称“忠实性证明”。后续 explanation sidecar 至少要保存全输出 `effect_vector`、operator digest、原图/反事实的质量与来源匹配、随机/decoy 区域负对照和 `intervention_validity`；比较 evidence mask、随机 mask、decoy mask 和 null mask。若随机区域同样造成大幅 route flip，解释审计必须 `insufficient`。 | SURF 主要针对最终线性层的概念解释，并不直接给出 AIGC 检测方案；其 MAE/EMD 或外部结果不能转成项目准确率、来源证明或法律证据。 |
| [Counterfactual Segmentation Reasoning（CVPR 2026 Findings）](https://openaccess.thecvf.com/content/CVPR2026F/html/Li_Counterfactual_Segmentation_Reasoning_Diagnosing_and_Mitigating_Pixel-Grounding_Hallucination_CVPRF_2026_paper.html)；[官方代码](https://github.com/PLAN-Lab/HalluSegBench)；[官方数据页](https://huggingface.co/datasets/PLAN-Lab/HalluSegBench) | HalluSegBench 以 factual/counterfactual 成对图像检查视觉 grounding；模型在反事实中应停止输出不存在对象的 mask，并显式报告 hallucination severity。官方仓库公开约 1.4K 对反事实图像、287 个对象类别和四种预测组合。 | PC-SCFT/SCTE 应增加 `counterfactual_mask_persistence` 与 `null_mask_hallucination_rate`：query 上的 evidence mask 可支持候选，普通传播 null、区域替换或 decoy counterfactual 上必须消失或进入 `null_consistent`/`insufficient`。评测要保留“factual positive、same-label null、decoy absent、wrong-reference”四格，而不是只看 query ROI IoU。 | 该工作是视觉语言分割 grounding，不是 AIGC detector；公开反事实数据和 30% hallucination 降幅不能外推到登记原件、生成器开放集或项目四态。 |
| [Looking in the Mirror: A Faithful Counterfactual Explanation Method（ICCV 2025）](https://openaccess.thecvf.com/content/ICCV2025/papers/Chowdhury_Looking_in_the_Mirror_A_Faithful_Counterfactual_Explanation_Method_for_Interpreting_Deep_Image_Classification_Models_ICCV2025_paper.pdf)；[官方代码](https://github.com/AIML-MED/Mirror-CFE) | Mirror-CFE 在分类器自身 feature space/decision boundary 中生成逐步 counterfactual，避免完全依赖外部生成器来制造解释，并同时检查 validity、proximity 和 transition。 | 对能暴露 feature/logit 的 detector，增加 feature-space transition 作为 explanation baseline；对黑盒 detector 不伪造 feature-space 解释。像素 mask-out 仍需 ordinary-propagation null、质量门和 operator validity；不得把“生成了看起来合理的反事实图”当成来源证据。 | Mirror-CFE 在通用图像分类数据上评估，不解决 source/query 配对、未知生成器、普通传播 FPR 或版权事实；外部反事实图像的逼真度不能证明编辑因果。 |

由此，`faithfulness_route` 不应只由 `delta_raw > threshold` 决定，至少应满足：

```text
valid intervention operator
+ observed effect vector
+ null/decoy effect vector
+ random-region negative control
+ source/quality/schema binding
+ fail-closed replay
```

其中 `observed-minus-null` 仍是项目的 source-conditioned 增量；SURF 和 HalluSegBench 说明它必须再经过“全输出、反事实消失、随机区域不应同样有效”三道 sanity check。该组合尚未在真实授权图片上验证，不能改写为 AIGC 概率或“解释已忠实”。

### 10.39 2026-09-20 NTIRE 2026 官方挑战资料复核：传播矩阵不等于来源条件评测

除 CVPR Workshops 官方挑战页面外，本轮核验了[官方挑战代码仓库](https://github.com/msu-video-group/NTIRE-2026-DeepFake-Detection)和[挑战论文](https://arxiv.org/abs/2604.11487)公开的标签/数据结构。资料说明挑战以真实/生成二分类标签、42 个开源与闭源生成器、36 类变换和 108,750 张真实图、185,750 张生成图评估野外鲁棒性；代码仓库的最小数据类按 shard 图像与 `labels.csv` 读取，标签 `0/1` 只表示 real/generated。

这对 Smart Shadow 有三个直接约束：

1. NTIRE 风格变换矩阵应作为传播 hard-negative/外部鲁棒性层，逐生成器、逐变换报告分数漂移、FPR、ECE、unknown 和 P95；不能只报告总体 AUROC。
2. 挑战标签没有登记原件、同资产 counterfactual、局部 edit mask 或传播族 null，因此 NTIRE 不能验证 PC-SCFT 的 source-conditioned 增量，也不能用于证明版权来源。
3. 官方代码和挑战数据只作为研究依赖候选；下载许可、完整数据访问、生成器授权和客户数据隔离须另行审计，不把公开标签写进生产校准 profile。

最小下一实验是同一冻结 manifest 上的二维对照：`NTIRE-like transform × source-conditioned triad`。先测 ordinary-propagation null 是否让局部 evidence 保持 `null_consistent`，再测真实/编辑 query 的 observed-minus-null 是否改善 ROI 和 selective risk；若只有二分类 AUROC 增长、而 null FPR/反事实 mask persistence 不改善，算法主张必须退回“传播鲁棒对照”，不能称为 Smart Shadow 创新。

### 10.40 本轮最小可辩护创新主张与下一实验

**最小主张（仍待证伪）。** Smart Shadow 不主张发明局部 mask、反事实、开放集 detector 或解释指标；唯一可继续检验的增量是：在同一登记原件、同一 canonical frame、同一传播族 ordinary-propagation null 和同一 intervention operator 下，把 observed/null 的全输出干预效应、反事实 mask 消失、matched placebo 和 fail-closed replay 组合成可审计的 source-conditioned evidence test。

**下一实验（只做离线研究，不接线上）：**

1. 固定一个授权 `reference/observed/counterfactual` manifest，加入 3 类普通传播、3 类局部 AI 编辑、1 类 decoy/错误参考和 1 类随机 mask；每个样本固定 `operator_digest`、质量、source-match、detector/schema 和 split。
2. 对比 A0 单图分数、A1 query-reference delta、A2 PC-SCFT、A3 `explanation_audit_v1`、A4 完整 `observed-minus-null + random/decoy control` 五路；不得通过重新选择阈值隐藏失败样本。
3. 除 image-level AUROC 外，必须输出 ordinary-propagation FPR（95% CI）、ROI IoU/Dice/boundary-F、`counterfactual_mask_persistence`、random/decoy effect gap、coverage-risk、unknown/review、route flip、P95 和人工一次复核分钟。
4. 预注册撤回规则：若随机区域 effect gap 不低于 evidence 区域、null FPR 上升、或收益只来自放宽拒判门，则撤回“source-conditioned explanation”创新主张，保留为调试/审计协议。
5. 只有在跨生成器、时间下一窗和截图/再编码/再拍摄三层都满足上述门，并把真实结果写入 `docs/07-验证与运行记录.md` 后，才能讨论论文主张；当前合成 runner、公开 benchmark 和论文数字均不满足。

代码/数据许可证仍需独立核验：论文页、作者代码和数据卡只能证明公开入口存在，不能直接授权商用、再分发或生产集成；本轮不下载或接入 SURF/HalluSegBench 依赖。

### 10.41 Counterfactual mask persistence 的工程落地与主张边界

基于反事实分割 grounding 的公开先例，本仓库已把四格 sanity check 落地为
`counterfactual-mask-persistence-v1`：factual view 冻结目标 region set，ordinary-propagation、
decoy 和 wrong-reference 作为控制，逐视角计算区域重合与控制 hallucination。它的作用是验证
“目标 mask 在真实候选中保持、在匹配反事实中消失”，补充 D-050 的 matched-intervention 和
D-051 的 multi-operator stability。

该切片不能单独称为算法创新；mask persistence、counterfactual grounding、decoy control 和
region overlap 都已有先例。Smart Shadow 只能继续检验完整组合是否在同一登记原件/传播族/坐标帧
下降低 ordinary-propagation FPR、random/decoy 激活和人工复核成本。真实实验必须加入人工或生成器
edit mask、wrong-reference、局部替换/重编码/截图传播和时间/生成器外部切分，并报告
`counterfactual_mask_persistence`、`null_mask_hallucination_rate`、ROI IoU/Dice/boundary-F、
coverage-risk、unknown/review、route flip、P95 和成本。合成 digest 不能替代这些结果。

### 10.42 本轮 prior-art 刷新

本轮新增的 AIGIBench、SAFE、NTIRE、Locate-Then-Examine、PRADA、CDAL、SimLBR、IFA-Net 和 SPARED
已集中索引于 [`docs/research/2026-09-20-市场算法刷新.md`](research/2026-09-20-市场算法刷新.md)。它们分别覆盖多来源/局部编辑传播评测、区域复核、生成器归因、real-only 流形和
source/edit adversarial hard negatives；Smart Shadow 不把这些单项能力重新命名为创新。

后续实验新增 A11 source/edit adversarial red-team，但必须与 A0–A8 使用同一授权 manifest、同一
ordinary-propagation null、时间/生成器切分和人工复核指标。最小主张仍是登记原件条件下的
source-conditioned matched-intervention contrast；外部 ROC-AUC、归因或 mask 指标不写入本项目结果。

### 10.43 Blind reference specificity：把参考原件选择纳入可证伪协议

D-054 的新增问题不是再做一个 detector，而是检验“当前候选登记原件是否比相似原件更能解释 query 的 observed-minus-null contrast”。`reference-specificity-v1` 要求 candidate 与同 query 的盲选 decoy 共享 manifest、canonical frame、transform/operator、detector/schema、quality/source-match bucket，并让 selection/evaluation split 保持独立；结果只保留候选/decoy raw contrast、上分位、gap、有限样本 p-value 和 digest。

该切片已完成离线契约：12 项单测、5 个 synthetic case，路由为 `reference_specific_candidate=1`、`reference_ambiguous=1`、`reference_null_consistent=1`、`insufficient=2`。p-value 使用 `(1 + exceedances) / (n + 1)`；3 个 decoy 的最小 p 值为 0.25，因此不能把小样本 fixture 写成 0.05 显著性。它只验证绑定、支持、分区隔离和确定性，不证明真实参考 false-match rate、AIGC 效果、来源或作者身份。

真实实验需在同一授权 manifest 上比较无 decoy、随机 decoy、语义相似 decoy、wrong-reference 和完整 PC-SCFT；若 reference-specific gate 只增加拒判而没有降低 ordinary-propagation FPR、reference false-match rate 或人工复核分钟，应撤回算法创新主张，保留为 provenance/review audit。

### 10.44 下一候选方向：version-DAG evidence consistency

当前 D-050–D-054 已覆盖单个 reference/query/null、多个 operator、factual/control mask、单条 edit trace 和参考选择。仍有一个产品相关但尚未批准的研究空白：同一登记资产的多版本传播图中，父子传播边、兄弟导出和编辑后的后代是否满足拓扑约束。可候选设计为 `Source-Conditioned Evidence Graph Consistency`，只消费已绑定的上游 sidecar，不重新计算 detector、p-value 或 placebo。

最小可证伪问题是：普通传播边是否产生异常新区域激活，内容编辑边是否出现 declared-mask 之外的 support，兄弟分支是否出现明显 disagreement，证据是否沿后代路径保持。输出应限定为 `graph_consistent`、`propagation_leak`、`branch_conflict`、`trajectory_inconsistent` 或 `insufficient` raw audit route；不能称图神经网络、通用 AIGC detector、来源证明或因果证明。真实开发必须等 D-050–D-054 的授权 manifest 和普通传播 null 回放稳定后再登记新决策和技术契约。

### 10.45 2026-09-20 一手论文刷新：无原件 fallback、训练期红队与生成器族切分

本轮补充只用于 prior-art 对照和实验设计，外部论文指标不属于 Smart Shadow 结果：

| 方向 | 一手来源与可迁移设计 | Smart Shadow 边界 |
| --- | --- | --- |
| GAPL / Generator-Aware Prototypes | [CVPR 2026 官方论文](https://openaccess.thecvf.com/content/CVPR2026/papers/Qin_Scaling_Up_AI-Generated_Image_Detection_with_Generator-Aware_Prototypes_CVPR_2026_paper.pdf)；多生成器扩展存在 benefit-then-conflict，可做无原件 generator-family 路由和 scaling curve。 | 不依赖登记原件、局部 mask 或 ordinary null；prototype 命中不等于来源/作者证明，不能改写四态。 |
| LTD / Layer Transition Discrepancy | [CVPR 2026 官方论文](https://openaccess.thecvf.com/content/CVPR2026/html/Yang_Layer_Consistency_Matters_Elegant_Latent_Transition_Discrepancy_for_Generalizable_Synthetic_Image_Detection_CVPR2026_paper.html)；跨层表征过渡可作为无原件被动流。 | 需测试 JPEG/resize 是否替代生成痕迹；不能证明局部编辑、来源或法律事实。 |
| RealStats | [AISTATS 2026 PMLR 官方页](https://proceedings.mlr.press/v300/zisman26a.html)；real-only 统计量和 p-value 可补充 conservative fallback/calibration。 | p-value 依赖 real calibration exchangeability；非拒绝不等于人类创作，拒绝不等于 AI 生成。 |
| PROBE | [ICML 2026 论文](https://arxiv.org/abs/2605.24906) 与[作者代码](https://github.com/Amamiya-C/PROBE-AIGI-Detection)；沿生成器边界生成难例，适合作为训练期 adversarial coverage。 | 需要可控生成器和算力，只证明训练覆盖改善，不能把难例写入生产校准或客户证据。 |
| NeuroRenderedFake | [NeurIPS 2025 benchmark 官方页](https://proceedings.neurips.cc/paper_files/paper/2025/hash/56bdf726a96d43ee1e66172d14c63a61-Abstract-Datasets_and_Benchmarks_Track.html)；增加 NeRF/3DGS/hybrid rendering 生成器族。 | 外部生成渲染分布不能代表客户图；应按族、时间、传播逐层报告 FPR/ECE/unknown/P95。 |
| Authenticated Contradictions | [CVPRW 2026 APAI 官方论文](https://openaccess.thecvf.com/content/CVPR2026W/APAI/papers/Nemecek_Authenticated_Contradictions_from_Desynchronized_Provenance_and_Watermarking_CVPRW_2026_paper.pdf)；C2PA manifest 与像素 watermark 的语义冲突可作为 provenance conflict adapter。 | 冲突进入 `unknown/review`，不生成 AIGC 概率；水印阴性不证明人类创作。 |

建议新增对照：无原件路由比较 `source-residual`、GAPL/LTD/RealStats；生成器族加入 neural-rendering；训练期单列 PROBE red-team。所有流都必须保留 detector/schema/profile/dataset digest，按 ordinary-propagation、generator、time split 报告 selective risk、unknown、P95 和成本。

### 10.46 D-055 version-DAG 的研究边界

D-050–D-054 已覆盖单个 reference/query/null、干预算子、控制 mask、编辑链和盲参考选择；D-055 只补充跨版本父子图的拓扑审计。它不是图神经网络或来源证明，不能替代 C2PA Actions、RITA/SEED 等已有过程/provenance 先例。真实实验要比较无图、单边父子检查和完整 DAG sidecar，按普通传播漏激活、声明 mask 外支持、兄弟分支 disagreement、后代 persistence、unknown/review、人工复核分钟和 P95 报告；若完整 sidecar只增加拒判而不降低 ordinary-propagation FPR或人工成本，撤回算法创新主张，保留为证据包审计。

### 10.47 2026-09-20 一手先例刷新：训练偏差、轨迹探针与水印红队

本节将本轮核验的一手论文放在 prior-art 对照位。它们改变实验设计和撤回条件，不改变 Smart Shadow 的四态边界，也不把外部结果写成仓库效果。

| 先例 | 已覆盖能力 | Smart Shadow 的可迁移实验因素 | 不能据此宣称 |
| --- | --- | --- | --- |
| [Stay-Positive（ICML 2025）](https://proceedings.mlr.press/v267/sundara-rajan25a.html) | 约束检测器忽略 real-side shortcut，减少压缩等伪相关。 | 将 real-side shortcut、JPEG/格式和真实图域偏差列为训练/红队消融；记录 post-processing、局部 inpaint 与 ordinary-propagation FPR。 | 非负/正向分类头不是本项目独立创新，也不解决登记原件、局部 mask 或 provenance。 |
| [Aligned Datasets Improve Detection of Latent Diffusion-Generated Images（ICLR 2025）](https://proceedings.iclr.cc/paper_files/paper/2025/hash/9ead108421b202494d01b5060d12aa34-Abstract-Conference.html) | 用同语义、同格式的 AE 重建真实图构造 aligned real/fake，减少语义/分辨率/格式捷径。 | 训练或校准流必须保存 paired alignment、decoder/模型版本和 split；与 source-conditioned ordinary null 分开做消融。 | aligned dataset 只能改善训练数据设计，不能证明来源、作者或客户图片准确率。 |
| [Denoising Trajectory Biases（NeurIPS 2025）](https://papers.nips.cc/paper_files/paper/2025/hash/dfd12fe50b18505e3c912c4426707cc7-Abstract-Conference.html) | 用 diffusion inversion 的去噪轨迹相似度做 zero-shot 检测，属于过程/轨迹探针。 | 可作为无原件慢速 adapter；必须单独记录 inversion 模型、步数、成本，并测截图/再编码、未见生成器和 real-only 校准。 | 轨迹相似度不是 source/query/null 证据，也不是 AIGC 概率或法律结论。 |
| [Target-domain calibration（AAAI 2026）](https://ojs.aaai.org/index.php/AAAI/article/view/38146) | 冻结 backbone，用小目标域样本做 scalar logit correction，应对分布偏移。 | profile 保存 calibration id/digest、目标域/时间窗、样本支持量、ECE/Brier、rollback；禁止把无标签校准当成真实标签。 | 标量校准不能替代独立 ordinary-propagation null、开放集拒判或真实授权评测。 |
| [MIRROR（arXiv 2026）](https://arxiv.org/abs/2602.02222) | 学习 real-image manifold 的 ideal reference，再用 residual 检测；与 ONMA/real-only fallback 有重合。 | 作为无原件 real-manifold 对照，测 leave-one-generator-out、真实传播和局部编辑；保留 profile 版本与训练许可。 | real-manifold residual 已有先例，不是本项目“reference comparison”独立发明；非拒绝不等于人类。 |
| [WMCopier（NeurIPS 2025）](https://proceedings.neurips.cc/paper_files/paper/2025/hash/c972859a984a21658432d7320c7df385-Abstract-Conference.html) | 展示黑盒隐形水印伪造与错误归因风险。 | 加入 watermark-forgery/removal red-team；C2PA、watermark 和视觉 raw evidence 发生语义冲突时固定 review/unknown。 | 水印通过、凭证有效或冲突本身都不证明来源、作者、版权或侵权。 |

因此 D-056 的新增价值只剩“把无原件 prototype 与 real-only p-value 分开绑定、支持量/输入/profile 完整性和冲突拒判”这一工程契约；它仍不是新的 detector。主算法主张继续收敛到登记原件、ordinary-propagation null、matched intervention、控制集和可回放拒判的组合，必须以真实授权数据的 selective risk 与人工复核收益证伪。

### 10.48 2026-09-21 论文与算法创新深挖：选择后校准（D-060 / SAEC-v1）

本轮一手先例覆盖审计集中见 [`docs/research/2026-09-21-论文与算法创新深挖.md`](research/2026-09-21-论文与算法创新深挖.md)。它进一步确认单图检测、局部定位、开放集/real-only、质量校准、C2PA/水印和版本轨迹都有公开先例；Smart Shadow 的最小可辩护主张仍是“登记原件 + ordinary-propagation null + blind decoy/wrong-reference + matched intervention + selective abstention”的组合协议。

研究审查已形成 D-060，并批准 `SAEC-v1`（selection-aware, stratified evidence calibration）作为阶段 7 的离线研究契约，用来处理“从大量参考图中挑 winner 后再评估”的 selection bias/winner's curse。当前实现只消费 D-054/D-058 已生成的 scalar contrast 和 sidecar，要求 selection/calibration/evaluation 三个独立 split、固定 decoy 数、按 generator/quality/transform/time 分层的 ordinary-propagation profile，并输出 `selection_specific_candidate`、`selection_ambiguous`、`null_consistent` 或 `insufficient` raw route。`aigc/selection_aware_calibration.py`、对应专测和 synthetic runner 已完成无模型契约回归；SAEC 不改 `aigc_result_v1`、D-054 或 D-058，也不接线上服务。

当前实现状态不等于真实效果成立：授权 query、独立 calibration groups、blind decoy、D-058 稳定性、跨生成器/时间切分和 G0–G6 消融仍未完成。进入论文或产品主张前，必须在同一冻结 manifest 上完成下述对照并报告普通传播误报、selective risk、ROI/边界质量、route flip、延迟、成本和人工复核收益；在此之前只能写成 raw evidence、`review` 或 `insufficient`。

### 10.49 2026-09-21 论文前沿补充：SCPTN-v1（D-062）

新增一手先例和重合审查见 [`docs/research/2026-09-21-AIGC前沿补充与下一创新切片.md`](research/2026-09-21-AIGC前沿补充与下一创新切片.md)。AIGIBench、RRDataset、DailyBench、SAFE、DICE、X-Edit、OpenSDI、DTS-Det、DoU、MLEP、WaRPAD、QuAD、IAPL 和 BCEA 进一步覆盖了真实传播、image-conditioned 局部编辑、开放集、多伪影、多视角选择和预算采证；D-057 generator-family router 暂缓编码，避免把已有开放集 detector 重新包装成创新。

D-062 `source-conditioned-propagation-tree-null-v1`（SCPTN）只提出一个更窄的可证伪组合：把同一登记资产的 ordinary-propagation 版本作为单根树，以树而不是相关的单个版本作为统计单位，对树内选择后的最大 paired local delta 建立分层 null profile。它与 QuAD/ReWIND 的质量聚合、IAPL 的最高置信 view 选择、BCEA 的 answer/abstain/acquire 和 SAEC 的 scalar winner 校准不同之处，只能落在 source/query/ordinary-counterfactual 的绑定、树级相关性和回放拒判。

当前代码、10 项专测和 5 个 synthetic case 已完成；固定 raw route 为 `tree_specific_candidate`、`tree_selection_ambiguous`、`tree_null_consistent`、`insufficient`。结果不输出 AIGC probability、作者或法律字段，不接线上服务。真实 G0–G6 评测必须比较逐版本 null、去树相关性、D-054、SAEC、SAEA 和完整组合，覆盖普通传播、局部编辑、错误 reference、未见生成器、下一时间窗、截图/再编码/再拍摄和低质量版本；只有 ordinary-propagation FPR、reference false-match、risk@coverage、ROI/边界 F、P95、成本或人工复核分钟在等预算下改善，才可讨论研究增量。

### 10.50 2026-09-21 ALG-001/SIPA 威胁模型补充：membership 不等于来源，且必须防隐私泄漏

ACL Findings 2026 的 [mRAG membership inference 与 image-caption retrieval 研究](https://aclanthology.org/2026.findings-acl.444/) 表明，多模态检索系统可能被用来判断视觉资产是否进入私有检索库，并尝试提取关联 caption/元数据。因此，`ALG-001` 的 retrieval membership 和 `SIPA` 的 A/B direct lookup 同时具有来源审计与访问隐私风险。它们不能只保存“命中/未命中”并把命中解释成来源证据。

#### 10.50.1 研究事件的最小隐私字段

在不修改线上接口的阶段 7 研究 sidecar 中，`RetrievalEvent`、`SIPASelectionTraceV1` 和对应 archive/index snapshot 至少要绑定以下字段或等价摘要：

```text
privacy_scope                 # tenant/collection/purpose scope，禁止跨域默认放宽
request_principal_digest      # 脱敏的调用主体/角色摘要，不写姓名或凭证
access_policy_digest          # 当时适用的最小权限策略版本
access_audit_digest           # grant/deny、用途、时间窗和审计链摘要
retention_policy_digest       # 留存期限、删除负责人和复核规则
deletion_tombstone_digest     # 已删除/撤回条目的版本化墓碑和生效时间
raw_asset_return_policy       # 只允许 digest/feature/region 摘要，默认禁止原始像素回显
metadata_return_policy        # caption、EXIF/XMP/IPTC 等字段的最小化和脱敏规则
```

字段值不足时只输出缺口原因，不用占位字符串冒充授权或访问通过。`privacy_scope`、访问主体、用途、快照、删除墓碑和 evidence digest 必须参与 canonical digest；任意一个字段改变，事件应改变 digest 或拒判。

#### 10.50.2 必须加入的回放与红队对照

`ALG-001` 事件回放和后续 `SIPA` B direct lookup 应至少预留以下 fixture/真实数据对照：

1. 同一资产在允许 collection 中命中，在无权 collection 中固定 `privacy_scope_violation`，不得借 A 的命中回退成功。
2. 条目已被删除或撤回，但旧 index 仍返回它，固定 `deletion_stale`；删除墓碑缺失、过期或无法重算时固定 `deletion_audit_missing`。
3. 请求者只有 feature/digest 权限却收到原始像素、caption 或 EXIF/XMP/IPTC，固定 `raw_asset_echo`/`metadata_scope_violation`，结果只保留最小化 evidence digest。
4. B index 能看到 A 未授权的候选、跨租户候选或超出 retention 的条目，固定 `access_audit_missing`/`cross_scope_leak`，禁止启动强 `holdout_consistent`。
5. poisoning/near-duplicate 既改变候选排序又尝试扩大可见范围时，分别记录 `poisoning_route_flip` 与隐私 reason，不把两种失败压成一个普通来源误配。

这些对照要在同一 frozen archive/index snapshot、授权用途和删除策略下重放；真实数据不足时只返回 `not_evaluated`、`review` 或 `insufficient`，不能用合成 membership 命中率或论文攻击率替代项目隐私指标。至少报告跨 scope 泄漏数、过期条目可见数、raw asset echo 数、删除回放成功率、审计摘要完整率、P50/P95 和人工处置分钟。

#### 10.50.3 与主动水印的边界

同日核验的 [SAiW（Source-Attributable Invisible Watermarking）](https://arxiv.org/abs/2603.23178) 说明 source-conditioned watermark/attribution 已有主动防伪先例。Smart Shadow 若接入水印或 C2PA/SynthID 等信号，只能把它们作为独立 adapter：保存 key/verifier 或 trust/parser 版本、输入/输出 digest、覆盖、移除/伪造和冲突状态，并与 retrieval membership、ordinary-propagation null、人工复核分开校准。水印阳性、阴性、缺失或与资产 registry 冲突均不能直接产生 AIGC 概率、作者/版权判断或法律结论；被动信号缺失时仍必须允许 `unknown`/`review`。

本节只收紧阶段 7 的 threat model 和证据最小化要求，不改变 `aigc_result_v1`、线上服务、商业接口或 G0–G6 数据门。任何“隐私保护通过”“删除已完成”或“水印验证可靠”的表述，都需要真实授权 manifest、权限审计、删除演练和独立红队记录后才能使用。

## 10.51 算法创新终审入口

本轮论文先例、开放集/传播/局部编辑/选择偏差边界和创新候选已集中到 [`docs/research/2026-09-21-市场商业化与AIGC算法创新终审.md`](research/2026-09-21-市场商业化与AIGC算法创新终审.md)。当前最窄的可辩护主张是“登记原件 + ordinary-propagation null + 同 mask/operator 干预 + 检索/版本事件回放 + fail-closed evidence route”的组合协议；它必须经 G0–G6、同 manifest 消融、时间/生成器外部切分和人工成本评测，不能由任何单项模块、p-value、digest 或合成结果单独支撑。

### 10.52 D-070：PE-CEA-v1 传播严重度包络审计

PE-CEA-v1 将 ordinary-propagation null 从一个 scalar 上界拆成多个传播严重度层级的 envelope，并对同一 source/query/counterfactual 的 paired local effect 计算整条曲线的超额面积、正向层级比例和曲线不连续性。它针对真实传播会破坏局部伪影捷径这一风险，属于传播审计 sidecar，不是新的 detector、统计理论或 AIGC 概率模型。

固定输出为 `envelope_candidate`、`null_consistent`、`curve_inconsistent`、`insufficient`。内容编辑必须有可回放的 `edit_mask_digest`；普通传播不能携带编辑标签，也不能升级为 candidate。首轮只允许无重量契约、合成 fixture 和 fail-closed 测试，真实授权图片、独立 null、wrong-reference/decoy、生成器/时间外部切分、FPR、coverage-risk、ROI、P95、成本和人工复核收益仍需 G0–G6 验证。
