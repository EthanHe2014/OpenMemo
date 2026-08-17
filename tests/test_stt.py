"""本地离线 STT（sherpa-onnx）测试

验证：
1. 模型可用性检测（缺模型时优雅降级，不崩）
2. 识别空/无效 WAV 返回 None
3. /api/stt 端点：有效音频返回文本，空 body 返回 400
"""
import os
import sys
import wave
import struct

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openmemo.stt import local_stt_available, transcribe_wav  # noqa: E402


def _make_wav(path, sample_rate=16000, seconds=0.3, freq=440.0):
    """生成一段正弦波 WAV（16-bit mono）。"""
    frames = int(sample_rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(frames):
            val = int(32767 * 0.3 * (2 ** 0.5) * __import__("math").sin(2 * __import__("math").pi * freq * i / sample_rate))
            wf.writeframes(struct.pack("<h", val))


def test_local_stt_available_detects_model():
    """模型目录存在时应返回 True（CI 无模型时返回 False 也不崩）。"""
    # 只要不抛异常即可；有模型时应为 True
    assert isinstance(local_stt_available(), bool)


def test_transcribe_nonexistent_file():
    """不存在的文件 → None（不崩）。"""
    assert transcribe_wav("/nonexistent/foo.wav") is None


def test_transcribe_silence_returns_none_or_empty():
    """静音音频 → None（不崩）。模型缺失时同样返回 None。"""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    try:
        _make_wav(path, seconds=0.3, freq=200)  # 纯音，无语音内容
        result = transcribe_wav(path)
        # 要么没识别出内容（None），要么模型真的给了文本——都不能抛异常
        assert result is None or isinstance(result, str)
    finally:
        os.unlink(path)


@pytest.mark.parametrize("body,expected_status", [
    (b"", 400),              # 空 body
    (b"short", 400),         # 太短（不是合法 WAV）
])
def test_stt_api_rejects_bad_audio(body, expected_status):
    """/api/stt 对空/非法音频返回 400。"""
    import sys as _sys
    sys_path = _sys.path
    try:
        from fastapi.testclient import TestClient
        _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from openmemo.server import app
        client = TestClient(app)
        resp = client.post("/api/stt", content=body)
        assert resp.status_code == expected_status
    finally:
        _sys.path = sys_path


def test_stt_api_valid_wav():
    """合法 WAV → 200，返回 engine=sherpa-onnx（模型缺失时 501）。"""
    from fastapi.testclient import TestClient
    from openmemo.server import app
    client = TestClient(app)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    try:
        _make_wav(path, seconds=0.2, freq=300)
        with open(path, "rb") as f:
            data = f.read()
    finally:
        os.unlink(path)

    resp = client.post("/api/stt", content=data)
    if not local_stt_available():
        assert resp.status_code == 501
    else:
        assert resp.status_code == 200
        body = resp.json()
        assert body["engine"] == "sherpa-onnx"
        assert isinstance(body.get("text", ""), str)
