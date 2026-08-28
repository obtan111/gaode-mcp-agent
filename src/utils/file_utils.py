"""文件处理工具函数。"""


def is_file_size_valid(file_content: bytes, max_size_bytes: int) -> bool:
    """检查文件大小是否在限制内。"""
    return len(file_content) <= max_size_bytes
