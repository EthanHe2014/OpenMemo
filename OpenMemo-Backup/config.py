"""OpenMemo 配置管理（纯环境变量驱动，无任何硬编码密钥/模型/地址）"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

# AI Configuration —— 只从环境变量读取；不配置/不填值时返回空，绝不内置默认模型或默认地址。
AI_BASE_URL = os.getenv("AI_BASE_URL", "")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")

# 搜索（NEWS_JOB 实时新闻用）：纯环境变量驱动，无默认提供商、无默认密钥、无默认地址。
# SEARCH_PROVIDER ∈ {tavily, brave, serper, custom}；为空或 SEARCH_API_KEY 为空 = 不启用外部搜索，新闻由 AI 生成。
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
SEARCH_BASE_URL = os.getenv("SEARCH_BASE_URL", "")

# (钉钉 / 企业微信 / 飞书 等渠道已移除，纯 App 使用)

# Server Configuration
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "18890"))

# TTS Configuration
TTS_VOICE = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")

# Data Configuration
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "openmemo.db"
AUDIO_DIR = DATA_DIR / "audio"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)
