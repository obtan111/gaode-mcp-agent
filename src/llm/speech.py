import os
import json
import struct
import requests
from typing import Optional, Union, Dict, Any

from src.config import Config
from src.utils.logger import logger
from src.utils.retry import retry
from src.utils.exception import ServiceError, ValidationError


class SpeechRecognition:
    """
    语音识别组件，将音频文件转换为文本。

    使用智谱 AI 的 GLM-ASR-2512 模型，支持 WAV、MP3 格式。
    通过 multipart/form-data 方式上传音频文件。

    使用示例：
        recognizer = SpeechRecognition()
        text = recognizer.recognize("audio.wav")
    """

    SUPPORTED_FORMATS = ["wav", "mp3"]
    MAX_FILE_SIZE_MB = 25
    MAX_DURATION_SECONDS = 30

    def __init__(self):
        self.config = Config()
        self._api_key = self.config.ZHIPU_API_KEY
        self._base_url = "https://open.bigmodel.cn/api/paas/v4/audio/transcriptions"

    def _validate_api_key(self):
        if not self._api_key:
            raise ServiceError("ZHIPU_API_KEY is not configured")

    def _validate_audio_format(self, format: str):
        if format.lower() not in self.SUPPORTED_FORMATS:
            raise ValidationError(
                f"Unsupported audio format: {format}. Supported formats: {', '.join(self.SUPPORTED_FORMATS)}"
            )

    def _get_audio_bytes(self, audio_source: Union[str, bytes]) -> bytes:
        if isinstance(audio_source, str):
            if not os.path.exists(audio_source):
                raise ValidationError(f"Audio file not found: {audio_source}")
            file_size = os.path.getsize(audio_source)
            if file_size > self.MAX_FILE_SIZE_MB * 1024 * 1024:
                raise ValidationError(
                    f"Audio file too large: {file_size} bytes. Max allowed: {self.MAX_FILE_SIZE_MB} MB"
                )
            with open(audio_source, "rb") as f:
                return f.read()
        return audio_source

    def _get_filename(self, audio_source: Union[str, bytes]) -> str:
        if isinstance(audio_source, str):
            return os.path.basename(audio_source)
        return "audio.wav"

    def _detect_format(self, audio_source: Union[str, bytes]) -> str:
        if isinstance(audio_source, str):
            _, ext = os.path.splitext(audio_source)
            return ext[1:] if ext else "wav"
        return "wav"

    @retry(max_retries=2, backoff_factor=1.0, initial_delay=1.0, retry_on_exceptions=(requests.Timeout, requests.ConnectionError))
    def recognize(
        self,
        audio_source: Union[str, bytes],
        audio_format: Optional[str] = None,
        language: str = "zh",
    ) -> str:
        """
        识别音频文件中的语音内容。

        使用智谱 GLM-ASR-2512 模型进行语音识别，通过 multipart/form-data 上传。

        参数：
        - audio_source: 音频文件路径（str）或音频字节流（bytes）
        - audio_format: 音频格式（wav/mp3），为 None 时自动检测
        - language: 语音语言，默认 "zh"（中文）

        返回：
        - str: 识别出的文本内容

        异常：
        - ServiceError: API 调用失败或返回错误
        - ValidationError: 文件格式不支持或文件不存在
        """
        self._validate_api_key()

        if audio_format is None:
            audio_format = self._detect_format(audio_source)
        self._validate_audio_format(audio_format)

        audio_bytes = self._get_audio_bytes(audio_source)
        filename = self._get_filename(audio_source)

        headers = {
            "Authorization": f"Bearer {self._api_key}",
        }

        logger.info(f"Starting speech recognition, format={audio_format}, file={filename}, size={len(audio_bytes)} bytes")

        try:
            files = {
                "file": (filename, audio_bytes, f"audio/{audio_format}"),
            }
            data = {
                "model": "glm-asr-2512",
                "stream": "false",
            }

            response = requests.post(
                self._base_url,
                headers=headers,
                files=files,
                data=data,
                timeout=60,
            )

            if response.status_code == 401:
                raise ServiceError("ASR API unauthorized - check ZHIPU_API_KEY")
            elif response.status_code == 413:
                raise ServiceError(f"ASR API file too large (max {self.MAX_FILE_SIZE_MB}MB)")
            response.raise_for_status()

        except requests.RequestException as e:
            logger.error(f"ASR API request failed: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    logger.error(f"ASR API response error: {json.dumps(error_detail, ensure_ascii=False)}")
                    raise ServiceError(
                        f"ASR API request failed: {str(e)}, detail: "
                        f"{json.dumps(error_detail, ensure_ascii=False)[:300]}"
                    )
                except Exception:
                    logger.error(f"ASR API response text: {e.response.text[:500]}")
                    raise ServiceError(
                        f"ASR API request failed: {str(e)}, body: {e.response.text[:300]}"
                    )
            raise ServiceError(f"ASR API request failed: {str(e)}")

        result = response.json()

        if "error" in result:
            error_msg = result.get("error", {}).get("message", str(result["error"]))
            logger.error(f"ASR API returned error: {error_msg}")
            raise ServiceError(f"ASR API error: {error_msg}")

        text = result.get("text", "")
        logger.info(f"Speech recognition completed, text length={len(text)}")

        return text


def _ensure_playable_audio(audio_data: bytes) -> bytes:
    """把服务端音频保证为浏览器可播放的容器格式。

    实测发现智谱 GLM-TTS 默认返回**无容器头的裸 PCM**（24kHz / 16bit /
    单声道，小端序）——浏览器 Audio 元素无法直接播放（报
    "no supported source"）。检测到无常见容器魔数时，按上述参数包装成
    标准 WAV。
    """
    if audio_data[:4] in (b"RIFF", b"ID3\x00", b"OggS", b"fLaC") or audio_data[:2] == b"\xff\xfb":
        # 已是常见容器（wav/mp3/ogg/flac），原样返回
        return audio_data
    if len(audio_data) % 2 != 0:
        logger.warning("Suspicious PCM chunk size (odd bytes), returning as-is")
        return audio_data
    # 44 字节 RIFF/WAVE 头：PCM、单声道、16bit、24kHz
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(audio_data),
        b"WAVE",
        b"fmt ",
        16,          # fmt 块长度
        1,           # PCM
        1,           # 单声道
        24000,       # 采样率
        48000,       # 字节率 = 采样率 × 2
        2,           # 块对齐
        16,          # 位深
        b"data",
        len(audio_data),
    )
    logger.info("Wrapped raw PCM into WAV (24kHz/16bit/mono)")
    return header + audio_data


