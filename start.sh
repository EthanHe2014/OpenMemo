#!/bin/bash
#
# OpenMemo 一键启动脚本 (One-Command Bootstrap)
# =============================================
# 使用方法:  ./start.sh
#
# 只需这一个命令, 它自动完成:
#   1. 检查 Python 版本
#   2. 创建虚拟环境  .venv          (不存在才建)
#   3. 安装全部依赖  requirements.txt
#   4. 生成配置文件  .env           (不存在才从 .env.example 复制)
#   5. 启动后端服务   (FastAPI + 调度器, 端口 18890)
#
# 无需手动建数据库——服务首次启动会自动创建 data/openmemo.db
# 无需手动装依赖——本脚本全自动。
#
set -e

cd "$(dirname "$0")"

# 颜色
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
say()  { echo -e "${GREEN}==>${NC} $1"; }
warn() { echo -e "${YELLOW}!! ${NC} $1"; }
die()  { echo -e "${RED}!! ${NC} $1"; exit 1; }

# ─── 1. 检查 Python ─────────────────────────────────────────────
PY=python3
command -v "$PY" >/dev/null 2>&1 || die "未找到 python3, 请先安装 Python 3.10+"
py_ver=$("$PY" -c 'import sys;print(".".join(map(str,sys.version_info[:2])))')
say "检测到 Python ${py_ver}"

# ─── 2. 创建虚拟环境 ────────────────────────────────────────────
if [ ! -d .venv ]; then
    say "首次运行: 创建虚拟环境 .venv ..."
    "$PY" -m venv .venv || die "创建虚拟环境失败"
else
    say "虚拟环境已存在, 跳过创建"
fi
source .venv/bin/activate

# ─── 3. 安装依赖 ────────────────────────────────────────────────
if [ ! -f requirements.txt ]; then
    die "缺少 requirements.txt"
fi
# 用 .installed_marker 避免每次重复 pip install
MARKER=".venv/.installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
    say "安装依赖 (可能需要一两分钟) ..."
    python -m pip install --quiet --upgrade pip
    python -m pip install --quiet -r requirements.txt
    touch "$MARKER"
    say "依赖安装完成"
else
    say "依赖已安装, 跳过"
fi

# ─── 4. 生成配置文件 ────────────────────────────────────────────
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        say "未找到 .env, 已从 .env.example 生成模板"
        cp .env.example .env
        warn "请编辑 .env, 填入你的 AI_API_KEY (以及飞书/其他渠道凭据)"
    else
        warn "缺少 .env.example, 跳过配置生成 (服务可能无法连接 AI)"
    fi
else
    say ".env 已存在, 跳过生成"
fi

# ─── 5. 启动服务 ────────────────────────────────────────────────
say "启动 OpenMemo 服务 (端口 18890) ..."
say "停止: 按 Ctrl+C"
exec python -m openmemo.server
