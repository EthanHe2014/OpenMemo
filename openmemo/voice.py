"""Voice output module - Edge TTS + Mac mini speakers"""
import asyncio
import os
import subprocess
import hashlib
from pathlib import Path
from .config import TTS_VOICE, AUDIO_DIR


async def generate_speech(text: str, voice: str = None, rate: str = "+0%") -> Path:
    """Generate speech audio file using Edge TTS.
    
    Args:
        text: Text to speak
        voice: Voice name (default from config)
        rate: Speech rate adjustment (e.g. "-10%" slower, "+10%" faster)
    
    Returns:
        Path to generated audio file
    """
    import edge_tts
    
    voice = voice or TTS_VOICE
    
    # Generate unique filename from text+rate hash
    text_hash = hashlib.md5(f"{text}{rate}".encode()).hexdigest()[:12]
    output_path = AUDIO_DIR / f"tts_{text_hash}.mp3"
    
    # Skip if already generated (cache)
    if output_path.exists():
        return output_path
    
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(output_path))
    
    return output_path


def play_audio(audio_path: Path, volume: float = 1.0):
    """Play audio file on Mac mini speakers using afplay.
    
    Args:
        audio_path: Path to audio file
        volume: Volume level (0.0 to 1.0)
    """
    if not audio_path.exists():
        print(f"Audio file not found: {audio_path}")
        return
    
    # Use afplay on macOS
    cmd = ["afplay", str(audio_path)]
    if volume != 1.0:
        cmd.extend(["-v", str(volume)])
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"Audio playback error: {e}")


async def speak(text: str, voice: str = None, volume: float = 1.0, rate: str = "+0%") -> bool:
    """Generate speech and play it immediately.
    
    Args:
        text: Text to speak
        voice: Voice name
        volume: Volume level
        rate: Speech rate (e.g. "-10%" slower)
    
    Returns:
        True if successful
    """
    try:
        audio_path = await generate_speech(text, voice, rate)
        # Run playback in a thread to not block
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, play_audio, audio_path, volume)
        return True
    except Exception as e:
        print(f"Speech error: {e}")
        return False


def speak_sync(text: str, voice: str = None, volume: float = 1.0, rate: str = "+0%") -> bool:
    """Synchronous version of speak()"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, speak(text, voice, volume, rate))
                return future.result(timeout=30)
        else:
            return asyncio.run(speak(text, voice, volume, rate))
    except Exception as e:
        print(f"Sync speech error: {e}")
        return False


# Available Chinese voices for Edge TTS
CHINESE_VOICES = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",      # Female, warm
    "xiaoyi": "zh-CN-XiaoyiNeural",           # Female, young
    "yunjian": "zh-CN-YunjianNeural",          # Male, mature
    "yunxi": "zh-CN-YunxiNeural",              # Male, young
    "yunxia": "zh-CN-YunxiaNeural",            # Male, child
    "yunyang": "zh-CN-YunyangNeural",          # Male, news anchor
}
