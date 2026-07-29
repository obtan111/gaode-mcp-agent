import json
import base64
from datetime import datetime
from typing import Any, Optional


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length] + suffix


def format_json(data: Any, indent: int = 2, ensure_ascii: bool = False) -> str:
    return json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)


def parse_json(text: str) -> Any:
    return json.loads(text)


def base64_encode(data: str, encoding: str = "utf-8") -> str:
    if isinstance(data, str):
        data = data.encode(encoding)
    return base64.b64encode(data).decode(encoding)


def base64_decode(data: str, encoding: str = "utf-8") -> str:
    return base64.b64decode(data).decode(encoding)


def format_datetime(
    dt: Optional[datetime] = None,
    fmt: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    if dt is None:
        dt = datetime.now()
    return dt.strftime(fmt)


def parse_datetime(text: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    return datetime.strptime(text, fmt)


def timestamp_to_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp)


def datetime_to_timestamp(dt: Optional[datetime] = None) -> float:
    if dt is None:
        dt = datetime.now()
    return dt.timestamp()


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.2f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.2f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs:.2f}s"
