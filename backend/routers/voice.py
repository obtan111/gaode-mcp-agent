"""语音接口：ASR（语音转文字）与 TTS（文字转语音）。

对应 Gradio 版的麦克风输入与语音播放按钮：
- POST /api/voice/tts：文本 → mp3 data URI（前端 <audio> 直接播放）
- POST /api/voice/asr：音频文件 → 文本（浏览器录音多为 webm，由前端转 WAV 后上传）
"""

import base64
import os
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.utils.logger import setup_logger

logger = setup_logger("voice_router")

router = APIRouter(prefix="/api/voice", tags=["voice"])

ALLOWED_AUDIO_EXT = {"wav", "mp3", "m4a", "webm", "ogg"}
MAX_AUDIO_BYTES = 20 * 1024 * 1024


class TTSRequest(BaseModel):
    # 智谱 TTS 硬限制 1024 字符（错误码 1214），放宽接收上限并在
    # 服务端截断，避免模型回答稍长就整段失败
    text: str = Field(..., min_length=1, max_length=8000)


@router.post("/tts")
def text_to_speech(req: TTSRequest):
    """把文本合成为 mp3，返回 base64 data URI。"""
    from backend.core.deps import get_text_to_speech

    # 智谱 TTS 输入硬上限 1024 字符（错误码 1214），超长部分截断
    text = req.text[:1024]
    try:
        audio_bytes = get_text_to_speech().synthesize(text, output_format="mp3")
    except Exception as exc:
        logger.error(f"TTS failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"语音合成失败：{exc}")
    if not audio_bytes or len(audio_bytes) == 0:
        logger.error("TTS returned empty audio (provider may have rejected the request)")
        raise HTTPException(
            status_code=500,
            detail="语音合成结果为空：请检查智谱 API 余额与语音服务状态",
        )
    return {
        "audio": "data:audio/mp3;base64," + base64.b64encode(audio_bytes).decode(),
    }


def _safe_ext(filename: str) -> str:
    """提取并校验扩展名：仅允许字母数字组成的白名单后缀。"""
    raw = os.path.splitext(filename or "")[1].lstrip(".").lower()
    if not raw or not raw.isalnum():
        return "wav"
    if raw not in ALLOWED_AUDIO_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的音频格式 .{raw}")
    return raw


@router.post("/asr")
async def speech_to_text(file: UploadFile = File(...)):
    """识别上传的音频文件，返回 {"text": "..."}。

    浏览器录音需要先在前端转成 WAV（见 frontend/src/api/voice.js 的
    blobToWav），服务端只负责落临时文件后交给识别组件。
    临时文件名完全由系统生成（NamedTemporaryFile），不使用上传文件名。
    """
    from backend.core.deps import get_speech_recognizer

    ext = _safe_ext(file.filename)

    content = await file.read()
    await file.close()
    if not content:
        raise HTTPException(status_code=400, detail="音频文件为空")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="音频超过 20MB 限制")

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            prefix="asr_", suffix=f".{ext}", delete=False
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        text = get_speech_recognizer().recognize(tmp_path)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"ASR failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"语音识别失败：{exc}")
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return {"text": (text or "").strip()}
