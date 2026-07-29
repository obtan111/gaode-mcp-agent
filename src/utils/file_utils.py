"""
文件处理工具函数 - 兼容 Gradio 5.x 和 6.x
"""
import os
import io
import logging
from typing import Tuple, Optional, Any

logger = logging.getLogger(__name__)


def extract_file_info(file_obj: Any) -> Tuple[str, str, bytes]:
    """
    从 Gradio 文件对象中提取文件路径、文件名和内容。
    
    支持的输入类型：
    - NamedString (Gradio 6.x, type="filepath"): str 子类，表示文件路径
    - FileData (Gradio 6.x 原始数据): 包含 path 属性
    - tempfile._TemporaryFileWrapper (Gradio 5.x): 有 .name 和 .read() 方法
    - str: 直接的文件路径字符串
    - Path: pathlib.Path 对象
    - bytes: 直接的二进制内容
    
    Returns:
        Tuple of (file_path, file_name, file_content)
        如果提取失败，file_path 为空字符串
    """
    if file_obj is None:
        return "", "", b""
    
    file_path = ""
    file_content = b""
    file_name = ""
    
    # 处理 NamedString (Gradio 6.x filepath 模式 - 最常见)
    # NamedString 是 str 的子类，str() 转换即为文件路径
    if hasattr(file_obj, 'path') and hasattr(file_obj, 'orig_name'):
        # FileData 对象 (Gradio 6.x 内部数据类)
        # 这是 Gradio 内部使用的数据类，包含 path, orig_name, size 等
        file_path = str(file_obj.path) if file_obj.path else ""
        file_name = str(getattr(file_obj, 'orig_name', '') or os.path.basename(file_path))
        logger.debug(f"FileData: path={file_path}, orig_name={file_name}")
    elif hasattr(file_obj, 'name') and hasattr(file_obj, 'read'):
        # tempfile._TemporaryFileWrapper (Gradio 5.x)
        # 有 .name 属性和 .read() 方法
        file_path = str(file_obj.name)
        file_name = os.path.basename(file_path)
        logger.debug(f"TemporaryFile: name={file_path}")
        try:
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
            file_content = file_obj.read()
        except Exception as e:
            logger.warning(f"Failed to read TemporaryFile directly: {e}")
    elif isinstance(file_obj, (str, bytes)):
        # 纯字符串路径 或 纯字节内容
        if isinstance(file_obj, bytes):
            file_content = file_obj
            file_path = ""
            file_name = "uploaded_file"
        else:
            file_path = file_obj
            file_name = os.path.basename(file_path) if file_path else ""
        logger.debug(f"String/bytes: path={file_path}, len={len(file_content)}")
    elif hasattr(file_obj, 'read'):
        # 任何有 .read() 方法的对象
        logger.debug(f"File-like object with read(): {type(file_obj).__name__}")
        try:
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
            file_content = file_obj.read()
            if isinstance(file_content, str):
                file_content = file_content.encode('utf-8')
        except Exception as e:
            logger.warning(f"Failed to read file-like object: {e}")
        file_path = str(getattr(file_obj, 'name', '') or '')
        file_name = os.path.basename(file_path) if file_path else ""
    else:
        # 其他所有情况：尝试 str() 转换为路径
        file_path = str(file_obj) if file_obj else ""
        file_name = os.path.basename(file_path) if file_path else ""
        logger.debug(f"Unknown type {type(file_obj).__name__}, str() -> {file_path}")
    
    # 如果有文件路径但还没有内容，从路径读取
    if file_path and not file_content:
        try:
            if os.path.isfile(file_path):
                with open(file_path, "rb") as f:
                    file_content = f.read()
                logger.debug(f"Read from path: {file_path}, size={len(file_content)}")
            else:
                logger.warning(f"File path does not exist: {file_path}")
        except Exception as e:
            logger.error(f"Failed to read file from path {file_path}: {e}")
    
    # 如果没有文件名，从路径提取
    if not file_name and file_path:
        file_name = os.path.basename(file_path)
    
    return file_path, file_name, file_content


def get_file_extension(file_name: str) -> str:
    """从文件名提取扩展名"""
    if not file_name or "." not in file_name:
        return ""
    return file_name.split(".")[-1].lower()


def is_valid_file_type(file_name: str, allowed_extensions: set) -> bool:
    """检查文件类型是否在允许列表中"""
    ext = get_file_extension(file_name)
    return ext in allowed_extensions


def is_file_size_valid(file_content: bytes, max_size_bytes: int) -> bool:
    """检查文件大小是否在限制内"""
    return len(file_content) <= max_size_bytes
