"""OpenMemo 配置管理"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

# AI Configuration
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://yuanyuaicloud.cn/v1")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "glm-5.2")

# Tavily 搜索（用于 NEWS_JOB 实时新闻；密钥复用 OpenClaw 的配置）
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "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")
TAVILY_BASE_URL = os.getenv("TAVILY_BASE_URL", "https://api.tavily.com")

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
