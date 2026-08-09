#!/usr/bin/env python3
"""OpenMemo 交互式配置向导 (Setup Wizard)

用法:
    python setup.py         首次配置/修改配置
    python setup.py --reset 清空旧值，从零配

作用:
    通过问答式向导，引导你选择 AI 提供商（OpenAI / DeepSeek / 智谱 / Moonshot /
    Ollama / 自定义）、搜索提供商（Tavily / Brave / Serper / 自定义 / 不配置），
    并把所有配置写入 .env 文件。全程无需手改任何文件。

原则:
    - 不内置任何默认模型、默认密钥、默认接口地址 —— 每个值都由你填写/选择。
    - 向导本身不联网、不泄露密钥。
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
EXAMPLE_FILE = BASE_DIR / ".env.example"

# ── AI 提供商预设（仅提供公开的官方接口地址作为"预填"，可修改；模型名/密钥永远要你填）──
AI_PROVIDERS = [
    ("OpenAI",          "https://api.openai.com/v1"),
    ("DeepSeek",        "https://api.deepseek.com/v1"),
    ("智谱 AI (GLM)",    "https://open.bigmodel.cn/api/paas/v4"),
    ("Moonshot (Kimi)", "https://api.moonshot.cn/v1"),
    ("Ollama (本地)",    "http://localhost:11434/v1"),
    ("自定义 / 其他",    ""),
]

# ── 搜索提供商预设（每日新闻用；同样只预填公开地址，密钥永远要你填）──
SEARCH_PROVIDERS = [
    ("不配置（新闻由 AI 生成）", ""),
    ("Tavily",   "https://api.tavily.com"),
    ("Brave",    "https://api.search.brave.com/res/v1"),
    ("Serper",   "https://google.serper.dev"),
    ("自定义 / 其他", ""),
]


def load_existing() -> dict:
    """读取现有 .env（若存在），并迁移旧版 TAVILY_* 配置到新的 SEARCH_* 键。"""
    vals: dict = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()
    # 旧版迁移：TAVILY_API_KEY → SEARCH_API_KEY（provider 置为 tavily）
    if not vals.get("SEARCH_API_KEY") and vals.get("TAVILY_API_KEY"):
        vals["SEARCH_API_KEY"] = vals["TAVILY_API_KEY"]
        vals["SEARCH_PROVIDER"] = "tavily"
        vals.setdefault("SEARCH_BASE_URL", "https://api.tavily.com")
    return vals


def ask(prompt: str, current: str = "", secret: bool = False,
        optional: bool = False, validate=None) -> str:
    """带默认值/掩码/校验的交互式提问。"""
    from getpass import getpass

    hint = ""
    if optional:
        hint = " [可留空]"
    if current:
        shown = "****" if secret else current
        hint += f" (当前: {shown})"

    while True:
        if secret:
            raw = getpass(f"{prompt}{hint}: ").strip()
        else:
            raw = input(f"{prompt}{hint}: ").strip()

        # 留空 = 保留旧值；没有旧值且可选的 = 空字符串
        if not raw:
            return current if current else ("" if optional else None)
        if validate:
            err = validate(raw)
            if err:
                print(f"   ✗ {err}")
                continue
        return raw


def choose(prompt: str, options: list, default_index: int = 0) -> int:
    """数字菜单选择。返回选中的下标。"""
    print(f"\n{prompt}")
    for i, (name, _) in enumerate(options, 1):
        print(f"  {i}. {name}")
    while True:
        raw = input(f"请输入数字 1-{len(options)} (当前: {default_index + 1}): ").strip()
        if not raw:
            return default_index
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(f"   ✗ 请输入 1-{len(options)} 之间的数字")


def validate_port(v: str):
    if not v.isdigit() or not (1 <= int(v) <= 65535):
        return "端口需为 1-65535 的整数"
    return None


def main():
    reset = "--reset" in sys.argv
    existing = {} if reset else load_existing()

    print("=" * 52)
    print("  OpenMemo 配置向导")
    print("  选择你的 AI 提供商与搜索服务，全程无需改文件")
    print("=" * 52)
    print("(直接回车 = 保留当前值；密钥输入不回显)")
    print()

    # ── 1. AI 提供商 ─────────────────────────────────────────
    print("【1/3】AI 提供商（必选 — 任意 OpenAI 兼容服务都可以）")
    ai_names = [n for n, _ in AI_PROVIDERS]
    cur_base = existing.get("AI_BASE_URL", "")
    cur_idx = 0
    # 若已有配置，尝试按 BaseURL 匹配预设
    for i, (_, url) in enumerate(AI_PROVIDERS):
        if url and cur_base and cur_base.rstrip("/").lower() == url.rstrip("/").lower():
            cur_idx = i
            break
    ai_idx = choose("选择你的 AI 提供商：", AI_PROVIDERS, cur_idx)
    ai_name, preset_url = AI_PROVIDERS[ai_idx]

    if preset_url and (not cur_base or ai_idx != cur_idx):
        print(f"  已选择 {ai_name}，接口地址预填为 {preset_url}（可直接回车确认，也可修改）")
        base_url = input(f"  AI 接口地址 (BaseURL) [{preset_url}]: ").strip() or preset_url
    else:
        base_url = ask("  AI 接口地址 (BaseURL)", cur_base)

    is_local = ai_name.startswith("Ollama")
    if is_local:
        print("  （Ollama 本地模型通常不需要密钥，可直接回车跳过）")
        api_key = ask("  AI 接口密钥 (API Key)", existing.get("AI_API_KEY", ""),
                      secret=True, optional=True)
    else:
        api_key = ask("  AI 接口密钥 (API Key)", existing.get("AI_API_KEY", ""),
                      secret=True)
    model = ask("  AI 模型名 (Model，例如 gpt-4o-mini / deepseek-chat，无默认值)",
                existing.get("AI_MODEL", ""))
    print()

    # ── 2. 搜索提供商（每日新闻）─────────────────────────────
    print("【2/3】新闻搜索服务（可选 — 仅做『每日新闻』任务时需要）")
    cur_search = existing.get("SEARCH_PROVIDER", "")
    search_idx = 0
    for i, (name, _) in enumerate(SEARCH_PROVIDERS):
        if name == cur_search or (cur_search and name == "自定义 / 其他" and cur_search == "custom"):
            search_idx = i
            break
    s_idx = choose("选择新闻搜索服务：", SEARCH_PROVIDERS, search_idx)
    s_name, s_preset = SEARCH_PROVIDERS[s_idx]
    if s_idx == 0:
        search_provider = ""
        search_key = ""
        search_url = ""
        print("  已选择不配置 —— 每日新闻任务将由 AI 直接生成内容。")
    else:
        search_provider = "custom" if s_idx == len(SEARCH_PROVIDERS) - 1 else s_name.lower()
        search_key = ask(f"  {s_name} 搜索密钥 (API Key)", existing.get("SEARCH_API_KEY", ""),
                         secret=True, optional=True)
        if search_key:
            if s_preset and existing.get("SEARCH_BASE_URL", "").strip() != s_preset:
                print(f"  接口地址预填为 {s_preset}（可直接回车确认，也可修改）")
                url_in = input(f"  搜索接口地址 (BaseURL) [{s_preset}]: ").strip()
                search_url = url_in or s_preset
            else:
                search_url = ask("  搜索接口地址 (BaseURL)", existing.get("SEARCH_BASE_URL", ""))
    print()

    # ── 3. 偏好 ──────────────────────────────────────────────
    print("【3/3】偏好设置")
    host = ask("  服务监听地址", existing.get("SERVER_HOST", "0.0.0.0"))
    port = ask("  服务端口", existing.get("SERVER_PORT", "18890"),
               validate=validate_port)
    voice = ask("  语音音色 (edge-tts，如 zh-CN-XiaoxiaoNeural)",
                existing.get("TTS_VOICE", "zh-CN-XiaoxiaoNeural"))
    print()

    # ── 校验必填项 ──────────────────────────────────────────
    missing = []
    if not base_url:
        missing.append("AI_BASE_URL")
    if not is_local and not api_key:
        missing.append("AI_API_KEY")
    if not model:
        missing.append("AI_MODEL")
    if missing:
        print("✗ 以下必填项缺失，无法继续：", "、".join(missing))
        print("  请重新运行，或编辑 .env 手动补上。")
        sys.exit(1)

    # ── 写 .env ─────────────────────────────────────────────
    lines = [
        "# OpenMemo Configuration (由 setup.py 生成)",
        "",
        "# AI Endpoint（你选择的提供商；BaseURL + API Key + 模型名，均必填，无默认值）",
        f"AI_BASE_URL={base_url}",
        f"AI_API_KEY={api_key}",
        f"AI_MODEL={model}",
        "",
        "# 搜索（可选，NEWS_JOB 每日新闻用；SEARCH_PROVIDER 为空或密钥为空 = 不启用外部搜索）",
        f"SEARCH_PROVIDER={search_provider}",
        f"SEARCH_API_KEY={search_key}",
        f"SEARCH_BASE_URL={search_url}",
        "",
        "# Server",
        f"SERVER_HOST={host}",
        f"SERVER_PORT={port}",
        "",
        "# TTS",
        f"TTS_VOICE={voice}",
        "",
        "# Data",
        "DATA_DIR=./data",
        "DB_PATH=./data/openmemo.db",
        "AUDIO_DIR=./data/audio",
        "",
    ]
    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")

    print("✓ 已写入 .env")
    print(f"  - AI 提供商: {ai_name}")
    print(f"  - AI 接口:   {base_url}")
    print(f"  - 模型:      {model}")
    print(f"  - 端口:      {port}")
    if search_provider and search_key:
        print(f"  - 搜索:      {search_provider} ({search_url})")
    else:
        print("  - 搜索:      未配置（每日新闻任务将用 AI 生成内容）")
    print()
    print("现在运行  ./start.sh  即可启动服务。")


if __name__ == "__main__":
    main()