class TextToSpeech:
    """
    文本转语音组件，支持本地（pyttsx3）和云端（智谱 GLM-TTS）两种引擎。

    特性：
    - 自动检测可用引擎，pyttsx3 不可用时自动降级到智谱 API
    - 空文本安全处理，返回空字节而非抛出异常
    - 支持 WAV 和 MP3 两种输出格式
    - 使用最新的 GLM-TTS 模型 (glm-tts)

    使用示例：
        tts = TextToSpeech(engine="zhipu")
        audio_data = tts.synthesize("你好世界", output_format="mp3")
        with open("output.mp3", "wb") as f:
            f.write(audio_data)
    """

    SUPPORTED_FORMATS = ["wav", "mp3"]
    SUPPORTED_ENGINES = ["pyttsx3", "zhipu"]

    def __init__(self, engine: str = "pyttsx3"):
        self.config = Config()
        self.engine = engine.lower()
        self._validate_engine()
        self._engine_instance = None

    def _validate_engine(self):
        if self.engine not in self.SUPPORTED_ENGINES:
            raise ValidationError(
                f"Unsupported TTS engine: {self.engine}. Supported engines: {', '.join(self.SUPPORTED_ENGINES)}"
            )

    def _validate_format(self, format: str):
        if format.lower() not in self.SUPPORTED_FORMATS:
            raise ValidationError(
                f"Unsupported audio format: {format}. Supported formats: {', '.join(self.SUPPORTED_FORMATS)}"
            )

    def _get_pyttsx3_engine(self):
        if self._engine_instance is None:
            try:
                import pyttsx3
                self._engine_instance = pyttsx3.init()
            except ImportError:
                logger.warning("pyttsx3 is not installed, falling back to zhipu TTS")
                self.engine = "zhipu"
                return None
        return self._engine_instance

    def synthesize(
        self,
        text: str,
        volume: float = 1.0,
        rate: int = 200,
        pitch: int = 50,
        output_format: str = "wav",
    ) -> bytes:
        """
        将文本合成为语音。

        参数：
        - text: 要合成的文本内容
        - volume: 音量（0.0-1.0，仅 pyttsx3 引擎）
        - rate: 语速（次/分钟，仅 pyttsx3 引擎）
        - pitch: 音调（0-100，仅 pyttsx3 引擎）
        - output_format: 输出格式，支持 "wav" 和 "mp3"

        返回：
        - bytes: 合成的音频数据，空文本时返回空字节 b""
        """
        if not text or not text.strip():
            logger.warning("TTS synthesize called with empty text, skipping")
            return b""

        self._validate_format(output_format)

        if self.engine == "pyttsx3":
            return self._synthesize_pyttsx3(text, volume, rate, pitch, output_format)
        elif self.engine == "zhipu":
            return self._synthesize_zhipu(text, volume, rate, pitch, output_format)

    def _synthesize_pyttsx3(
        self,
        text: str,
        volume: float,
        rate: int,
        pitch: int,
        output_format: str,
    ) -> bytes:
        import io

        engine = self._get_pyttsx3_engine()
        if engine is None:
            return self._synthesize_zhipu(text, volume, rate, pitch, output_format)

        engine.setProperty("volume", max(0.0, min(1.0, volume)))
        engine.setProperty("rate", rate)

        voices = engine.getProperty("voices")
        for voice in voices:
            if "zh" in voice.language or "Chinese" in voice.name:
                engine.setProperty("voice", voice.id)
                break

        buffer = io.BytesIO()

        class FileWriter:
            def __init__(self, buf):
                self.buf = buf

            def write(self, data):
                self.buf.write(data)

            def close(self):
                pass

        try:
            from pyttsx3.drivers import audio
            audio.AudioSink = FileWriter(buffer)
        except Exception:
            pass

        engine.save_to_file(text, buffer)
        engine.runAndWait()

        buffer.seek(0)
        audio_data = buffer.read()
        logger.info(f"pyttsx3 TTS completed, audio length={len(audio_data)}")

        return audio_data

    @retry(max_retries=2, backoff_factor=1.0, initial_delay=0.5, retry_on_exceptions=(requests.Timeout, requests.ConnectionError))
    def _synthesize_zhipu(
        self,
        text: str,
        volume: float,
        rate: int,
        pitch: int,
        output_format: str,
    ) -> bytes:
        api_key = self.config.ZHIPU_API_KEY
        if not api_key:
            logger.warning("ZHIPU_API_KEY not configured, skipping TTS")
            return b""

        if not text or len(text) < 2:
            logger.warning(f"Skipping TTS synthesis: text too short ({len(text or '')} characters)")
            return b""

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        params = {
            "model": "glm-tts",
            "input": text[:1024],  # 智谱 TTS 硬上限 1024 字符（错误码 1214）
            "voice_id": "glm-tts-voice-qingci",
            "speed": 1.0,
            "volume": 1.0,
            "pitch": 1.0,
            "language": "zh",
        }

        logger.info(f"Starting zhipu TTS synthesis, text length={len(text)}")

        try:
            # 长文本（上限 1024 字符）合成耗时可能超过 30s，放宽超时
            response = requests.post(
                "https://open.bigmodel.cn/api/paas/v4/audio/speech",
                headers=headers,
                json=params,
                timeout=120,
            )
            if response.status_code == 404:
                logger.warning("Zhipu TTS API returned 404, service may be unavailable")
                return b""
            if response.status_code == 400:
                error_detail = response.json() if response.text else {}
                logger.error(f"Zhipu TTS API 400 error: {error_detail}")
                return b""
            response.raise_for_status()
            audio_data = response.content
            logger.info(f"Zhipu TTS completed, audio length={len(audio_data)}")
            return _ensure_playable_audio(audio_data)
        except requests.RequestException as e:
            logger.error(f"Zhipu TTS API request failed: {str(e)}")
            return b""

    def save_to_file(
        self,
        text: str,
        file_path: str,
        volume: float = 1.0,
        rate: int = 200,
        pitch: int = 50,
        output_format: Optional[str] = None,
    ):
        if output_format is None:
            _, ext = os.path.splitext(file_path)
            output_format = ext[1:] if ext else "wav"

        audio_data = self.synthesize(text, volume, rate, pitch, output_format)

        if not audio_data:
            logger.warning("TTS returned empty audio, skipping file save")
            return

        with open(file_path, "wb") as f:
            f.write(audio_data)

        logger.info(f"TTS audio saved to {file_path}")