# 🛡️ 智影链 (Smart Shadow) - 数字作品来源存证与视觉风险筛查平台

> **当前阶段：比赛展示已完成，项目进入持续开发。**
>
> 当前维护入口：先阅读 [AGENTS.md](AGENTS.md)，再按顺序查看 [当前任务说明](docs/00-当前任务说明.md)、[项目决策记录](docs/01-项目决策记录.md)、[项目记忆](docs/02-项目记忆.md)、[技术方案](docs/03-技术方案.md)、[实施方案](docs/04-实施方案.md)、[市场与商业化调研](docs/05-市场与商业化调研.md)、[AIGC 算法创新调研](docs/06-AIGC算法创新调研.md)、[验证与运行记录](docs/07-验证与运行记录.md)、[拓展路线](docs/08-拓展路线与商业化验证路线图.md) 和 [主要创新点](docs/09-主要创新点与可证伪主张.md)。本 README 保留比赛阶段的历史介绍；当前实现边界、验证状态和后续开发以 `docs/` 为准。

> 本轮调研入口： [第三轮研究终审与 SIPA-LG 执行入口](docs/research/2026-09-21-第三轮研究终审与SIPA-LG执行入口.md)、[持续创新与商业价值深度调研](docs/research/2026-09-21-持续创新与商业价值深度调研.md)、[市场、商业化与 AIGC 算法创新终审](docs/research/2026-09-21-市场商业化与AIGC算法创新终审.md)、[官方市场扩展审计](docs/research/2026-09-21-官方市场扩展与商业价值审计.md)、[CFAEA-v1 研究设计](docs/research/2026-09-21-CFAEA-v1研究设计.md)、[论文前沿与 AR-SCMI 白区](docs/research/2026-09-21-论文前沿深度审计与白区.md)。RSCPTN 与 ALG-001 已完成离线契约；当前先做 SS-032 真实 archive/index preparation，再做 SIPA-LG；完整 CFAEA 和 AR-SCMI 仍是条件性候选。真实 archive、授权图片、独立 null 和 G0–G6 仍待验证，商业 sidecar 仍受阶段 1–5 和客户授权数据阻塞。

> **视觉算法工作区已拆出**：AIGC/视觉算法研究现在在 [`../smart-shadow-vision-algorithm`](../smart-shadow-vision-algorithm) 独立进行。本项目只负责未来的服务落地；算法成熟后通过版本化 landing bundle 接入。

> **徽章和比赛版部署章节是历史资料。** 它们不代表当前 checkout 已完成 Go、MySQL、IPFS、Faiss、PyTorch、ChainMaker 或线上部署验证；当前唯一轻量验收入口是 `bash scripts/verify_lightweight.sh`。
>
> 当前算法研究主线：利用已登记原件做 source-conditioned 局部差异取证，输出 ROI 和可审计证据；AIGC 结果采用拒判和人工复核，`unknown` 不等于“人类创作”。

## 当前开发入口

比赛版页面、部署说明和宣传指标只保留作历史参考。后续 Agent 从
`AGENTS.md → docs/00-当前任务说明.md → docs/01-项目决策记录.md → docs/02-项目记忆.md → docs/03-技术方案.md → docs/04-实施方案.md`
开始；研究依据按需阅读 `docs/05–06` 和 `docs/research/`，运行证据只认
`docs/07-验证与运行记录.md`。

```bash
git status --short
bash scripts/verify_lightweight.sh
```

当前轻量入口最近一次为 398 个契约测试、41 个合成/契约 runner 通过；这只证明无重量模型的契约、确定性和 fail-closed 回归，不代表真实图片效果、全栈部署或商业验证。新增任务先登记到 [`docs/active-tasks/README.md`](docs/active-tasks/README.md)，再按独占文件和验收命令认领。

