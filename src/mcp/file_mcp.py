import os
import json
import shutil
from typing import Optional, List, Dict, Any

from src.mcp.mcp_client import MCPClient
from src.utils.logger import setup_logger

logger = setup_logger("file_mcp")


@MCPClient.register_tool("FileMCP")
class FileMCP(MCPClient):
    """
    文件操作 MCP 工具。
    
    提供本地文件系统操作功能：
    - 文件读取/写入
    - 文件/目录列表
    - 文件/目录创建、删除、移动
    - 目录结构查看
    """
    
    def __init__(self):
        super().__init__()
        # 限制可操作的根目录（安全考虑）
        self._base_dirs = [
            os.path.expanduser("~"),
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.path.join(os.path.expanduser("~"), "Documents"),
            os.path.join(os.path.expanduser("~"), "Downloads"),
        ]
    
    def _validate_path(self, path: str) -> str:
        """
        验证路径安全性，防止路径遍历攻击。
        """
        abs_path = os.path.abspath(os.path.expanduser(path))
        
        # 检查路径是否在允许的根目录下
        allowed = False
        for base_dir in self._base_dirs:
            if abs_path.startswith(base_dir):
                allowed = True
                break
        
        if not allowed:
            raise PermissionError(f"Path not in allowed directories: {path}. Allowed: {self._base_dirs}")
        
        return abs_path
    
    def read_file(self, path: str, encoding: str = "utf-8", max_lines: int = 100) -> dict:
        """
        读取本地文件内容。
        
        Args:
            path: 文件路径（支持 ~ 表示用户主目录）
            encoding: 文件编码，默认为 utf-8
            max_lines: 最大读取行数，默认为 100 行
        
        Returns:
            dict: 包含以下字段的字典：
                - path: 实际读取的文件路径
                - content: 文件内容
                - lines: 总行数
                - truncated: 是否截断（超过 max_lines）
        """
        safe_path = self._validate_path(path)
        
        if not os.path.isfile(safe_path):
            raise FileNotFoundError(f"File not found: {path}")
        
        with open(safe_path, "r", encoding=encoding) as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        truncated = total_lines > max_lines
        
        content = "".join(lines[:max_lines])
        
        result = {
            "path": safe_path,
            "content": content,
            "lines": total_lines,
            "truncated": truncated,
        }
        
        logger.info(f"read_file: {path}, lines={total_lines}, truncated={truncated}")
        return result
    
    def write_file(self, path: str, content: str, encoding: str = "utf-8", append: bool = False) -> dict:
        """
        写入文件内容。
        
        Args:
            path: 文件路径（支持 ~ 表示用户主目录）
            content: 要写入的内容
            encoding: 文件编码，默认为 utf-8
            append: 是否追加写入，默认为 False（覆盖写入）
        
        Returns:
            dict: 包含以下字段的字典：
                - path: 实际写入的文件路径
                - success: 是否成功
                - size: 写入的字节数
        """
        safe_path = self._validate_path(path)
        
        mode = "a" if append else "w"
        
        with open(safe_path, mode, encoding=encoding) as f:
            f.write(content)
        
        size = os.path.getsize(safe_path)
        
        result = {
            "path": safe_path,
            "success": True,
            "size": size,
        }
        
        logger.info(f"write_file: {path}, mode={mode}, size={size}")
        return result
    
    def list_directory(self, path: str = ".", recursive: bool = False, file_types: Optional[List[str]] = None) -> dict:
        """
        列出目录内容。
        
        Args:
            path: 目录路径，默认为当前目录
            recursive: 是否递归列出子目录，默认为 False
            file_types: 过滤文件类型（扩展名列表，如 ['.txt', '.py']），不指定则返回所有文件
        
        Returns:
            dict: 包含以下字段的字典：
                - path: 目录路径
                - files: 文件列表（每个文件包含 name, path, size, is_dir, modified）
                - dirs: 子目录列表
                - total: 总文件数
        """
        safe_path = self._validate_path(path)
        
        if not os.path.isdir(safe_path):
            raise NotADirectoryError(f"Not a directory: {path}")
        
        files = []
        dirs = []
        
        if recursive:
            for root, dir_names, file_names in os.walk(safe_path):
                for d in dir_names:
                    d_path = os.path.join(root, d)
                    dirs.append({
                        "name": d,
                        "path": d_path,
                        "modified": os.path.getmtime(d_path),
                    })
                
                for f in file_names:
                    if file_types:
                        ext = os.path.splitext(f)[1].lower()
                        if ext not in [t.lower() if t.startswith('.') else f'.{t.lower()}' for t in file_types]:
                            continue
                    
                    f_path = os.path.join(root, f)
                    files.append({
                        "name": f,
                        "path": f_path,
                        "size": os.path.getsize(f_path),
                        "is_dir": False,
                        "modified": os.path.getmtime(f_path),
                    })
        else:
            for item in os.listdir(safe_path):
                item_path = os.path.join(safe_path, item)
                
                if os.path.isdir(item_path):
                    dirs.append({
                        "name": item,
                        "path": item_path,
                        "modified": os.path.getmtime(item_path),
                    })
                elif os.path.isfile(item_path):
                    if file_types:
                        ext = os.path.splitext(item)[1].lower()
                        if ext not in [t.lower() if t.startswith('.') else f'.{t.lower()}' for t in file_types]:
                            continue
                    
                    files.append({
                        "name": item,
                        "path": item_path,
                        "size": os.path.getsize(item_path),
                        "is_dir": False,
                        "modified": os.path.getmtime(item_path),
                    })
        
        result = {
            "path": safe_path,
            "files": files,
            "dirs": dirs,
            "total": len(files),
        }
        
        logger.info(f"list_directory: {path}, files={len(files)}, dirs={len(dirs)}")
        return result
    
    def create_directory(self, path: str, exist_ok: bool = True) -> dict:
        """
        创建目录。
        
        Args:
            path: 目录路径
            exist_ok: 目录已存在时是否忽略错误
        
        Returns:
            dict: 包含以下字段的字典：
                - path: 创建的目录路径
                - created: 是否成功创建
                - existed: 目录是否已存在
        """
        safe_path = self._validate_path(path)
        
        existed = os.path.exists(safe_path)
        
        try:
            os.makedirs(safe_path, exist_ok=exist_ok)
            result = {
                "path": safe_path,
                "created": True,
                "existed": existed,
            }
            logger.info(f"create_directory: {path}, existed={existed}")
            return result
        except OSError as e:
            logger.error(f"Failed to create directory: {e}")
            raise
    
    def delete_file(self, path: str) -> dict:
        """
        删除文件。
        
        Args:
            path: 文件路径
        
        Returns:
            dict: 包含以下字段的字典：
                - path: 删除的文件路径
                - success: 是否成功删除
        """
        safe_path = self._validate_path(path)
        
        if not os.path.isfile(safe_path):
            raise FileNotFoundError(f"File not found: {path}")
        
        os.remove(safe_path)
        
        result = {
            "path": safe_path,
            "success": True,
        }
        
        logger.info(f"delete_file: {path}")
        return result
    
    def delete_directory(self, path: str, recursive: bool = False) -> dict:
        """
        删除目录。
        
        Args:
            path: 目录路径
            recursive: 是否递归删除目录内容
        
        Returns:
            dict: 包含以下字段的字典：
                - path: 删除的目录路径
                - success: 是否成功删除
        """
        safe_path = self._validate_path(path)
        
        if not os.path.isdir(safe_path):
            raise NotADirectoryError(f"Not a directory: {path}")
        
        if recursive:
            shutil.rmtree(safe_path)
        else:
            os.rmdir(safe_path)
        
        result = {
            "path": safe_path,
            "success": True,
        }
        
        logger.info(f"delete_directory: {path}, recursive={recursive}")
        return result
    
    def move_file(self, source: str, destination: str) -> dict:
        """
        移动或重命名文件。
        
        Args:
            source: 源文件路径
            destination: 目标路径
        
        Returns:
            dict: 包含以下字段的字典：
                - source: 源路径
                - destination: 目标路径
                - success: 是否成功
        """
        safe_source = self._validate_path(source)
        safe_dest = self._validate_path(destination)
        
        if not os.path.exists(safe_source):
            raise FileNotFoundError(f"Source not found: {source}")
        
        os.makedirs(os.path.dirname(safe_dest), exist_ok=True)
        shutil.move(safe_source, safe_dest)
        
        result = {
            "source": safe_source,
            "destination": safe_dest,
            "success": True,
        }
        
        logger.info(f"move_file: {source} -> {destination}")
        return result
    
    def search_files(self, directory: str, pattern: str = "", file_types: Optional[List[str]] = None, max_results: int = 50) -> dict:
        """
        在目录中搜索文件。
        
        Args:
            directory: 搜索的根目录
            pattern: 文件名过滤模式（支持模糊匹配）
            file_types: 过滤文件类型
            max_results: 最大返回结果数
        
        Returns:
            dict: 包含以下字段的字典：
                - directory: 搜索目录
                - pattern: 使用的模式
                - results: 匹配的文件列表
                - total: 总匹配数
        """
        safe_dir = self._validate_path(directory)
        
        if not os.path.isdir(safe_dir):
            raise NotADirectoryError(f"Not a directory: {directory}")
        
        results = []
        pattern_lower = pattern.lower() if pattern else ""
        
        for root, dirs, files in os.walk(safe_dir):
            for f in files:
                if len(results) >= max_results:
                    break
                
                if pattern_lower and pattern_lower not in f.lower():
                    continue
                
                if file_types:
                    ext = os.path.splitext(f)[1].lower()
                    allowed_exts = [t.lower() if t.startswith('.') else f'.{t.lower()}' for t in file_types]
                    if ext not in allowed_exts:
                        continue
                
                f_path = os.path.join(root, f)
                results.append({
                    "name": f,
                    "path": f_path,
                    "size": os.path.getsize(f_path),
                    "modified": os.path.getmtime(f_path),
                })
            
            if len(results) >= max_results:
                break
        
        result = {
            "directory": safe_dir,
            "pattern": pattern,
            "results": results,
            "total": len(results),
        }
        
        logger.info(f"search_files: dir={directory}, pattern={pattern}, found={len(results)}")
        return result
