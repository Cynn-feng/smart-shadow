#!/bin/bash

# ================= 配置区域 =================
PROJECT_DIR="/mnt/f/Code/smart-shadow"
CHAIN_SCRIPTS_DIR="/mnt/f/Code/chainmaker-go/scripts"
CHAIN_BUILD_DIR="/mnt/f/Code/chainmaker-go/build/release"
CHAIN_VERSION="v2.3.7"

# 👇 【新增】在这里填写你虚拟环境的 Python 执行文件的相对或绝对路径
# 常见例子： "venv/bin/python" 或 ".venv/bin/python" 或 "env/bin/python"
PYTHON_EXEC="venv/bin/python" 

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}   🚀 智影链 (Smart Shadow) 全栈启动程序 v1.6   ${NC}"
echo -e "${BLUE}   集成: 4节点共识链 + IPFS + AI引擎 + Go后端   ${NC}"
echo -e "${BLUE}=================================================${NC}"

# ================= 0. 定义清理函数 =================
cleanup() {
    echo ""
    echo -e "${RED}>>> 🛑 检测到退出信号，正在清理所有服务...${NC}"
    
    # 1. 清理 IPFS 和 Python AI 进程
    if [ -n "$IPFS_PID" ]; then kill -9 $IPFS_PID 2>/dev/null; fi
    if [ -n "$PY_PID" ]; then kill -9 $PY_PID 2>/dev/null; fi

    # 2. 强杀 Go 后端进程，彻底释放 8088 端口
    echo -e "${RED}>>> 正在释放 8088 端口并关闭 Go 后端...${NC}"
    fuser -k -9 8088/tcp >/dev/null 2>&1
    pkill -f "server.go" >/dev/null 2>&1

    # 3. 停止 4 个真实区块链节点 (采用官方安全停止脚本)
    echo -e "${RED}>>> 正在停止 4 个区块链节点...${NC}"
    cd "$CHAIN_SCRIPTS_DIR" && ./cluster_quick_stop.sh >/dev/null 2>&1

    echo -e "${GREEN}>>> 👋 系统已彻底清理并安全关闭！${NC}"
    exit
}
# 捕获 Ctrl+C (SIGINT) 和 kill 信号 (TERM)
trap cleanup SIGINT TERM

# ================= 1. 启动 4 节点共识集群 =================
echo -e "${BLUE}[1/4] 正在唤醒 4 节点拜占庭容错集群...${NC}"

# 使用官方启动脚本代替原来的 for 循环，彻底解决卡死问题
cd "$CHAIN_SCRIPTS_DIR"
./cluster_quick_start.sh normal >/dev/null 2>&1

sleep 3
if ps -ef | grep "chainmaker" | grep "wx-org1" > /dev/null; then
    echo -e "${GREEN}>>> ✅ 区块链集群启动成功 (Nodes: 4/4)${NC}"
else
    echo -e "${RED}>>> ❌ 链启动失败，请手动检查日志${NC}"
    exit 1
fi

# ================= 2. 启动 IPFS =================
echo -e "${BLUE}[2/4] 正在启动 IPFS...${NC}"
ipfs daemon > /dev/null 2>&1 &
IPFS_PID=$!
echo -e "${GREEN}>>> ✅ IPFS 已运行 (PID: $IPFS_PID)${NC}"

# ================= 3. 启动 AI 引擎 =================
echo -e "${BLUE}[3/4] 正在启动 AI 引擎...${NC}"
cd "$PROJECT_DIR"

# 检查配置的 Python 解释器是否存在
if [ ! -f "$PYTHON_EXEC" ]; then
    echo -e "${RED}>>> ❌ 找不到虚拟环境的 Python: $PYTHON_EXEC ${NC}"
    echo -e "${RED}>>> 请检查脚本顶部的 PYTHON_EXEC 路径是否正确！${NC}"
    exit 1
fi

# 直接使用虚拟环境的 Python 执行
nohup $PYTHON_EXEC ai_server.py > ai_server.log 2>&1 &
PY_PID=$!

echo -n ">>> 等待 AI 加载 (可能需要下载模型，请耐心) "
# 稍微增加一点等待时间，以防模型加载慢
for i in {1..5}; do echo -n "."; sleep 1; done
echo ""
echo -e "${GREEN}>>> ✅ AI 服务启动指令已发送 (PID: $PY_PID)${NC}"
echo -e "${BLUE}>>> 💡 提示: 如果前端依然报 5000 端口错误，请查看 ai_server.log 日志文件找出报错原因。${NC}"

# ================= 4. 启动 Go 后端 =================
echo -e "${BLUE}[4/4] 正在启动 Go 后端...${NC}"
echo -e "${GREEN}>>> 🎉 系统就绪: http://localhost:8088${NC}"
echo "-----------------------------------------------------"

go run server.go cm_client.go