![ChainMaker](https://img.shields.io/badge/ChainMaker-v2.3.7-1890ff.svg)
![AI-Engine](https://img.shields.io/badge/AI_Model-CLIP_|_YOLOv8-FF9F43.svg)
![Go](https://img.shields.io/badge/Go-1.18+-00add8.svg)
![Python](https://img.shields.io/badge/Python-3.8+-green.svg)
![MySQL](https://img.shields.io/badge/MySQL-8.0+-4479A1.svg)

> **🏆 长安链开发者大赛 参赛作品**
> - **参赛赛道**：应用实践赛道 (本科生组) - 数字资产/版权保护方向
> - **演示视频**：[📺 点击观看项目功能演示视频](https://t.bilibili.com/1173916103671283720?share_source=pc_native)

## 📖 1. 项目背景与立项初衷
在 AIGC（人工智能生成内容）技术爆发的背景下，数字艺术创作繁荣的同时，也衍生出“AI 洗稿、局部截取、滤镜伪装”等新型侵权手段。传统的基于哈希比对的区块链存证方案在面对此类“非精确复制”的洗稿手段时，极易发生哈希碰撞失效，导致维权困难。

**“智影链 (Smart Shadow)”** 旨在解决这一痛点。本项目依托于**长安链 (ChainMaker)** 的高并发、高可信特性，结合 **IPFS 去中心化存储**，并创新性地提出 **“6维全息多尺度特征裂变检索算法”**，实现了数字资产从“链上铸造确权”到“跨模态侵权监测”的全生命周期保护。

---

## ✨ 2. 比赛版历史亮点（当前不作为实现结论）

本节保留比赛阶段的产品叙事，便于回看参赛版本。当前源码事实、已验证能力和继续创新方向以 [项目决策记录](docs/01-项目决策记录.md)、[技术方案](docs/03-技术方案.md)、[市场与商业化调研](docs/05-市场与商业化调研.md) 和 [AIGC 算法创新调研](docs/06-AIGC算法创新调研.md) 为准；“精准抗裁剪”“ANN”“AI/人类确定性判定”和“链上确权”等表述在完成对应实现和评测前不得对外承诺。

**警告：以下比赛亮点只用于回看参赛版本，不能作为当前源码能力、论文结果、法律结论或商业 SLA。**

### 🥇 创新一：6维全息多尺度特征裂变查重算法 (核心抗洗稿机制)
摒弃了脆弱的传统图像哈希（如感知哈希 pHash），自主研发了基于 `CLIP` 预训练模型的多模态特征提取链路。
- **切片裂变机制**：算法将单张图像动态划分为“全图、左上、右上、左下、右下、中心核心” 6 个维度，独立提取高维语义特征（512维向量），并打散存入 `Faiss` 极速向量引擎。
- **高鲁棒性拦截**：即便侵权者对图片进行**高强度裁剪、截图或添加滤镜**，只要局部语义特征命中 6 维库中的任意一环，系统即可在相似度极低（55%及以上）的视觉重合下，精准触发侵权预警。

### 🥈 创新二：AIGC 伪影侦测双引擎
融合 `YOLOv8` 目标识别与深度图像分类大模型（ResNet 变体）。系统在确权上链前，不仅能识别画面的物理实体，还能通过图像底层参数与像素分布规律，智能判定作品是“人类原创”还是由“Stable Diffusion / Midjourney 等 AI 模型生成”，遏制劣质 AI 图像污染链上生态。

### 🥉 创新三：四重混合存储架构设计
打破传统单一存储瓶颈，本项目设计了严密的**“链上+链下+关系型+向量”**四维解耦存储架构：
- **IPFS 真实物理节点 (Kubo)**：系统不仅调用外部 API，更在本地完整挂载了真实的 IPFS 守护进程（监听 5001 与 4001 P2P 端口），实现大容量非结构化图像数据的真实碎片化与去中心化存储，生成 SHA-256 密码学寻址 CID。
- **Faiss 向量库**：驻留于 AI 引擎内存中，负责海量 512 维特征的高速近似最近邻 (ANN) 检索。
- **MySQL 关系型数据库**：持久化存储用户账户状态、业务流水与元数据，保障高频业务查询。
- **长安链 ChainMaker**：仅负责将拥有者、确权时间戳、高维特征 Hash 以及 IPFS CID 进行绑定存证，大幅降低链上存储开销并提升 TPS 性能。

---

## 🛠️ 3. 比赛版系统技术栈与架构资料（历史参考）

本项目采用前后端分离与跨语言微服务架构，深度整合了区块链密码学与高维数学算法：

- **表示层 (异步前端引擎)**：
  - 基于 `HTML5` + `jQuery` 驱动。
  - 采用 **AJAX 异步请求** 与 **FormData 二进制流解析**，实现图片特征的无感上传与实时回调。
  - 视觉整合 `Vanta.js` 3D 动态引擎与 `SweetAlert2` 交互组件。
- **业务网关 (Go 高并发服务)**：
  - 采用 `Gin` 框架构建 RESTful API。
  - 利用 Go 原生 **Goroutine 协程** 机制，提供极高的并发吞吐能力。
  - 负责身份签发、跨域管理、MySQL (v5.7+) 业务数据持久化。
- **AI 算法微服务 (Python)**：
  - 基于 `FastAPI` 构建的异步微服务，搭载 `PyTorch` 框架。
  - **核心数学算法**：调用 `Faiss` 引擎执行高维空间下的 **余弦相似度计算 (Cosine Similarity)** 与极速近似最近邻 (ANN) 搜索。
- **智能合约与分布式存储底座**：
  - **智能合约生态**：基于 Go 语言编写的长效存证智能合约，参考数字资产规范定制数据结构，通过长安链官方 Go-SDK 触发跨节点交易。
  - **密码学与网络协议**：基于 **SHA-256** 防篡改哈希算法与 **Base58** 编码生成 IPFS 唯一内容标识符 (CID)；长安链底层采用 4 节点拜占庭容错 (BFT) 共识机制。

---

## 🚀 4. 比赛版部署与复现指南（历史参考，未作为当前验证）

为确保项目评审的可复现性，本团队封装了高度自动化的全栈启动流程。请依次完成以下配置：

### 4.1 基础运行环境要求
- **操作系统**: Linux / macOS / Windows WSL2 (推荐 Ubuntu 20.04+)
- **容器环境**: Docker & Docker-Compose
- **开发语言**: Go (>=1.18), Python (>=3.8)
- **数据库**: MySQL (>=5.7)
- **其他组件**: IPFS CLI (需提前执行 `ipfs init`)

### 4.2 长安链底层网络搭建 (ChainMaker 部署)
若本地尚未运行长安链节点，可通过官方最新规范部署 4 节点测试网络：

**1. 源码与证书工具下载**
```bash
# 浅克隆 chainmaker-go 源码到本地
git clone -b v2.3.7 --depth=1 [https://git.chainmaker.org.cn/chainmaker/chainmaker-go.git](https://git.chainmaker.org.cn/chainmaker/chainmaker-go.git)

# 浅克隆证书生成工具源码到本地
git clone -b v2.3.5 --depth=1 [https://git.chainmaker.org.cn/chainmaker/chainmaker-cryptogen.git](https://git.chainmaker.org.cn/chainmaker/chainmaker-cryptogen.git)
```

**2. 编译证书生成工具**
```bash
cd chainmaker-cryptogen
make
```

**3. 生成配置与启动集群**
```bash
# 将编译好的 cryptogen 软连接到 chainmaker-go 工具目录
cd ../chainmaker-go/tools
ln -s ../../chainmaker-cryptogen/ .

# 进入脚本目录，生成单链 4 节点集群的证书和配置
cd ../scripts
./prepare.sh 4 1

# 编译 chainmaker-go 模块，并打包生成安装文件
./build_release.sh

# 启动 chainmaker 节点集群
./cluster_quick_start.sh normal
```
> 💡 **依赖拉取提示**：若启动集群时遭遇 Docker 镜像拉取超时，请修改 `/etc/docker/daemon.json`，添加长安链团队自建镜像源 `"registry-mirrors": ["https://hub-dev.cnbn.org.cn"]`，并重启 Docker 服务后再次执行启动命令。


### 4.3 数据库与 AI 环境初始化
**第一步：初始化 MySQL 数据库与双核心表结构 (严格执行)**
```sql
CREATE DATABASE IF NOT EXISTS smart_shadow DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE smart_shadow;

-- 1. 创建用户权限与鉴权表
CREATE TABLE IF NOT EXISTS `users` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(64) NOT NULL UNIQUE COMMENT '登录用户名',
    `password` VARCHAR(255) NOT NULL COMMENT 'Bcrypt 哈希加密密码',
    `role` VARCHAR(20) DEFAULT 'user' COMMENT '账户角色',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户账户表';

-- 2. 创建数字资产存证核心流水表
CREATE TABLE IF NOT EXISTS `upload_histories` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(64) NOT NULL COMMENT '资产所属账户',
    `ipfs_cid` VARCHAR(100) NOT NULL COMMENT '链下 IPFS 实体文件寻址哈希',
    `tx_id` VARCHAR(100) NOT NULL COMMENT '链上 ChainMaker 交易存证哈希',
    `file_name` VARCHAR(255) COMMENT '原始上传文件名',
    `time` VARCHAR(64) COMMENT '确权铸造时间',
    `is_aigc` BOOLEAN DEFAULT FALSE COMMENT 'AI引擎侦测结果',
    `note` VARCHAR(255) COMMENT '作品备注/名称',
    `ai_object` VARCHAR(64) COMMENT 'AI视觉识别的主体内容',
    INDEX `idx_username` (`username`),
    INDEX `idx_cid` (`ipfs_cid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数字资产存证核心流水表';
```

**第二步：配置 Go 后端数据源（比赛版历史示例）**
不要把账号、密码或证书写入文档或源码。阶段 5 的目标写法是通过环境变量提供 DSN；当前比赛版 `server.go` 仍保留历史硬编码，尚未完成这项迁移：
```go
dsn := os.Getenv("SMART_SHADOW_DSN")
```
示例值只应在本机未提交的环境文件中设置，例如
`SMART_SHADOW_DSN='user:password@tcp(127.0.0.1:3306)/smart_shadow?charset=utf8mb4&parseTime=True&loc=Local'`。

**第三步：配置 Python 虚拟环境与安装依赖 (重要)**
为防止依赖冲突，请务必在隔离的虚拟环境中安装算法组件：
```bash
# 1. 创建名为 venv 的虚拟环境
python3 -m venv venv

# 2. 激活虚拟环境
source venv/bin/activate  # Linux / macOS 用户
# venv\Scripts\activate   # Windows 用户

# 3. 在隔离环境中安装底层算法依赖
pip install torch torchvision transformers faiss-cpu ultralytics fastapi uvicorn pillow opencv-python numpy scipy
```

### 4.4 智能合约编译与部署 (关键步骤)
本系统根目录下已集成了自动部署脚本 `deploy_contract.go`。
若需手动重新编译与部署，请执行以下流程：

**1. 编译合约为 7z 压缩包**
进入项目 `contract/` 目录，编译 Go 合约主体：
```bash
cd contract
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o fact main.go
7z a fact.7z fact
```

**2. 部署合约至区块链**
退回项目根目录，通过本系统内建的 Go 部署脚本将合约（名称：`fact`）发布上链：
```bash
# 将新生成的证书目录放到本机未提交的路径，并通过环境变量提供位置
export SMART_SHADOW_CRYPTO_CONFIG="/path/to/crypto-config"

# 再次尝试部署合约
cd /path/to/smart-shadow
go run deploy_contract.go
```
*(同时支持通过长安链 CMC 命令行工具或 Web 管理控制台进行图形化部署)*

### 4.5 一键点火启动全栈系统
赋予自动化脚本执行权限并启动：
```bash
chmod +x start_all.sh
./start_all.sh
```
**启动时序说明：**
1. 唤醒本地 IPFS Daemon，开启 `8080` 端口用于去中心化图片极速回显。
2.后台静默拉起 Python AI 算法服务器 (挂载于 `5000` 端口)。
3. 编译并拉起 `server.go` 核心网关（自动加载 `cm_client.go` 连接底层区块链）。
4. 控制台输出 `>>> 智影链 V3.0 服务启动: http://localhost:8088` 时，代表服务完全启动。

---

## 💻 5. 比赛版操作路径（历史演示，不是当前验收）

以下步骤只用于回看比赛演示。当前检索阈值、AIGC 结果和部署状态必须按 `docs/` 与 `eval/` 的验证记录判断，不能根据页面提示或历史百分比作为效果证明。

为了直观体验本系统的抗裁剪查重能力，建议评委按以下流程进行体验：

1. **作品铸造 (上链体验)**
   - 访问 `http://localhost:8088` 进入智影链工作台。
   - 切换至**「作品确权」**，上传一张任意尺寸的原图并点击“立即上链”。系统将调用模型对图片进行 6 维裂变切片分析，落库 MySQL 并返回上链确权 TXID。
2. **高强度破坏性侵权监测 (亮点体验)**
   - 切换至**「侵权扫描」**。
   - ⚠️ **操作建议**：请勿直接上传原图。请将刚才上链的图片进行**极端局部截图**（例如仅保留左上角的局部画面）。
   - 上传该局部截图进行比对。系统依然能从庞大的高维特征库中产生向量共鸣，精准展示 55%~90% 的相似度，并弹出橙红色的版权风险预警框。
3. **我的数字资产库**
   - 切换至**「我的作品」**，通过 MySQL 极速拉取历史流水，并秒级加载本地 IPFS 节点映射的图片资源，核对每张作品的长效存证状态。

---

## 📁 6. 当前目录结构导读

```text
📦 smart-shadow
 ┣ 📂 docs/                 # 项目记忆、决策、技术/实施方案、调研和验证记录
 ┃ ┣ 📜 README.md           # agent 阅读顺序和文档维护约定
 ┃ ┣ 📜 00-当前任务说明.md  # 当前工作目标和执行顺序
 ┃ ┣ 📜 01-项目决策记录.md  # 已确认的产品和技术决策（SSOT）
 ┃ ┣ 📜 02-项目记忆.md      # 当前事实、风险、验证边界
 ┃ ┣ 📜 03-技术方案.md      # 目标架构、接口、数据和可靠性约束
 ┃ ┣ 📜 04-实施方案.md      # 分阶段任务、验收标准和推进顺序
 ┃ ┣ 📜 05-市场与商业化调研.md # 客户、竞品、合规和商业假设
 ┃ ┣ 📜 06-AIGC算法创新调研.md  # 论文证据、研究假设和 A0–A11
 ┃ ┣ 📜 07-验证与运行记录.md    # 可重复命令、结果和未验证边界
 ┃ ┣ 📜 08-拓展路线与商业化验证路线图.md # 市场、论文、算法和 12 周执行顺序
 ┃ ┣ 📜 09-主要创新点与可证伪主张.md # 主要创新候选、prior-art 边界和验证门
 ┃ ┣ 📂 active-tasks/           # Agent 任务认领和状态；完整队列只看其中的 README
 ┃ ┃ ┗ 📜 README.md
 ┃ ┣ 📂 research/               # 外部来源索引；完整清单和证据等级只看其中的 README
 ┃ ┃ ┗ 📜 README.md
 ┃ ┗ 📂 templates/              # agent 任务、代码切片和研究评测记录模板
 ┃   ┣ 📜 agent任务单模板.md
 ┃   ┣ 📜 代码切片记录模板.md
 ┃   ┗ 📜 研究评测记录模板.md
 ┣ 📂 aigc/                 # AIGC 结果契约、来源证据、PC-SCFT/SCTE/MPCF/Crop-Consensus、DAG 审计和 A9 顺序取证
 ┣ 📂 eval/                 # 评测 manifest 约定与合成/契约 runner（不含第三方图片）
 ┃ ┣ 📜 README.md           # manifest、评测矩阵和 runner 说明
 ┃ ┗ 📜 manifest.example.jsonl # 可公开的最小 manifest 示例
 ┣ 📂 tests/                # 无重量模型依赖的核心契约测试
 ┣ 📂 scripts/              # 新 agent 可直接运行的轻量验证入口
 ┃ ┗ 📜 verify_lightweight.sh # 统一测试、语法、manifest、runner 和文档卫生检查
 ┣ 📂 contract/              # 智能合约源码层
 ┃ ┣ 📜 main.go              # 核心合约代码 (资产注册、指纹核验)
 ┃ ┗ 📜 go.mod               # 合约层依赖清单
 ┣ 📂 templates/             # 比赛版前端 UI 与视图层
 ┣ 📜 server.go              # Web 网关主入口 (Gin + MySQL)
 ┣ 📜 cm_client.go           # 链上交互层 (封装长安链 Go-SDK 接口)
 ┣ 📜 deploy_contract.go     # 比赛版合约部署脚本
 ┣ 📜 sdk_config.yml         # 比赛版 ChainMaker SDK 配置模板
 ┣ 📜 go.mod                 # Go 网关依赖清单
 ┣ 📜 ai_server.py           # 比赛版 AI 算法微服务入口
 ┣ 📜 super_algo.py          # 比赛版 CLIP 六区域指纹实现
 ┣ 📜 start_all.sh           # 比赛版全栈启动脚本
 ┣ 📜 sdk_interface.md      # 比赛版 ChainMaker SDK 接口参考
 ┣ 📜 requirements-research.txt # 研究 adapter 的最小锁定依赖
 ┣ 📜 .gitignore             # 凭据、运行时和实验产物忽略规则
 ┣ 📜 README.md              # 项目对外说明和历史比赛资料入口
 ┗ 📜 AGENTS.md              # agent 协作入口和文档优先级
```

真实图片契约 runner 的入口是 `aigc/model_adapter.py`、`aigc/real_image_runner.py` 和
`eval/pc_scft_real_image_eval.py`。它们支持授权图片输入所需的哈希、解码、配对和
`source-residual-v1` raw evidence 契约；当前验证仍是合成文件和无独立 null 时的
fail-closed 路由，真实授权 manifest、真实模型、独立校准和线上接入均未完成。

比赛环境可能额外提供以下不应提交到仓库的运行时文件：

```text
crypto-config/               # 长安链节点证书与用户私钥
contract/fact.7z             # 编译封装的合约发布包
faiss.index / faiss_meta.pkl # 可重建的本地向量索引
```

仓库中保留的比赛资产包括 `yolov8n.pt` 和 `演示视频/`；它们用于回看比赛版本，不属于当前契约测试或生产部署的验证依据。

历史比赛代码仍保留在以下文件中，新增能力应优先放入 `aigc/` 并同步更新 `docs/`：

```text
templates/                   # 比赛版前端 UI
server.go                    # 比赛版业务网关
cm_client.go                 # 比赛版链上交互
ai_server.py                 # 比赛版 AI 服务
super_algo.py                # 比赛版算法实现
start_all.sh                 # 比赛版服务编排
```


## 📄 7. 开源声明
当前 checkout 尚未包含正式的开源许可证文件，许可状态待项目维护者补齐确认。项目中部分深度学习依赖模型（如 YOLO、CLIP）遵循其原生开源组织协议。
