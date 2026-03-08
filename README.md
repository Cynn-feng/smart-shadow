# 🛡️ 智影链 (Smart Shadow) - 跨模态数字资产保护与全生命周期存证平台

![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)
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

## ✨ 2. 核心创新点 (亮点特色)

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

## 🛠️ 3. 系统核心技术栈与架构设计

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

## 🚀 4. 快速部署与复现指南 (评委审阅专用)

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

**第二步：配置 Go 后端数据源**
在 `server.go` 中，确认 `initDB()` 函数内的 DSN 与本地 MySQL 匹配：
```go
dsn := "root:123456@tcp(127.0.0.1:3306)/smart_shadow?charset=utf8mb4&parseTime=True&loc=Local"
```

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
# 将新生成的证书目录完整复制到你的项目下
cp -r /mnt/f/Code/chainmaker-go/build/crypto-config /mnt/f/Code/smart-shadow/

# 再次尝试部署合约
cd /mnt/f/Code/smart-shadow
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

## 💻 5. 核心操作路径与测试建议

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

## 📁 6. 核心目录结构导读

```text
📦 smart-shadow
 ┣ 📂 contract/              # 智能合约源码层
 ┃ ┣ 📜 main.go              # 核心合约代码 (资产注册、指纹核验)
 ┃ ┣ 📜 go.mod               # 合约层依赖清单
 ┃ ┗ 📦 fact.7z              # 编译封装的合约发布包
 ┣ 📂 crypto-config/         # 长安链节点证书与用户私钥目录
 ┣ 📂 templates/             # 前端 UI 与视图层
 ┃ ┣ 📜 index.html           # 门面引导与功能分流
 ┃ ┣ 📜 login.html           # 授权验证页
 ┃ ┣ 📜 landing.html         # 核心落地介绍页
 ┃ ┗ 📜 dashboard.html       # 智影链业务操作工作台
 ┣ 📜 server.go              # Web 网关主入口 (Gin + MySQL)
 ┣ 📜 cm_client.go           # 链上交互层 (封装长安链 Go-SDK 接口)
 ┣ 📜 deploy_contract.go     # 合约自动化生命周期管理脚本
 ┣ 📜 sdk_config.yml         # 长安链 SDK 网络连接与多签配置
 ┣ 📜 ai_server.py           # AI 算法微服务引擎 (FastAPI 驱动)
 ┣ 📜 super_algo.py          # 核心算法实现 (AIGC 分析 & 6维切片特征)
 ┣ 📜 yolov8n.pt             # YOLOv8 预训练网络权重底座 (本地化免下载)
 ┣ 📜 go.mod                 # 业务网关依赖清单
 ┣ 📜 ipfs.log               # IPFS 分布式网络节点运行日志 (真实去中心化存储凭证)
 ┣ 📜 sdk.log                # 长安链底层网络跨节点共识与交易通讯日志
 ┗ 📜 start_all.sh           # 全栈级服务编排与环境启动脚本
```

## 📄 7. 开源声明
本项目代码及相关算法遵循 [Apache License 2.0](LICENSE) 协议开源。项目中部分深度学习依赖模型（如 YOLO、CLIP）遵循其原生开源组织协议。
