"""语音输入模块 —— 本地离线 STT（sherpa-onnx 中文流式模型）

不依赖任何云服务 / 系统识别服务：
- 适用于不支持 Web Speech API 的浏览器 / 平台（"不兼容手机"）
- 完全离线，音频不出本机
- 中文流式 zipformer 模型（~150MB，已在 models/ 目录）

用法：
    from .stt import transcribe_wav, local_stt_available
    text = transcribe_wav("/tmp/recording.wav")   # 返回识别文本或 None
"""
import os
import wave
from pathlib import Path

from .config import AUDIO_DIR

# 模型目录（仓库 models/ 下）
MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23"

_recognizer = None  # 懒加载的单例（加载模型很慢，只做一次）


def local_stt_available() -> bool:
    """模型文件是否齐全（缺模型时优雅降级）。"""
    needed = [
        MODEL_DIR / "encoder-epoch-99-avg-1.onnx",
        MODEL_DIR / "decoder-epoch-99-avg-1.onnx",
        MODEL_DIR / "joiner-epoch-99-avg-1.onnx",
        MODEL_DIR / "tokens.txt",
    ]
    return all(p.exists() for p in needed)


def _get_recognizer():
    """懒加载 sherpa-onnx 流式识别器（线程安全：一次初始化，全程复用）。"""
    global _recognizer
    if _recognizer is not None:
        return _recognizer

    import sherpa_onnx

    _recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
        encoder=str(MODEL_DIR / "encoder-epoch-99-avg-1.onnx"),
        decoder=str(MODEL_DIR / "decoder-epoch-99-avg-1.onnx"),
        joiner=str(MODEL_DIR / "joiner-epoch-99-avg-1.onnx"),
        tokens=str(MODEL_DIR / "tokens.txt"),
        num_threads=2,
        sample_rate=16000,
        feature_dim=80,
        enable_endpoint_detection=True,
        rule1_min_trailing_silence=2.4,
        rule2_min_trailing_silence=1.2,
        rule3_min_utterance_length=300,  # 0.3s 起算
    )
    return _recognizer


def transcribe_wav(wav_path: str | Path) -> str | None:
    """识别一段 WAV（16kHz 单声道 PCM）。返回文本；失败/静音返回 None。

    兼容 16-bit PCM；采样率不对时用 sox/ffmpeg 重采样（若可用）。
    """
    if not local_stt_available():
        print("本地 STT 模型缺失，跳过识别")
        return None

    wav_path = Path(wav_path)
    if not wav_path.exists():
        return None

    # 用 wave 模块读原始 16-bit PCM（sherpa-onnx 流式接口直接吃 PCM）
    samples, sample_rate = _read_pcm(wav_path)
    if samples is None:
        return None

    recognizer = _get_recognizer()
    stream = recognizer.create_stream()

    # 流式喂入：每块 0.1s（1600 样本），模拟实时流
    chunk = int(sample_rate * 0.1)
    for i in range(0, len(samples), chunk):
        block = samples[i:i + chunk]
        stream.accept_waveform(sample_rate, block)
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)

    # 收尾：灌结束标记，取最终文本
    stream.input_finished()
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    text = recognizer.get_result(stream).strip()

    if not text:
        return None
    return text


def _read_pcm(wav_path: Path):
    """从 WAV 读出 (samples: list[float], sample_rate: int)。
    非 16k 采样率先尝试 ffmpeg 重采样；失败返回 (None, None)。
    """
    try:
        with wave.open(str(wav_path), "rb") as wf:
            sr = wf.getframerate()
            n_channels = wf.getnchannels()
            sw = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())

        if sw != 2:  # 非 16-bit：不折腾，直接放弃
            print(f"本地 STT：只支持 16-bit PCM，收到 {sw*8}-bit")
            return None, None

        # 单声道 16k 直接解析
        if sr == 16000 and n_channels == 1:
            import array
            pcm = array.array("h")
            pcm.frombytes(frames)
            return [x / 32768.0 for x in pcm], sr

        # 其它采样率/声道：尝试 ffmpeg 重采样到 16k mono
        import subprocess, tempfile
        resampled = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        resampled.close()
        try:
            cmd = [
                "ffmpeg", "-y", "-i", str(wav_path),
                "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                resampled.name,
            ]
            subprocess.run(cmd, capture_output=True, timeout=30, check=True)
            with wave.open(resampled.name, "rb") as wf:
                sr = wf.getframerate()
                frames = wf.readframes(wf.getnframes())
            import array
            pcm = array.array("h")
            pcm.frombytes(frames)
            return [x / 32768.0 for x in pcm], sr
        except Exception as e:
            print(f"本地 STT：重采样失败 {e}")
            return None, None
        finally:
            try:
                os.unlink(resampled.name)
            except OSError:
                pass
    except Exception as e:
        print(f"本地 STT：读 WAV 失败 {e}")
        return None, None
