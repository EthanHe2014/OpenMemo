"""回归测试：AI 输出 JSON 后追加散文时，不得泄漏原始 JSON 到回复"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openmemo.ai import _extract_json  # noqa: E402


def test_json_followed_by_prose():
    """AI 在 JSON 后追加散文/思考 → 仍能提取 JSON，不泄漏原文。"""
    content = (
        '{"action": "chat", "task": null, "tasks": [], "appointment": null, '
        '"search": null, "reply": "你好呀！今天星期六～有什么需要我帮忙的吗？"}\n\n'
        "Wait, I need to double-check the current time injection. "
        "The system prompt says today is Saturday."
    )
    parsed = _extract_json(content)
    assert parsed is not None
    assert parsed["action"] == "chat"
    assert "星期六" in parsed["reply"]
    # 关键：reply 里绝不能出现 JSON 结构
    assert not parsed["reply"].startswith("{")


def test_json_with_code_fence_and_prose():
    """代码块包裹的 JSON + 后面追加文字 → 正常提取。"""
    content = (
        '```json\n{"action": "chat", "reply": "好的，已记下。"}\n```\n'
        "（以上是系统内部格式，用户无需看到）"
    )
    parsed = _extract_json(content)
    assert parsed is not None
    assert parsed["reply"] == "好的，已记下。"


def test_truncated_json_still_repairs():
    """截断的 JSON（缺闭合括号）仍能修复（原有能力不退化）。"""
    content = '{"action": "task_added", "task": {"content": "买牛奶", "time": "明天早上8点"}, "reply": "好的'
    parsed = _extract_json(content)
    assert parsed is not None
    assert parsed["action"] == "task_added"


def test_no_json_returns_none():
    """完全没有 JSON → None（走兜底回复，不泄漏原文）。"""
    assert _extract_json("我今天心情不错，随便聊聊") is None
    assert _extract_json("") is None
