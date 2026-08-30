"""语音情绪识别模块 —— SenseVoice（本地离线，sherpa-onnx）

输入一段 WAV → 输出 (文本, 情绪标签, 语种)。
SenseVoice 一次推理同时给出：
- 转写文本（中文等）
- 情绪：高兴 / 悲伤 / 生气 / 恐惧 / 惊讶 / 中性（中文标签）
- 事件（笑声/掌声等，暂不使用）

完全离线，音频不出本机。模型在 models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/
"""
import wave
from pathlib import Path

from .config import AUDIO_DIR

# 模型目录（仓库 models/ 下）
MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"

_recognizer = None  # 懒加载单例（SenseVoice 模型 ~1GB，加载慢，只做一次）

# 情绪标签映射（模型输出英文标签 → 中文；未知保持原样）
_EMOTION_ZH = {
    "happy": "高兴",
    "sad": "悲伤",
    "angry": "生气",
    "fear": "恐惧",
    "surprise": "惊讶",
    "neutral": "中性",
    "hate": "厌恶",
    "pleasant": "愉悦",
    "disgust": "厌恶",
    "excited": "兴奋",
}


def emotion_available() -> bool:
    """模型文件是否齐全（缺模型时优雅降级）。"""
    return (MODEL_DIR / "model.int8.onnx").exists() and (MODEL_DIR / "tokens.txt").exists()


def _get_recognizer():
    """懒加载 SenseVoice 离线识别器。"""
    global _recognizer
    if _recognizer is not None:
        return _recognizer

    import sherpa_onnx

    _recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(MODEL_DIR / "model.int8.onnx"),
        tokens=str(MODEL_DIR / "tokens.txt"),
        num_threads=4,
        use_itn=True,
        debug=False,
    )
    return _recognizer


def _read_pcm(wav_path: Path):
    """从 WAV 读出 (samples: list[float], sample_rate: int)。
    只处理 16-bit PCM；采样率不是 16k 先用 ffmpeg 重采样。"""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            sr = wf.getframerate()
            n_channels = wf.getnchannels()
            sw = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
    except (wave.Error, OSError):
        return None, None

    if sw != 2:
        return None, None

    import array
    samples = array.array("h", frames)
    if n_channels > 1:
        # 取第一个声道
        samples = samples[0::n_channels]

    if sr != 16000:
        # 尝试 ffmpeg 重采样到 16k
        import subprocess, tempfile, os
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tf.write(wav_path.read_bytes())
                tmp_in = tf.name
            tmp_out = tempfile.mktemp(suffix=".wav")
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_in, "-ar", "16000", "-ac", "1", tmp_out],
                capture_output=True, timeout=30,
            )
            os.unlink(tmp_in)
            if r.returncode == 0:
                with wave.open(tmp_out, "rb") as wf2:
                    sr = 16000
                    frames2 = wf2.readframes(wf2.getnframes())
                samples = array.array("h", frames2)
                os.unlink(tmp_out)
            else:
                os.unlink(tmp_out)
                return None, None
        except Exception:
            return None, None

    floats = [float(s) / 32768.0 for s in samples]
    return floats, sr


def detect_emotion(wav_path: str | Path) -> dict:
    """识别一段 WAV 的情绪。返回 {"text", "emotion", "language"}。
    失败时 emotion/text 为空字符串。"""
    result = {"text": "", "emotion": "", "language": ""}
    if not emotion_available():
        print("[情绪] SenseVoice 模型缺失，跳过")
        return result

    wav_path = Path(wav_path)
    if not wav_path.exists():
        return result

    samples, sample_rate = _read_pcm(wav_path)
    if samples is None or len(samples) < 1600:  # 至少 0.1s
        return result

    try:
        recognizer = _get_recognizer()
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        recognizer.decode_stream(stream)
        r = stream.result

        result["text"] = (r.text or "").strip()
        # 情绪/语种字段：新版本 sherpa-onnx 才有，用 getattr 兼容
        emotion = getattr(r, "emotion", None)
        if emotion:
            result["emotion"] = _EMOTION_ZH.get(emotion.lower(), emotion)
        lang = getattr(r, "lang", None)
        if lang:
            result["language"] = str(lang)
        print(f"[情绪] SenseVoice: emotion={result['emotion']} lang={result['language']} text={result['text'][:40]}")
    except Exception as e:
        print(f"[情绪] 识别出错：{e}")
    return result
