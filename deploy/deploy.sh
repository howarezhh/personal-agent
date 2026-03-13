#!/bin/bash

# ============================================
# 企业级多Agent知识库助手 - 部署脚本
# ============================================

set -e  # 遇到错误立即退出

echo "=========================================="
echo "开始部署企业级多Agent知识库助手"
echo "=========================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查环境变量文件
if [ ! -f .env ]; then
    echo -e "${RED}错误: .env文件不存在${NC}"
    echo "请复制.env.example并配置环境变量"
    exit 1
fi

# 加载环境变量
source .env

# 检查必需的环境变量
required_vars=("JWT_SECRET_KEY" "DATABASE_PASSWORD" "OPENAI_API_KEY")
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo -e "${RED}错误: 环境变量 $var 未设置${NC}"
        exit 1
    fi
done

echo -e "${GREEN}✓ 环境变量检查通过${NC}"

# 检查Docker是否安装
if ! command -v docker &> /dev/null; then
    echo -e "${RED}错误: Docker未安装${NC}"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}错误: Docker Compose未安装${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker环境检查通过${NC}"

# 创建必要的目录
echo "创建必要的目录..."
mkdir -p logs data/uploads chroma_db deploy

# 停止现有容器
echo "停止现有容器..."
docker-compose down

# 构建镜像
echo "构建Docker镜像..."
docker-compose build

# 启动服务
echo "启动服务..."
docker-compose up -d

# 等待服务启动
echo "等待服务启动..."
sleep 10

# 检查服务状态
echo "检查服务状态..."
docker-compose ps

# 检查后端健康状态
echo "检查后端健康状态..."
max_retries=30
retry_count=0

while [ $retry_count -lt $max_retries ]; do
    if curl -f http://localhost:8000/health &> /dev/null; then
        echo -e "${GREEN}✓ 后端服务启动成功${NC}"
        break
    fi

    retry_count=$((retry_count + 1))
    echo "等待后端服务启动... ($retry_count/$max_retries)"
    sleep 2
done

if [ $retry_count -eq $max_retries ]; then
    echo -e "${RED}错误: 后端服务启动失败${NC}"
    echo "查看日志:"
    docker-compose logs backend
    exit 1
fi

# 显示访问信息
echo ""
echo "=========================================="
echo -e "${GREEN}部署成功！${NC}"
echo "=========================================="
echo ""
echo "服务访问地址:"
echo "  - 后端API: http://localhost:8000"
echo "  - API文档: http://localhost:8000/docs"
echo "  - Prometheus: http://localhost:9090"
echo "  - Grafana: http://localhost:3000 (默认密码: admin)"
echo ""
echo "查看日志:"
echo "  docker-compose logs -f backend"
echo ""
echo "停止服务:"
echo "  docker-compose down"
echo ""
echo "=========================================="
