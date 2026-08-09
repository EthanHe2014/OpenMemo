#!/bin/bash
#
# OpenMemo 一键启动 —— 就这一条命令，别的都不用你管
# =====================================================
# 用法:  ./start.sh
#
# 自动完成:
#   1. 检查 Python 3.10+
#   2. 创建虚拟环境 .venv（不存在才建）
#   3. 安装全部依赖 requirements.txt
#   4. 配置：若还没配好 AI 接口，自动进入【交互式设置向导】(setup.py)
#       只需回答几个问题（AI 地址/密钥/模型/偏好），密钥不会回显
#   5. 启动后端服务（FastAPI + 调提醒度器，端口默认 18890）
#
# 无需手动建库（首次启动自动建 data/openmemo.db）
# 无需手动改文件（配置都在向导里完成）
#
set -e

cd "$(dirname "$0")"

# 颜色
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
say()  { echo -e "${GREEN}==>${NC} $1"; }
warn() { echo -e "${YELLOW}!! ${NC} $1"; }
die()  { echo -e "${RED}!! ${NC} $1"; exit 1; }

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  OpenMemo 一键启动${NC}"
echo -e "${CYAN}========================================${NC}"

# ─── 1. 检查 Python ─────────────────────────────────────────────
PY=python3
command -v "$PY" >/dev/null 2>&1 || die "未找到 python3，请先安装 Python 3.10+"
py_ver=$("$PY" -c 'import sys;print(".".join(map(str,sys.version_info[:2])))')
# 至少 3.10
IFS='.' read -r MAJ MIN <<< "$py_ver"
if [ "$MAJ" -lt 3 ] || { [ "$MAJ" -eq 3 ] && [ "$MIN" -lt 10 ]; }; then
    die "Python 版本过低（$py_ver），需要 3.10+"
fi
say "检测到 Python ${py_ver}"

# ─── 2. 创建虚拟环境 ────────────────────────────────────────────
if [ ! -d .venv ]; then
    say "首次运行：创建虚拟环境 .venv ..."
    "$PY" -m venv .venv || die "创建虚拟环境失败"
else
    say "虚拟环境已存在，跳过创建"
fi
source .venv/bin/activate

# ─── 3. 安装依赖 ────────────────────────────────────────────────
[ -f requirements.txt ] || die "缺少 requirements.txt"
MARKER=".venv/.installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
    say "安装依赖（可能需要一两分钟）..."
    python -m pip install --quiet --upgrade pip 2>/dev/null || true
    python -m pip install --quiet -r requirements.txt
    touch "$MARKER"
    say "依赖安装完成"
else
    say "依赖已安装，跳过"
fi

# ─── 4. 配置（缺失或未填必填项 → 自动进入设置向导）──────────────
# 判断是否已正确配置：.env 存在且三大必填项都有值
needs_setup=0
if [ ! -f .env ]; then
    warn "尚未配置。即将进入设置向导..."
    needs_setup=1
else
    # 从 .env 读取三大必填项（空值 = 未配置）
    has_all=1
    for key in AI_BASE_URL AI_API_KEY AI_MODEL; do
        val=$(grep -E "^${key}=" .env | head -1 | cut -d'=' -f2- | tr -d '[:space:]')
        if [ -z "$val" ] || [ "$val" = "your-api-key-here" ]; then
            has_all=0
        fi
    done
    if [ "$has_all" -eq 0 ]; then
        warn "检测到 AI 接口尚未完整配置，进入设置向导..."
        needs_setup=1
    fi
fi

if [ "$needs_setup" -eq 1 ]; then
    python setup.py || die "配置未完成，请重跑 ./start.sh"
    say "配置完成 ✓"
fi

# ─── 5. 启动服务 ────────────────────────────────────────────────
say "启动 OpenMemo 服务（端口 $(grep -E '^SERVER_PORT=' .env 2>/dev/null | cut -d'=' -f2 | tr -d '[:space:]' || echo 18890)）..."
say "停止: 按 Ctrl+C"
exec python -m openmemo.server
