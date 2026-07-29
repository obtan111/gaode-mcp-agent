from __future__ import annotations
import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()


class Config:
    """
    配置管理类，负责从环境变量中读取所有配置项。
    
    使用 @property 装饰器提供类型安全的配置访问，
    支持字符串、整数、浮点数等多种类型。
    
    配置项包括：
    - 数据库连接配置（Supabase）
    - 大语言模型 API Key
    - RAG 检索参数
    - 工具调用限制
    - 日志级别
    - 数据库连接池配置
    """
    @staticmethod
    def _get_env(name: str, default: str = "") -> str:
        """获取字符串类型的环境变量"""
        return os.getenv(name, default)

    @staticmethod
    def _get_env_int(name: str, default: int = 0) -> int:
        """获取整数类型的环境变量，无法解析时返回默认值"""
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _get_env_float(name: str, default: float = 0.0) -> float:
        """获取浮点数类型的环境变量，无法解析时返回默认值"""
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @property
    def SUPABASE_URL(self) -> str:
        return self._get_env("SUPABASE_URL", "")

    @property
    def SUPABASE_KEY(self) -> str:
        return self._get_env("SUPABASE_KEY", "")

    @property
    def DEEPSEEK_API_KEY(self) -> str:
        return self._get_env("DEEPSEEK_API_KEY", "")

    @property
    def ZHIPU_API_KEY(self) -> str:
        return self._get_env("ZHIPU_API_KEY", "")

    @property
    def AMAP_API_KEY(self) -> str:
        return self._get_env("AMAP_API_KEY", "")

    @property
    def MODEL_TEMPERATURE(self) -> float:
        return self._get_env_float("MODEL_TEMPERATURE", 0.7)

    @property
    def CHUNK_SIZE(self) -> int:
        return self._get_env_int("CHUNK_SIZE", 512)

    @property
    def CHUNK_OVERLAP(self) -> int:
        return self._get_env_int("CHUNK_OVERLAP", 50)

    @property
    def RETRIEVE_TOP_K(self) -> int:
        return self._get_env_int("RETRIEVE_TOP_K", 5)

    @property
    def RRF_K(self) -> int:
        return self._get_env_int("RRF_K", 60)

    @property
    def CROSS_ENCODER_THRESHOLD(self) -> float:
        # 轻量级精排器分数范围 [0, 1]，默认 0.1 过滤完全不相关的结果
        # 如果安装了 sentence-transformers (Cross-Encoder)，可提高到 0.3-0.5
        return self._get_env_float("CROSS_ENCODER_THRESHOLD", 0.1)

    @property
    def MAX_TOOL_CALLS(self) -> int:
        return self._get_env_int("MAX_TOOL_CALLS", 10)

    @property
    def LOG_LEVEL(self) -> str:
        return self._get_env("LOG_LEVEL", "INFO").upper()

    @property
    def CONNECTION_POOL_SIZE(self) -> int:
        return self._get_env_int("CONNECTION_POOL_SIZE", 10)

    @property
    def CONNECTION_TIMEOUT(self) -> int:
        return self._get_env_int("CONNECTION_TIMEOUT", 30)

    @property
    def HEARTBEAT_INTERVAL(self) -> int:
        return self._get_env_int("HEARTBEAT_INTERVAL", 60)

    @property
    def LOCAL_VECTOR_CACHE_DIR(self) -> str:
        return self._get_env("LOCAL_VECTOR_CACHE_DIR", "./.vector_cache")

    @property
    def MAX_TEXT_LENGTH(self) -> int:
        return self._get_env_int("MAX_TEXT_LENGTH", 2000)

    @property
    def PDF_CHUNK_SIZE(self) -> int:
        return self._get_env_int("PDF_CHUNK_SIZE", 1000)

    @property
    def PDF_CHUNK_OVERLAP(self) -> int:
        return self._get_env_int("PDF_CHUNK_OVERLAP", 100)

    @property
    def MD_CHUNK_SIZE(self) -> int:
        return self._get_env_int("MD_CHUNK_SIZE", 800)

    @property
    def MD_CHUNK_OVERLAP(self) -> int:
        return self._get_env_int("MD_CHUNK_OVERLAP", 80)

    @property
    def TXT_CHUNK_SIZE(self) -> int:
        return self._get_env_int("TXT_CHUNK_SIZE", 800)

    @property
    def TXT_CHUNK_OVERLAP(self) -> int:
        return self._get_env_int("TXT_CHUNK_OVERLAP", 80)

    @property
    def CSV_CHUNK_SIZE(self) -> int:
        return self._get_env_int("CSV_CHUNK_SIZE", 500)

    @property
    def CSV_CHUNK_OVERLAP(self) -> int:
        return self._get_env_int("CSV_CHUNK_OVERLAP", 0)

    @property
    def JSON_CHUNK_SIZE(self) -> int:
        return self._get_env_int("JSON_CHUNK_SIZE", 1000)

    @property
    def JSON_CHUNK_OVERLAP(self) -> int:
        return self._get_env_int("JSON_CHUNK_OVERLAP", 100)


def validate_config(config: Config = None) -> tuple[bool, list[str]]:
    if config is None:
        config = Config()

    errors = []

    if not config.SUPABASE_URL:
        errors.append("SUPABASE_URL is not set")
    if not config.SUPABASE_KEY:
        errors.append("SUPABASE_KEY is not set")

    if not (config.DEEPSEEK_API_KEY or config.ZHIPU_API_KEY):
        errors.append("At least one LLM API key (DEEPSEEK_API_KEY or ZHIPU_API_KEY) must be set")

    if config.MODEL_TEMPERATURE < 0.0 or config.MODEL_TEMPERATURE > 1.0:
        errors.append("MODEL_TEMPERATURE must be between 0.0 and 1.0")

    if config.CHUNK_SIZE <= 0:
        errors.append("CHUNK_SIZE must be positive")
    if config.CHUNK_OVERLAP < 0 or config.CHUNK_OVERLAP >= config.CHUNK_SIZE:
        errors.append("CHUNK_OVERLAP must be non-negative and less than CHUNK_SIZE")
    if config.RETRIEVE_TOP_K <= 0:
        errors.append("RETRIEVE_TOP_K must be positive")
    if config.RRF_K <= 0:
        errors.append("RRF_K must be positive")

    if config.MAX_TOOL_CALLS <= 0:
        errors.append("MAX_TOOL_CALLS must be positive")

    if config.LOG_LEVEL not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        errors.append("LOG_LEVEL must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL")

    if config.CONNECTION_POOL_SIZE <= 0:
        errors.append("CONNECTION_POOL_SIZE must be positive")
    if config.CONNECTION_TIMEOUT <= 0:
        errors.append("CONNECTION_TIMEOUT must be positive")
    if config.HEARTBEAT_INTERVAL <= 0:
        errors.append("HEARTBEAT_INTERVAL must be positive")

    return len(errors) == 0, errors


def load_and_validate_config() -> Config:
    config = Config()
    is_valid, errors = validate_config(config)
    if not is_valid:
        raise ValueError("Configuration validation failed:\n" + "\n".join(f"- {e}" for e in errors))
    return config
